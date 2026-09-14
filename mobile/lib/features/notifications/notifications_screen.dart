import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/api/api_exception.dart';
import '../../core/api/endpoints.dart';
import '../../core/connection/connection_controller.dart';
import '../../core/routing/app_router.dart';
import '../../core/theme/app_theme.dart';
import '../../core/widgets/app_widgets.dart';
import '../intelligence/labels.dart';

/// Filtre courant de l'inbox.
class NotificationFilter {
  const NotificationFilter({this.category, this.unreadOnly = false});

  final String? category;
  final bool unreadOnly;

  NotificationFilter withCategory(String? value) =>
      NotificationFilter(category: value, unreadOnly: unreadOnly);

  NotificationFilter withUnreadOnly(bool value) =>
      NotificationFilter(category: category, unreadOnly: value);

  @override
  bool operator ==(Object other) =>
      other is NotificationFilter && other.category == category && other.unreadOnly == unreadOnly;

  @override
  int get hashCode => Object.hash(category, unreadOnly);
}

final StateProvider<NotificationFilter> notificationFilterProvider =
    StateProvider<NotificationFilter>((Ref ref) => const NotificationFilter());

/// Inbox des notifications (CDC2 section 67).
final FutureProvider<Map<String, dynamic>> notificationsProvider =
    FutureProvider<Map<String, dynamic>>((Ref ref) {
  final NotificationFilter filter = ref.watch(notificationFilterProvider);
  return ref.watch(apiClientProvider).getJson(
        Endpoints.notifications,
        query: <String, dynamic>{
          'limit': 100,
          if (filter.category != null) 'category': filter.category,
          if (filter.unreadOnly) 'unreadOnly': true,
        },
      );
});

/// Nombre de notifications non lues, affiche en pastille ailleurs dans l'app.
final FutureProvider<int> unreadCountProvider = FutureProvider<int>((Ref ref) async {
  final Map<String, dynamic> payload =
      await ref.watch(apiClientProvider).getJson(Endpoints.notificationsUnreadCount);
  final Object? unread = payload['unread'];
  return unread is num ? unread.toInt() : 0;
});

/// Centre de notifications : ce que le Bridge a jugé digne d'être signalé.
class NotificationsScreen extends ConsumerWidget {
  const NotificationsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final AsyncValue<Map<String, dynamic>> inbox = ref.watch(notificationsProvider);

