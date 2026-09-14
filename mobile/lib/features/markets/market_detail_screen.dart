import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api/api_exception.dart';
import '../../core/api/endpoints.dart';
import '../../core/connection/connection_controller.dart';
import '../../core/theme/app_theme.dart';
import '../../core/widgets/app_widgets.dart';
import '../intelligence/labels.dart';

final FutureProviderFamily<Map<String, dynamic>, String> marketDetailProvider =
    FutureProvider.family<Map<String, dynamic>, String>((Ref ref, String symbol) {
  return ref.watch(apiClientProvider).getJson(Endpoints.marketDetail(symbol));
});

/// Fiche complète d'un instrument : prix, régime, structure multi-timeframes.
class MarketDetailScreen extends ConsumerWidget {
  const MarketDetailScreen({super.key, required this.symbol});

  final String symbol;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final AsyncValue<Map<String, dynamic>> detail = ref.watch(marketDetailProvider(symbol));

    return Scaffold(
      appBar: AppBar(
        title: Text(symbol),
        actions: <Widget>[
          IconButton(
            tooltip: 'Réanalyser',
            onPressed: () => ref.invalidate(marketDetailProvider(symbol)),
            icon: const Icon(Icons.refresh),
          ),
        ],
      ),
      body: detail.when(
        loading: () => const LoadingView(label: 'Analyse en cours…'),
        error: (Object error, StackTrace stack) => ErrorView(
          message: error is ApiException ? error.message : 'Instrument indisponible.',
          technical: error is ApiException ? error.technical : error.toString(),
          onRetry: () => ref.invalidate(marketDetailProvider(symbol)),
        ),
        data: (Map<String, dynamic> payload) => _Body(payload: payload),
      ),
    );
  }
}

class _Body extends StatelessWidget {
  const _Body({required this.payload});

  final Map<String, dynamic> payload;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    final Map<String, dynamic> scan = Map<String, dynamic>.from(
      (payload['scan'] as Map<dynamic, dynamic>?) ?? const <dynamic, dynamic>{},
    );
    final Map<String, dynamic> marketState = Map<String, dynamic>.from(
      (payload['marketState'] as Map<dynamic, dynamic>?) ?? const <dynamic, dynamic>{},
    );
    final Map<String, dynamic> trends = Map<String, dynamic>.from(
      (scan['trends'] as Map<dynamic, dynamic>?) ?? const <dynamic, dynamic>{},
    );
    final List<String> reasons = <String>[
      ...?(scan['reasons'] as List<dynamic>?)?.map((dynamic e) => '$e'),
    ];
    final List<String> anomalies = <String>[
      ...?(scan['anomalies'] as List<dynamic>?)?.map((dynamic e) => '$e'),
    ];

    // Une erreur de scan est dite, pas masquée : sans elle, l'écran afficherait
    // des tirets sans expliquer pourquoi.
    if (scan['error'] != null) {
      return EmptyState(
        title: 'Analyse impossible',
        message: '${scan['error']}',
        icon: Icons.error_outline,
      );
    }

