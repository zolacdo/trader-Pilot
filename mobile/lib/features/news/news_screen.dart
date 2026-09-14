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

/// Impact minimal retenu dans la liste des actualités.
final StateProvider<String?> newsImpactProvider = StateProvider<String?>((Ref ref) => null);

/// Fenêtre du calendrier économique : today, tomorrow ou week.
final StateProvider<String> calendarRangeProvider = StateProvider<String>((Ref ref) => 'today');

final FutureProvider<Map<String, dynamic>> newsProvider =
    FutureProvider<Map<String, dynamic>>((Ref ref) {
  final String? impact = ref.watch(newsImpactProvider);
  return ref.watch(apiClientProvider).getJson(
        Endpoints.news,
        query: <String, dynamic>{'limit': 80, if (impact != null) 'impact': impact},
      );
});

final FutureProvider<Map<String, dynamic>> economicCalendarProvider =
    FutureProvider<Map<String, dynamic>>((Ref ref) {
  final String range = ref.watch(calendarRangeProvider);
  return ref
      .watch(apiClientProvider)
      .getJson(Endpoints.economicCalendar, query: <String, dynamic>{'range': range});
});

/// Centre d'actualités : dépêches qualifiées et calendrier économique.
///
/// Les actualités proviennent de flux publics (banques centrales, instituts
/// statistiques, régulateurs, presse financière en accès libre). TradePilot ne
/// contourne aucun paywall, CAPTCHA ni authentification.
class NewsScreen extends ConsumerWidget {
  const NewsScreen({super.key, this.initialTab = 0});

  /// Onglet ouvert à l'arrivée : 0 pour les dépêches, 1 pour le calendrier.
  ///
  /// Une notification d'événement économique renvoyait jusqu'ici vers les
  /// dépêches : on lisait « publication imminente » et on tombait sur des
  /// titres de presse.
  final int initialTab;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return DefaultTabController(
      length: 2,
      initialIndex: initialTab.clamp(0, 1),
      child: Scaffold(
        appBar: AppBar(
          title: const Text('Actualités'),
          actions: <Widget>[
            IconButton(
              tooltip: 'Collecter maintenant',
              onPressed: () => _refreshNow(context, ref),
              icon: const Icon(Icons.cloud_download_outlined),
            ),
            IconButton(
              tooltip: 'Sources',
              onPressed: () => _showSources(context, ref),
              icon: const Icon(Icons.rss_feed_outlined),
            ),
          ],
          bottom: const TabBar(
            tabs: <Widget>[
              Tab(text: 'Dépêches'),
              Tab(text: 'Calendrier'),
            ],
          ),
        ),
        body: const TabBarView(
          children: <Widget>[_NewsTab(), _CalendarTab()],
        ),
      ),
    );
  }

  Future<void> _refreshNow(BuildContext context, WidgetRef ref) async {
    showToast(context, 'Collecte en cours…');
    try {
      final Map<String, dynamic> report =
          await ref.read(apiClientProvider).postJson(Endpoints.newsRefresh);
      ref
        ..invalidate(newsProvider)
        ..invalidate(economicCalendarProvider);
      if (!context.mounted) return;
      final Object? created = report['created'];
      final Object? fetched = report['fetched'];
      showToast(
        context,
        '$fetched dépêche(s) lue(s), $created nouvelle(s) retenue(s).',
      );
    } on ApiException catch (error) {
      if (!context.mounted) return;
      showToast(context, error.message, error: true);
    }
  }

  Future<void> _showSources(BuildContext context, WidgetRef ref) async {
    try {
      final Map<String, dynamic> payload =
          await ref.read(apiClientProvider).getJson(Endpoints.newsSources);
      if (!context.mounted) return;
      final List<Map<String, dynamic>> sources = <Map<String, dynamic>>[
        ...?(payload['sources'] as List<dynamic>?)
            ?.map((dynamic e) => Map<String, dynamic>.from(e as Map)),
      ];
      await showModalBottomSheet<void>(
        context: context,
        isScrollControlled: true,
        builder: (BuildContext context) => SafeArea(
          child: ListView(
            shrinkWrap: true,
            padding: AppSpacing.page,
            children: <Widget>[
              SectionHeader(
                title: 'Sources d’actualités',
                subtitle: '${sources.length} flux configurés',
              ),
              for (final Map<String, dynamic> source in sources)
                ListTile(
                  dense: true,
                  leading: Icon(
                    source['official'] == true ? Icons.verified_outlined : Icons.article_outlined,
                    size: 20,
                  ),
                  title: Text('${source['name']}'),
                  subtitle: Text('${source['url']}', maxLines: 1, overflow: TextOverflow.ellipsis),
                  trailing: source['enabled'] == true
                      ? const StatusChip(label: 'Actif', tone: StatusTone.good, dense: true)
                      : const StatusChip(label: 'Inactif', dense: true),
                ),
              if (payload['note'] != null)
                Padding(
                  padding: const EdgeInsets.only(top: AppSpacing.md),
                  child: Text(
                    '${payload['note']}',
                    style: Theme.of(context).textTheme.bodySmall,
                  ),
                ),
            ],
          ),
        ),
      );
    } on ApiException catch (error) {
      if (!context.mounted) return;
      showToast(context, error.message, error: true);
    }
  }
}