    return Scaffold(
      appBar: AppBar(
        title: const Text('Notifications'),
        actions: <Widget>[
          IconButton(
            tooltip: 'Tout marquer comme lu',
            onPressed: () => _markAllRead(context, ref),
            icon: const Icon(Icons.done_all),
          ),
          PopupMenuButton<String>(
            onSelected: (String action) => switch (action) {
              'test' => _sendTest(context, ref),
              'clear' => _deleteAll(context, ref),
              _ => _openPushStatus(context, ref),
            },
            itemBuilder: (BuildContext context) => const <PopupMenuEntry<String>>[
              PopupMenuItem<String>(value: 'test', child: Text('Envoyer une notification d’essai')),
              PopupMenuItem<String>(value: 'push', child: Text('État des notifications push')),
              PopupMenuDivider(),
              PopupMenuItem<String>(value: 'clear', child: Text('Tout supprimer')),
            ],
          ),
        ],
      ),
      body: Column(
        children: <Widget>[
          const _NotificationFilters(),
          const Divider(height: 1),
          Expanded(
            child: inbox.when(
              loading: () => const LoadingView(label: 'Chargement des notifications…'),
              error: (Object error, StackTrace stack) => ErrorView(
                message: error is ApiException ? error.message : 'Notifications indisponibles.',
                technical: error is ApiException ? error.technical : error.toString(),
                onRetry: () => ref.invalidate(notificationsProvider),
              ),
              data: (Map<String, dynamic> payload) => _NotificationList(payload: payload),
            ),
          ),
        ],
      ),
    );
  }

  Future<void> _markAllRead(BuildContext context, WidgetRef ref) async {
    try {
      await ref.read(apiClientProvider).postJson(Endpoints.notificationsReadAll);
      ref
        ..invalidate(notificationsProvider)
        ..invalidate(unreadCountProvider);
      if (!context.mounted) return;
      showToast(context, 'Toutes les notifications sont marquées comme lues.');
    } on ApiException catch (error) {
      if (!context.mounted) return;
      showToast(context, error.message, error: true);
    }
  }

  /// Vide la boîte de réception, après confirmation.
  ///
  /// L'effacement est définitif et porte sur tout, y compris ce qui n'a pas
  /// été lu : on demande donc confirmation plutôt que de l'exécuter d'un
  /// seul geste depuis un menu.
  Future<void> _deleteAll(BuildContext context, WidgetRef ref) async {
    final bool? confirme = await showDialog<bool>(
      context: context,
      builder: (BuildContext context) => AlertDialog(
        title: const Text('Tout supprimer ?'),
        content: const Text(
          'Toutes les notifications seront effacées, y compris celles que vous '
          'n’avez pas lues. Cette action est définitive.',
        ),
        actions: <Widget>[
          TextButton(
            onPressed: () => Navigator.of(context).pop(false),
            child: const Text('Annuler'),
          ),
          FilledButton(
            onPressed: () => Navigator.of(context).pop(true),
            child: const Text('Supprimer'),
          ),
        ],
      ),
    );
    if (confirme != true) return;

    try {
      final Map<String, dynamic> resultat =
          await ref.read(apiClientProvider).deleteJson(Endpoints.notifications);
      ref
        ..invalidate(notificationsProvider)
        ..invalidate(unreadCountProvider);
      if (!context.mounted) return;
      showToast(context, '${resultat['deleted'] ?? 0} notification(s) supprimée(s).');
    } on ApiException catch (error) {
      if (!context.mounted) return;
      showToast(context, error.message, error: true);
    }
  }

  Future<void> _sendTest(BuildContext context, WidgetRef ref) async {
    try {
      final Map<String, dynamic> result =
          await ref.read(apiClientProvider).postJson(Endpoints.notificationTest);
      ref.invalidate(notificationsProvider);
      if (!context.mounted) return;
      // On rapporte ce que le Bridge a reellement fait : enregistrer la
      // notification n'implique pas que le push soit parti.
      final bool pushed = result['pushed'] == true;
      showToast(
        context,
        pushed
            ? 'Notification d’essai envoyée sur ce téléphone.'
            : 'Notification enregistrée, mais le push n’a pas été envoyé : '
                'vérifiez l’état des notifications push.',
        error: !pushed,
      );
    } on ApiException catch (error) {
      if (!context.mounted) return;
      showToast(context, error.message, error: true);
    }
  }

  Future<void> _openPushStatus(BuildContext context, WidgetRef ref) async {
    try {
      final Map<String, dynamic> status =
          await ref.read(apiClientProvider).getJson(Endpoints.notificationPushStatus);
      if (!context.mounted) return;
      await showDialog<void>(
        context: context,
        builder: (BuildContext context) => AlertDialog(
          title: const Text('Notifications push'),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            children: <Widget>[
              DetailRow(
                label: 'Service configuré',
                value: status['configured'] == true ? 'Oui' : 'Non',
              ),
              DetailRow(
                label: 'Appareils enregistrés',
                value: '${status['devices'] ?? 0}',
              ),
              if (status['detail'] != null)
                Padding(
                  padding: const EdgeInsets.only(top: AppSpacing.md),
                  child: Text('${status['detail']}'),
                ),
            ],
          ),
          actions: <Widget>[
            TextButton(onPressed: () => Navigator.of(context).pop(), child: const Text('Fermer')),
          ],
        ),
      );
    } on ApiException catch (error) {
      if (!context.mounted) return;
      showToast(context, error.message, error: true);
    }
  }
}

class _NotificationFilters extends ConsumerWidget {
  const _NotificationFilters();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final NotificationFilter filter = ref.watch(notificationFilterProvider);
    final AsyncValue<Map<String, dynamic>> inbox = ref.watch(notificationsProvider);
    final List<String> categories = <String>[
      ...?(inbox.valueOrNull?['categories'] as List<dynamic>?)?.map((dynamic e) => '$e'),
    ];

    return Padding(
      padding: const EdgeInsets.fromLTRB(AppSpacing.lg, AppSpacing.md, AppSpacing.lg, AppSpacing.md),
      child: Row(
        children: <Widget>[
          Expanded(
            child: InputDecorator(
              decoration: const InputDecoration(
                labelText: 'Catégorie',
                isDense: true,
                contentPadding: EdgeInsets.symmetric(horizontal: AppSpacing.md, vertical: 10),
              ),
              child: DropdownButtonHideUnderline(
                child: DropdownButton<String?>(
                  value: filter.category,
                  isExpanded: true,
                  isDense: true,
                  style: Theme.of(context).textTheme.bodyMedium,
                  items: <DropdownMenuItem<String?>>[
                    const DropdownMenuItem<String?>(value: null, child: Text('Toutes')),
                    for (final String category in categories)
                      DropdownMenuItem<String?>(
                        value: category,
                        child: Text(
                          labelFor(kCategoryLabels, category),
                          overflow: TextOverflow.ellipsis,
                        ),
                      ),
                  ],
                  onChanged: (String? value) => ref
                      .read(notificationFilterProvider.notifier)
                      .state = filter.withCategory(value),
                ),
              ),
            ),
          ),
          const SizedBox(width: AppSpacing.md),
          FilterChip(
            label: const Text('Non lues'),
            selected: filter.unreadOnly,
            onSelected: (bool value) => ref
                .read(notificationFilterProvider.notifier)
                .state = filter.withUnreadOnly(value),
          ),
        ],
      ),
    );
  }
}