    return ListView(
      padding: AppSpacing.page,
      children: <Widget>[
        AppCard(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: <Widget>[
              Row(
                children: <Widget>[
                  Expanded(
                    child: MetricTile(
                      label: 'Prix',
                      value: number(scan['price'], digits: 5),
                      caption: 'spread ${scan['spreadPoints'] ?? '—'} pts',
                    ),
                  ),
                  StatusChip(
                    label: marketState['state'] == 'OPEN' ? 'Marché ouvert' : 'Marché fermé',
                    tone: marketState['state'] == 'OPEN' ? StatusTone.good : StatusTone.neutral,
                    dense: true,
                  ),
                ],
              ),
              const SizedBox(height: AppSpacing.md),
              Row(
                children: <Widget>[
                  Expanded(
                    child: MetricTile(
                      label: 'Achat',
                      value: number(scan['bid'], digits: 5),
                      compact: true,
                    ),
                  ),
                  Expanded(
                    child: MetricTile(
                      label: 'Vente',
                      value: number(scan['ask'], digits: 5),
                      compact: true,
                    ),
                  ),
                  Expanded(
                    child: MetricTile(
                      label: 'ATR',
                      value: number(scan['atr'], digits: 5),
                      compact: true,
                    ),
                  ),
                ],
              ),
              const SizedBox(height: AppSpacing.xs),
              Text(
                'Analysé ${relativeMoment('${scan['scannedAt']}')}',
                style: theme.textTheme.labelSmall,
              ),
            ],
          ),
        ),
        const SizedBox(height: AppSpacing.md),
        AppCard(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: <Widget>[
              const SectionHeader(title: 'Lecture du marché'),
              DetailRow(
                label: 'Régime',
                value: labelFor(kRegimeLabels, '${scan['regime']}'),
              ),
              if (scan['regimeDetail'] != null && '${scan['regimeDetail']}'.isNotEmpty)
                DetailRow(label: 'Pourquoi', value: '${scan['regimeDetail']}'),
              DetailRow(label: 'Structure', value: '${scan['structure'] ?? '—'}'),
              DetailRow(
                label: 'Alignement des unités de temps',
                value: percentFromRatio(scan['alignment']),
              ),
              DetailRow(label: 'Déclencheur', value: '${scan['trigger'] ?? 'aucun'}'),
              DetailRow(
                label: 'Potentiel de setup',
                value: percentFromRatio(scan['setupPotential']),
              ),
              DetailRow(
                label: 'Direction envisagée',
                value: scan['setupDirection'] == null
                    ? 'aucune'
                    : labelFor(kActionLabels, '${scan['setupDirection']}'),
              ),
              DetailRow(label: 'R/R estimé', value: number(scan['riskReward'])),
              const SizedBox(height: AppSpacing.sm),
              Wrap(
                spacing: AppSpacing.sm,
                runSpacing: AppSpacing.xs,
                children: <Widget>[
                  for (final MapEntry<String, dynamic> frame in trends.entries)
                    StatusChip(
                      label: '${frame.key} · ${labelFor(kTrendLabels, '${frame.value}')}',
                      tone: switch ('${frame.value}') {
                        'BULLISH' => StatusTone.good,
                        'BEARISH' => StatusTone.bad,
                        _ => StatusTone.neutral,
                      },
                      dense: true,
                    ),
                ],
              ),
            ],
          ),
        ),
        if (reasons.isNotEmpty) ...<Widget>[
          const SizedBox(height: AppSpacing.md),
          AppCard(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: <Widget>[
                const SectionHeader(title: 'Ce que le scanner a relevé'),
                for (final String reason in reasons)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 4),
                    child: Text('• $reason', style: theme.textTheme.bodySmall),
                  ),
              ],
            ),
          ),
        ],
        if (anomalies.isNotEmpty) ...<Widget>[
          const SizedBox(height: AppSpacing.md),
          AppCard(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: <Widget>[
                const SectionHeader(title: 'Anomalies mesurées'),
                Wrap(
                  spacing: AppSpacing.sm,
                  runSpacing: AppSpacing.xs,
                  children: <Widget>[
                    for (final String anomaly in anomalies)
                      StatusChip(label: anomaly, tone: StatusTone.warning, dense: true),
                  ],
                ),
              ],
            ),
          ),
        ],
        const SizedBox(height: AppSpacing.md),
        _RegimeHistory(records: payload['regimeHistory']),
      ],
    );
  }
}

/// Historique des changements de régime : seuls les changements sont écrits.
class _RegimeHistory extends StatelessWidget {
  const _RegimeHistory({required this.records});

  final Object? records;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    final List<Map<String, dynamic>> items = <Map<String, dynamic>>[
      ...?(records as List<dynamic>?)?.map((dynamic e) => Map<String, dynamic>.from(e as Map)),
    ];

    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          const SectionHeader(
            title: 'Changements de régime',
            subtitle: 'Seuls les basculements sont enregistrés',
          ),
          if (items.isEmpty)
            Text('Aucun changement enregistré.', style: theme.textTheme.bodySmall)
          else
            for (final Map<String, dynamic> record in items)
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 4),
                child: Row(
                  children: <Widget>[
                    SizedBox(
                      width: 96,
                      child: Text(
                        shortMoment('${record['detectedAt']}'),
                        style: theme.textTheme.labelSmall,
                      ),
                    ),
                    Expanded(
                      child: Text(
                        '${record['timeframe']} · ${labelFor(kRegimeLabels, '${record['regime']}')}',
                        style: theme.textTheme.bodySmall,
                      ),
                    ),
                  ],
                ),
              ),
        ],
      ),
    );
  }
}