class _NewsTab extends ConsumerWidget {
  const _NewsTab();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final AsyncValue<Map<String, dynamic>> news = ref.watch(newsProvider);
    final String? impact = ref.watch(newsImpactProvider);

    return Column(
      children: <Widget>[
        Padding(
          padding: const EdgeInsets.fromLTRB(
            AppSpacing.lg,
            AppSpacing.md,
            AppSpacing.lg,
            AppSpacing.sm,
          ),
          child: Wrap(
            spacing: AppSpacing.sm,
            children: <Widget>[
              ChoiceChip(
                label: const Text('Tous'),
                selected: impact == null,
                onSelected: (_) => ref.read(newsImpactProvider.notifier).state = null,
              ),
              for (final String level in <String>['MEDIUM', 'HIGH', 'CRITICAL'])
                ChoiceChip(
                  label: Text(labelFor(kImpactLabels, level)),
                  selected: impact == level,
                  onSelected: (_) => ref.read(newsImpactProvider.notifier).state = level,
                ),
            ],
          ),
        ),
        Expanded(
          child: news.when(
            loading: () => const LoadingView(label: 'Chargement des actualités…'),
            error: (Object error, StackTrace stack) => ErrorView(
              message: error is ApiException ? error.message : 'Actualités indisponibles.',
              technical: error is ApiException ? error.technical : error.toString(),
              onRetry: () => ref.invalidate(newsProvider),
            ),
            data: (Map<String, dynamic> payload) {
              final List<Map<String, dynamic>> items = <Map<String, dynamic>>[
                ...?(payload['items'] as List<dynamic>?)
                    ?.map((dynamic e) => Map<String, dynamic>.from(e as Map)),
              ];
              if (items.isEmpty) {
                return const EmptyState(
                  title: 'Aucune actualité',
                  message: 'Lancez une collecte depuis l’icône de téléchargement, ou attendez '
                      'le prochain passage automatique.',
                  icon: Icons.public_off_outlined,
                );
              }
              return RefreshIndicator(
                onRefresh: () async => ref.invalidate(newsProvider),
                child: ListView.separated(
                  padding: AppSpacing.page,
                  itemCount: items.length,
                  separatorBuilder: (BuildContext context, int index) =>
                      const SizedBox(height: AppSpacing.sm),
                  itemBuilder: (BuildContext context, int index) =>
                      _NewsTile(item: items[index]),
                ),
              );
            },
          ),
        ),
      ],
    );
  }
}

class _NewsTile extends StatelessWidget {
  const _NewsTile({required this.item});

  final Map<String, dynamic> item;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    final String impact = '${item['impactLevel'] ?? ''}';
    final List<String> assets = <String>[
      ...?(item['affectedAssets'] as List<dynamic>?)?.map((dynamic e) => '$e'),
    ];

    return AppCard(
      onTap: () {
        final Object? id = item['id'];
        if (id is int) context.push(Routes.newsDetail(id));
      },
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Text('${item['title'] ?? ''}', style: theme.textTheme.titleSmall),
          const SizedBox(height: AppSpacing.xs),
          Text(
            '${item['source'] ?? ''} · ${relativeMoment('${item['publishedAt'] ?? item['receivedAt']}')}',
            style: theme.textTheme.labelSmall,
          ),
          if (item['summary'] != null) ...<Widget>[
            const SizedBox(height: AppSpacing.sm),
            Text(
              '${item['summary']}',
              maxLines: 3,
              overflow: TextOverflow.ellipsis,
              style: theme.textTheme.bodySmall,
            ),
          ],
          const SizedBox(height: AppSpacing.sm),
          Wrap(
            spacing: AppSpacing.sm,
            runSpacing: AppSpacing.xs,
            children: <Widget>[
              StatusChip(
                label: 'Impact ${labelFor(kImpactLabels, impact).toLowerCase()}',
                tone: impactTone(impact),
                dense: true,
              ),
              StatusChip(
                label: labelFor(kSentimentLabels, '${item['sentiment']}'),
                tone: sentimentTone('${item['sentiment']}'),
                dense: true,
              ),
              if (item['confirmations'] is num && (item['confirmations'] as num) > 1)
                StatusChip(label: '${item['confirmations']} sources', dense: true),
              for (final String asset in assets.take(3))
                StatusChip(label: asset, tone: StatusTone.accent, dense: true),
            ],
          ),
        ],
      ),
    );
  }
}

class _CalendarTab extends ConsumerWidget {
  const _CalendarTab();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final AsyncValue<Map<String, dynamic>> calendar = ref.watch(economicCalendarProvider);
    final String range = ref.watch(calendarRangeProvider);