class _NotificationList extends ConsumerWidget {
  const _NotificationList({required this.payload});

  final Map<String, dynamic> payload;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final List<Map<String, dynamic>> items = <Map<String, dynamic>>[
      ...?(payload['items'] as List<dynamic>?)?.map(
        (dynamic e) => Map<String, dynamic>.from(e as Map),
      ),
    ];

    if (items.isEmpty) {
      return const EmptyState(
        title: 'Aucune notification',
        message: 'Les opportunités détectées, les actualités à fort impact, les événements '
            'économiques et les alertes de risque apparaîtront ici.',
        icon: Icons.notifications_none_outlined,
      );
    }

    return RefreshIndicator(
      onRefresh: () async {
        ref
          ..invalidate(notificationsProvider)
          ..invalidate(unreadCountProvider);
      },
      child: ListView.separated(
        padding: AppSpacing.page,
        itemCount: items.length,
        separatorBuilder: (BuildContext context, int index) => const SizedBox(height: AppSpacing.sm),
        itemBuilder: (BuildContext context, int index) => _NotificationTile(event: items[index]),
      ),
    );
  }
}

class _NotificationTile extends ConsumerWidget {
  const _NotificationTile({required this.event});

  final Map<String, dynamic> event;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final ThemeData theme = Theme.of(context);
    final bool unread = event['readAt'] == null;
    final String category = '${event['category'] ?? ''}';
    final String priority = '${event['priority'] ?? ''}';

    return AppCard(
      accent: unread,
      onTap: () => _open(context, ref),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Row(
            children: <Widget>[
              Icon(categoryIcon(category), size: 18, color: theme.colorScheme.primary),
              const SizedBox(width: AppSpacing.sm),
              Expanded(
                child: Text(
                  '${event['title'] ?? ''}',
                  style: theme.textTheme.titleSmall?.copyWith(
                    fontWeight: unread ? FontWeight.w700 : FontWeight.w500,
                  ),
                ),
              ),
              if (unread)
                Container(
                  width: 8,
                  height: 8,
                  decoration: BoxDecoration(
                    color: theme.colorScheme.primary,
                    shape: BoxShape.circle,
                  ),
                ),
            ],
          ),
          const SizedBox(height: AppSpacing.sm),
          Text(
            '${event['body'] ?? ''}',
            maxLines: 4,
            overflow: TextOverflow.ellipsis,
            style: theme.textTheme.bodySmall,
          ),
          const SizedBox(height: AppSpacing.sm),
          Wrap(
            spacing: AppSpacing.sm,
            runSpacing: AppSpacing.xs,
            crossAxisAlignment: WrapCrossAlignment.center,
            children: <Widget>[
              StatusChip(
                label: labelFor(kCategoryLabels, category),
                dense: true,
              ),
              StatusChip(
                label: labelFor(kPriorityLabels, priority),
                tone: priorityTone(priority),
                dense: true,
              ),
              if (event['symbol'] != null)
                StatusChip(label: '${event['symbol']}', tone: StatusTone.accent, dense: true),
              Text(relativeMoment('${event['createdAt']}'), style: theme.textTheme.labelSmall),
              if (event['pushed'] != true)
                Text('non poussée', style: theme.textTheme.labelSmall),
            ],
          ),
        ],
      ),
    );
  }

  /// Ouvre l'ecran concerne et marque la notification comme lue.
  ///
  /// Aucune action financiere n'est declenchee depuis une notification
  /// (CDC2 section 94) : on se contente de naviguer vers l'analyse.
  Future<void> _open(BuildContext context, WidgetRef ref) async {
    final Object? id = event['id'];
    if (id is int && event['readAt'] == null) {
      try {
        await ref.read(apiClientProvider).postJson(Endpoints.notificationRead(id));
        ref
          ..invalidate(notificationsProvider)
          ..invalidate(unreadCountProvider);
      } on ApiException {
        // Marquer comme lu est secondaire : on n'interrompt pas la navigation.
      }
    }

    if (!context.mounted) return;
    final Map<String, dynamic> data = Map<String, dynamic>.from(
      (event['data'] as Map<dynamic, dynamic>?) ?? const <dynamic, dynamic>{},
    );
    final String route = '${data['route'] ?? ''}';
    final Object? newsId = data['newsId'] ?? event['newsId'];

    switch (route) {
      case 'news':
        if (newsId is int) context.push(Routes.newsDetail(newsId));
      case 'opportunity':
        context.push(Routes.opportunities);
      case 'calendar':
        context.push(Routes.economicCalendar);
      case 'diagnostic':
        context.push(Routes.diagnostics);
      default:
        if (event['symbol'] != null) {
          context.push(Routes.marketDetail('${event['symbol']}'));
        }
    }
  }
}
