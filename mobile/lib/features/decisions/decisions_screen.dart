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

/// N'afficher que les décisions n'ayant PAS débouché sur un trade.
final StateProvider<bool> notTakenOnlyProvider = StateProvider<bool>((Ref ref) => false);

final FutureProvider<Map<String, dynamic>> decisionsProvider =
    FutureProvider<Map<String, dynamic>>((Ref ref) {
  final bool notTaken = ref.watch(notTakenOnlyProvider);
  return ref.watch(apiClientProvider).getJson(
        Endpoints.decisions,
        query: <String, dynamic>{'limit': 80, if (notTaken) 'notTaken': true},
      );
});

final FutureProvider<Map<String, dynamic>> shadowPerformanceProvider =
    FutureProvider<Map<String, dynamic>>((Ref ref) {
  return ref.watch(apiClientProvider).getJson(Endpoints.shadowPerformance);
});

/// Journal de décisions : pourquoi le système a agi, et surtout pourquoi non.
class DecisionsScreen extends ConsumerWidget {
  const DecisionsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return DefaultTabController(
      length: 2,
      child: Scaffold(
        appBar: AppBar(
          title: const Text('Décisions'),
          bottom: const TabBar(
            tabs: <Widget>[
              Tab(text: 'Journal'),
              Tab(text: 'Mode observation'),
            ],
          ),
        ),
        body: const TabBarView(children: <Widget>[_JournalTab(), _ShadowTab()]),
      ),
    );
  }
}

class _JournalTab extends ConsumerWidget {
  const _JournalTab();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final AsyncValue<Map<String, dynamic>> decisions = ref.watch(decisionsProvider);
    final bool notTaken = ref.watch(notTakenOnlyProvider);

    return Column(
      children: <Widget>[
        Padding(
          padding: const EdgeInsets.fromLTRB(
            AppSpacing.lg,
            AppSpacing.md,
            AppSpacing.lg,
            AppSpacing.sm,
          ),
          child: Row(
            children: <Widget>[
              FilterChip(
                label: const Text('Trades non pris'),
                selected: notTaken,
                onSelected: (bool value) =>
                    ref.read(notTakenOnlyProvider.notifier).state = value,
              ),
            ],
          ),
        ),
        Expanded(
          child: decisions.when(
            loading: () => const LoadingView(label: 'Chargement du journal…'),
            error: (Object error, StackTrace stack) => ErrorView(
              message: error is ApiException ? error.message : 'Journal indisponible.',
              technical: error is ApiException ? error.technical : error.toString(),
              onRetry: () => ref.invalidate(decisionsProvider),
            ),
            data: (Map<String, dynamic> payload) {
              final List<Map<String, dynamic>> items = <Map<String, dynamic>>[
                ...?(payload['items'] as List<dynamic>?)
                    ?.map((dynamic e) => Map<String, dynamic>.from(e as Map)),
              ];
              if (items.isEmpty) {
                return const EmptyState(
                  title: 'Aucune décision enregistrée',
                  message: 'Chaque analyse aboutie laisse ici une trace chiffrée : l’action '
                      'retenue, le score et les facteurs qui l’ont portée ou freinée.',
                  icon: Icons.rule_outlined,
                );
              }
              return RefreshIndicator(
                onRefresh: () async => ref.invalidate(decisionsProvider),
                child: ListView.separated(
                  padding: AppSpacing.page,
                  itemCount: items.length,
                  separatorBuilder: (BuildContext context, int index) =>
                      const SizedBox(height: AppSpacing.sm),
                  itemBuilder: (BuildContext context, int index) =>
                      _DecisionTile(decision: items[index]),
                ),
              );
            },
          ),
        ),
      ],
    );
  }
}

class _DecisionTile extends StatelessWidget {
  const _DecisionTile({required this.decision});

  final Map<String, dynamic> decision;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    final String action = '${decision['action'] ?? ''}';