    return Column(
      children: <Widget>[
        Padding(
          padding: const EdgeInsets.fromLTRB(
            AppSpacing.lg,
            AppSpacing.md,
            AppSpacing.lg,
            AppSpacing.sm,
          ),
          child: SegmentedButton<String>(
            segments: const <ButtonSegment<String>>[
              ButtonSegment<String>(value: 'today', label: Text('Aujourd’hui')),
              ButtonSegment<String>(value: 'tomorrow', label: Text('Demain')),
              ButtonSegment<String>(value: 'week', label: Text('Semaine')),
            ],
            selected: <String>{range},
            onSelectionChanged: (Set<String> value) =>
                ref.read(calendarRangeProvider.notifier).state = value.first,
          ),
        ),
        Expanded(
          child: calendar.when(
            loading: () => const LoadingView(label: 'Chargement du calendrier…'),
            error: (Object error, StackTrace stack) => ErrorView(
              message: error is ApiException ? error.message : 'Calendrier indisponible.',
              technical: error is ApiException ? error.technical : error.toString(),
              onRetry: () => ref.invalidate(economicCalendarProvider),
            ),
            data: (Map<String, dynamic> payload) {
              // Aucune source configuree n'est un etat legitime : mieux vaut le
              // dire que d'afficher un calendrier vide qui ressemble a une panne.
              if (payload['configured'] != true) {
                return EmptyState(
                  title: 'Aucune source de calendrier',
                  message: '${payload['detail'] ?? 'Configurez une source pour voir les publications à venir.'}',
                  icon: Icons.event_busy_outlined,
                );
              }
              final List<Map<String, dynamic>> items = <Map<String, dynamic>>[
                ...?(payload['items'] as List<dynamic>?)
                    ?.map((dynamic e) => Map<String, dynamic>.from(e as Map)),
              ];
              if (items.isEmpty) {
                return const EmptyState(
                  title: 'Aucune publication',
                  message: 'Rien n’est prévu sur cette période.',
                  icon: Icons.event_available_outlined,
                );
              }
              return RefreshIndicator(
                onRefresh: () async => ref.invalidate(economicCalendarProvider),
                child: ListView.separated(
                  padding: AppSpacing.page,
                  itemCount: items.length,
                  separatorBuilder: (BuildContext context, int index) =>
                      const SizedBox(height: AppSpacing.sm),
                  itemBuilder: (BuildContext context, int index) =>
                      _EventTile(event: items[index]),
                ),
              );
            },
          ),
        ),
      ],
    );
  }
}

class _EventTile extends StatelessWidget {
  const _EventTile({required this.event});

  final Map<String, dynamic> event;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    final String impact = '${event['impact'] ?? ''}';

    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Row(
            children: <Widget>[
              Expanded(child: Text('${event['title'] ?? ''}', style: theme.textTheme.titleSmall)),
              const SizedBox(width: AppSpacing.sm),
              StatusChip(
                label: labelFor(kImpactLabels, impact),
                tone: impactTone(impact),
                dense: true,
              ),
            ],
          ),
          const SizedBox(height: AppSpacing.xs),
          Text(
            '${shortMoment('${event['scheduledAt']}')} · ${relativeMoment('${event['scheduledAt']}')}'
            '${event['currency'] != null ? ' · ${event['currency']}' : ''}',
            style: theme.textTheme.labelSmall,
          ),
          // On n'affiche que les chiffres réellement fournis. Le calendrier
          // hebdomadaire de Forex Factory ne porte aucune valeur publiée : la
          // colonne « Publié » restait donc vide sur chaque carte, et
          // « Prévision » l'est aussi pour les événements sans consensus.
          // Trois tirets alignés ne renseignent sur rien et font croire à une
          // panne ; l'absence de colonne, elle, se comprend.
          ...buildEventMetrics(event),
        ],
      ),
    );
  }
}

/// Colonnes de chiffres d'un événement, limitées à ce qui est renseigné.
///
/// Renvoie une liste vide quand la source ne fournit aucun chiffre : la carte
/// se termine alors sur l'heure et la devise, sans rangée creuse.
List<Widget> buildEventMetrics(Map<String, dynamic> event) {
  const Map<String, String> colonnes = <String, String>{
    'forecast': 'Prévision',
    'previous': 'Précédent',
    'actual': 'Publié',
  };

  final List<Widget> tuiles = <Widget>[];
  colonnes.forEach((String cle, String libelle) {
    final String valeur = '${event[cle] ?? ''}'.trim();
    if (valeur.isEmpty) return;
    tuiles.add(
      Expanded(child: MetricTile(label: libelle, value: valeur, compact: true)),
    );
  });

  if (tuiles.isEmpty) return const <Widget>[];
  return <Widget>[
    const SizedBox(height: AppSpacing.sm),
    Row(children: tuiles),
  ];
}
