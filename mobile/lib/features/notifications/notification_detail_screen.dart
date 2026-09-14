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
import 'notifications_screen.dart';

final FutureProviderFamily<Map<String, dynamic>, int> notificationDetailProvider =
    FutureProvider.family<Map<String, dynamic>, int>((Ref ref, int id) async {
  final Map<String, dynamic> payload =
      await ref.watch(apiClientProvider).getJson(Endpoints.notificationDetail(id));
  // L'ouverture vaut lecture : on marque ici plutôt que d'attendre un geste
  // supplémentaire, sinon la pastille « non lue » resterait après lecture.
  if (payload['readAt'] == null) {
    try {
      final Map<String, dynamic> lu =
          await ref.read(apiClientProvider).postJson(Endpoints.notificationRead(id));
      ref
        ..invalidate(notificationsProvider)
        ..invalidate(unreadCountProvider);
      // On reprend la notification telle que le Bridge la renvoie : sans
      // cela l'écran affichait encore « Lue : Non » juste après l'avoir
      // marquée lue.
      final Object? rafraichie = lu['notification'];
      if (rafraichie is Map) {
        return Map<String, dynamic>.from(rafraichie);
      }
    } on ApiException {
      // Marquer comme lu est secondaire : l'affichage ne doit pas en dépendre.
    }
  }
  return payload;
});

/// Détail d'une notification, ouvert depuis l'inbox ou depuis l'alerte Android.
///
/// Cet écran informe. Il ne déclenche aucune action financière : le CDC2
/// section 94 l'interdit depuis une notification.
class NotificationDetailScreen extends ConsumerWidget {
  const NotificationDetailScreen({super.key, required this.notificationId});

  final int notificationId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final AsyncValue<Map<String, dynamic>> detail =
        ref.watch(notificationDetailProvider(notificationId));

    return Scaffold(
      appBar: AppBar(title: const Text('Notification')),
      body: detail.when(
        loading: () => const LoadingView(label: 'Chargement…'),
        error: (Object error, StackTrace stack) => ErrorView(
          message: error is ApiException ? error.message : 'Notification introuvable.',
          technical: error is ApiException ? error.technical : error.toString(),
          onRetry: () => ref.invalidate(notificationDetailProvider(notificationId)),
        ),
        data: (Map<String, dynamic> event) => _Body(event: event),
      ),
    );
  }
}

class _Body extends StatelessWidget {
  const _Body({required this.event});

  final Map<String, dynamic> event;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    final String category = '${event['category'] ?? ''}';
    final String priority = '${event['priority'] ?? ''}';
    final Map<String, dynamic> data = Map<String, dynamic>.from(
      (event['data'] as Map<dynamic, dynamic>?) ?? const <dynamic, dynamic>{},
    );

    return ListView(
      padding: AppSpacing.page,
      children: <Widget>[
        AppCard(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: <Widget>[
              Row(
                children: <Widget>[
                  Icon(categoryIcon(category), size: 20, color: theme.colorScheme.primary),
                  const SizedBox(width: AppSpacing.sm),
                  Expanded(
                    child: Text('${event['title'] ?? ''}', style: theme.textTheme.titleMedium),
                  ),
                ],
              ),
              const SizedBox(height: AppSpacing.sm),
              Text(
                '${shortMoment('${event['createdAt']}')} · ${relativeMoment('${event['createdAt']}')}',
                style: theme.textTheme.labelSmall,
              ),
              const SizedBox(height: AppSpacing.md),
              // Le corps contient des retours à la ligne mis en forme par le
              // Bridge : on les respecte tels quels.
              SelectableText('${event['body'] ?? ''}', style: theme.textTheme.bodyMedium),
              const SizedBox(height: AppSpacing.md),
              Wrap(
                spacing: AppSpacing.sm,
                runSpacing: AppSpacing.xs,
                children: <Widget>[
                  StatusChip(label: labelFor(kCategoryLabels, category), dense: true),
                  StatusChip(
                    label: labelFor(kPriorityLabels, priority),
                    tone: priorityTone(priority),
                    dense: true,
                  ),
                  if (event['symbol'] != null)
                    StatusChip(
                      label: '${event['symbol']}',
                      tone: StatusTone.accent,
                      dense: true,
                    ),
                ],
              ),
            ],
          ),
        ),
        const SizedBox(height: AppSpacing.md),
        AppCard(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: <Widget>[
              const SectionHeader(title: 'Acheminement'),
              DetailRow(
                label: 'Notification poussée',
                value: event['pushed'] == true ? 'Oui' : 'Non',
              ),
              if (event['pushError'] != null)
                DetailRow(label: 'Raison', value: _pushReason('${event['pushError']}')),
              DetailRow(
                label: 'Lue',
                value: event['readAt'] == null ? 'Non' : shortMoment('${event['readAt']}'),
              ),
            ],
          ),
        ),
        const SizedBox(height: AppSpacing.md),
        ..._actions(context, data, event),
      ],
    );
  }

  /// Traduit le code technique du transport en phrase utile.
  String _pushReason(String code) {
    return switch (code) {
      'PUSH_TRANSPORT_UNAVAILABLE' =>
        'Firebase n’est pas configuré : l’alerte est arrivée par le canal direct.',
      'NO_DEVICE_TOKEN' => 'Aucun appareil n’a enregistré de jeton push.',
      _ => code,
    };
  }

  /// Raccourcis vers l'écran qui porte le contexte complet.
  List<Widget> _actions(
    BuildContext context,
    Map<String, dynamic> data,
    Map<String, dynamic> event,
  ) {
    final String route = '${data['route'] ?? ''}';
    final Object? newsId = data['newsId'] ?? event['newsId'];
    final Object? decisionId = event['decisionId'];
    final List<Widget> boutons = <Widget>[];

    void ajouter(IconData icone, String texte, VoidCallback action) {
      boutons.add(
        OutlinedButton.icon(onPressed: action, icon: Icon(icone), label: Text(texte)),
      );
      boutons.add(const SizedBox(height: AppSpacing.sm));
    }

    if (route == 'news' && newsId is int) {
      ajouter(Icons.public_outlined, 'Ouvrir l’actualité', () => context.push(Routes.newsDetail(newsId)));
    }
    if (route == 'opportunity') {
      ajouter(Icons.auto_awesome_outlined, 'Voir les opportunités', () => context.push(Routes.opportunities));
    }
    if (route == 'calendar') {
      ajouter(Icons.event_outlined, 'Ouvrir le calendrier', () => context.push(Routes.economicCalendar));
    }
    if (decisionId is int) {
      ajouter(Icons.rule_outlined, 'Voir la décision', () => context.push(Routes.decisionDetail(decisionId)));
    }
    if (event['symbol'] != null) {
      ajouter(
        Icons.show_chart_outlined,
        'Analyser ${event['symbol']}',
        () => context.push(Routes.marketDetail('${event['symbol']}')),
      );
    }
    return boutons;
  }
}