    return AppCard(
      onTap: () {
        final Object? id = decision['id'];
        if (id is int) context.push(Routes.decisionDetail(id));
      },
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: <Widget>[
              // Un Wrap plutot qu'une Row : « Ne pas trader » a cote d'un
              // symbole long deborde sur un ecran de 360 points.
              Expanded(
                child: Wrap(
                  spacing: AppSpacing.sm,
                  runSpacing: AppSpacing.xs,
                  crossAxisAlignment: WrapCrossAlignment.center,
                  children: <Widget>[
                    Text('${decision['symbol'] ?? ''}', style: theme.textTheme.titleSmall),
                    StatusChip(
                      label: labelFor(kActionLabels, action),
                      tone: actionTone(action),
                      dense: true,
                    ),
                  ],
                ),
              ),
              const SizedBox(width: AppSpacing.sm),
              Text(
                '${number(decision['globalScore'], digits: 0)}/100',
                style: theme.textTheme.titleSmall,
              ),
            ],
          ),
          const SizedBox(height: AppSpacing.xs),
          Text(
            '${labelFor(kSourceLabels, '${decision['source']}')} · '
            '${relativeMoment('${decision['createdAt']}')}',
            style: theme.textTheme.labelSmall,
          ),
          if (decision['reason'] != null) ...<Widget>[
            const SizedBox(height: AppSpacing.sm),
            Text(
              '${decision['reason']}',
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
              if (decision['regime'] != null)
                StatusChip(
                  label: labelFor(kRegimeLabels, '${decision['regime']}'),
                  dense: true,
                ),
              if (decision['shadow'] == true)
                const StatusChip(label: 'Observation', dense: true),
              if (decision['executed'] == true)
                const StatusChip(label: 'Exécutée', tone: StatusTone.good, dense: true),
            ],
          ),
        ],
      ),
    );
  }
}

/// Bande marginale : ce que le seuil de confiance écarte, mesuré quand même.
///
/// Elle est distincte du mode observation. Celui-ci enregistre quand *rien* ne
/// part au broker ; celle-ci enregistre pendant que le système trade, ce qui
/// est précisément ce qui la rend comparable — et c'est elle, seule, qui
/// autorise le Bridge à abaisser son exigence d'entrée.
class _MarginalBandCard extends StatelessWidget {
  const _MarginalBandCard({required this.overall});

  final Map<String, dynamic> overall;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    final Object? moyenne = overall['averageR'];
    final String moyenneTexte =
        moyenne is num ? '${moyenne > 0 ? '+' : ''}${moyenne.toStringAsFixed(2)} R' : '--';

    return AppCard(
      accent: true,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          const SectionHeader(
            title: 'Bande écartée par le seuil',
            subtitle: 'Mesurée pendant que le système trade, jamais envoyée.',
          ),
          Row(
            children: <Widget>[
              Expanded(
                child: MetricTile(
                  label: 'Clôturées',
                  value: '${overall['closed'] ?? 0}',
                  caption: '${overall['simulated'] ?? 0} simulée(s)',
                  compact: true,
                ),
              ),
              Expanded(
                child: MetricTile(
                  label: 'Réussite',
                  value: percentFromRatio(overall['winRate'], digits: 1),
                  compact: true,
                ),
              ),
              Expanded(
                child: MetricTile(
                  label: 'R moyen',
                  value: moyenneTexte,
                  valueColor: moyenne is num && moyenne != 0
                      ? (moyenne > 0 ? theme.colorScheme.primary : theme.colorScheme.error)
                      : null,
                  compact: true,
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

/// Résultats du mode observation : ce que le système aurait fait.
class _ShadowTab extends ConsumerWidget {
  const _ShadowTab();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final AsyncValue<Map<String, dynamic>> report = ref.watch(shadowPerformanceProvider);
    final ThemeData theme = Theme.of(context);

    return report.when(
      loading: () => const LoadingView(label: 'Calcul des performances simulées…'),
      error: (Object error, StackTrace stack) => ErrorView(
        message: error is ApiException ? error.message : 'Performances indisponibles.',
        technical: error is ApiException ? error.technical : error.toString(),
        onRetry: () => ref.invalidate(shadowPerformanceProvider),
      ),
      data: (Map<String, dynamic> payload) {
        final Map<String, dynamic> overall = Map<String, dynamic>.from(
          (payload['overall'] as Map<dynamic, dynamic>?) ?? const <dynamic, dynamic>{},
        );
        final Map<String, dynamic> marginal = Map<String, dynamic>.from(
          ((payload['marginalBand'] as Map<dynamic, dynamic>?)?['overall']
                  as Map<dynamic, dynamic>?) ??
              const <dynamic, dynamic>{},
        );
        final Object? simulated = overall['simulated'];
        final Object? marginalSimulated = marginal['simulated'];
        final bool observationVide = simulated is! num || simulated == 0;
        final bool bandeVide = marginalSimulated is! num || marginalSimulated == 0;

        // L'écran ne se déclare vide que si les DEUX mesures le sont. Le mode
        // observation peut très bien n'avoir jamais tourné alors que la bande
        // marginale se remplit : c'est même le cas normal, puisqu'elle
        // s'enregistre pendant que le système trade.
        if (observationVide && bandeVide) {
          return const EmptyState(
            title: 'Aucune simulation clôturée',
            message: 'Le mode observation enregistre ce que le système aurait fait, sans '
                'envoyer d’ordre. Les statistiques apparaîtront dès la première '
                'simulation terminée.',
            icon: Icons.visibility_outlined,
          );
        }

        return RefreshIndicator(
          onRefresh: () async => ref.invalidate(shadowPerformanceProvider),
          child: ListView(
            padding: AppSpacing.page,
            children: <Widget>[
              if (!bandeVide) _MarginalBandCard(overall: marginal),
              AppCard(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: <Widget>[
                    const SectionHeader(title: 'Vue d’ensemble'),
                    Row(
                      children: <Widget>[
                        Expanded(
                          child: MetricTile(
                            label: 'Simulations',
                            value: '$simulated',
                            caption: '${overall['closed'] ?? 0} clôturée(s)',
                            compact: true,
                          ),
                        ),
                        Expanded(
                          child: MetricTile(
                            label: 'Réussite',
                            value: percentFromRatio(overall['winRate'], digits: 1),
                            compact: true,
                          ),
                        ),
                        Expanded(
                          child: MetricTile(
                            label: 'Total R',
                            value: number(overall['totalR']),
                            compact: true,
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: AppSpacing.sm),
                    DetailRow(
                      label: 'Facteur de profit',
                      // Sans la moindre perte, le facteur n'est pas calculable :
                      // on le dit plutot que d'afficher l'infini.
                      value: overall['profitFactor'] == null
                          ? 'non calculable (aucune perte)'
                          : number(overall['profitFactor']),
                    ),
                    DetailRow(
                      label: 'Perte maximale enchaînée',
                      value: number(overall['maxDrawdownR']),
                    ),
                    DetailRow(
                      label: 'Décisions écartées',
                      value: '${overall['skipped'] ?? 0}',
                    ),
                  ],
                ),
              ),
              const SizedBox(height: AppSpacing.md),
              _Breakdown(
                title: 'Par origine',
                entries: payload['bySource'],
                labels: kSourceLabels,
              ),
              const SizedBox(height: AppSpacing.md),
              _Breakdown(
                title: 'Par moteur d’analyse',
                entries: payload['byEngine'],
                labels: const <String, String>{
                  'OPENROUTER': 'OpenRouter',
                  'ENSEMBLE': 'Ensemble',
                  'TELEGRAM': 'Telegram',
                  'UNKNOWN': 'Origine inconnue',
                },
              ),
              const SizedBox(height: AppSpacing.md),
              Text(
                'Aucun ordre n’a été envoyé : ces chiffres mesurent des décisions, '
                'pas des positions réelles.',
                style: theme.textTheme.bodySmall,
              ),
            ],
          ),
        );
      },
    );
  }
}

class _Breakdown extends StatelessWidget {
  const _Breakdown({required this.title, required this.entries, required this.labels});

  final String title;
  final Object? entries;
  final Map<String, String> labels;

  @override
  Widget build(BuildContext context) {
    final Map<String, dynamic> data = Map<String, dynamic>.from(
      (entries as Map<dynamic, dynamic>?) ?? const <dynamic, dynamic>{},
    );
    if (data.isEmpty) return const SizedBox.shrink();

    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          SectionHeader(title: title),
          for (final MapEntry<String, dynamic> entry in data.entries)
            DetailRow(
              label: labelFor(labels, entry.key, fallback: entry.key),
              value: _summarise(entry.value),
            ),
        ],
      ),
    );
  }

  String _summarise(Object? value) {
    if (value is! Map) return '—';
    final Map<String, dynamic> stats = Map<String, dynamic>.from(value);
    final Object? simulated = stats['simulated'];
    if (simulated is! num || simulated == 0) return 'aucune simulation';
    if (stats['closed'] == 0) return '$simulated simul. · aucune clôturée';
    return '$simulated simul. · ${percentFromRatio(stats['winRate'], digits: 0)} · '
        '${number(stats['totalR'])} R';
  }
}
