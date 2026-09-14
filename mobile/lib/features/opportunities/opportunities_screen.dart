import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api/api_exception.dart';
import '../../core/api/endpoints.dart';
import '../../core/connection/connection_controller.dart';
import '../../core/theme/app_theme.dart';
import '../../core/widgets/app_widgets.dart';
import '../intelligence/labels.dart';

final FutureProvider<Map<String, dynamic>> opportunitiesProvider =
    FutureProvider<Map<String, dynamic>>((Ref ref) {
  return ref
      .watch(apiClientProvider)
      .getJson(Endpoints.opportunities, query: <String, dynamic>{'limit': 60});
});

final FutureProvider<Map<String, dynamic>> intelligenceStatusProvider =
    FutureProvider<Map<String, dynamic>>((Ref ref) {
  return ref.watch(apiClientProvider).getJson(Endpoints.intelligenceStatus);
});

/// Opportunités générées par le système lui-même (CDC2 section 40).
///
/// Une liste vide est un résultat normal : le plus souvent, aucun setup ne se
/// présente. L'écran le dit plutôt que de laisser croire à une panne.
class OpportunitiesScreen extends ConsumerWidget {
  const OpportunitiesScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final AsyncValue<Map<String, dynamic>> opportunities = ref.watch(opportunitiesProvider);

    return Scaffold(
      appBar: AppBar(
        title: const Text('Opportunités'),
        actions: <Widget>[
          IconButton(
            tooltip: 'Analyser le marché maintenant',
            onPressed: () => _scanNow(context, ref),
            icon: const Icon(Icons.radar_outlined),
          ),
        ],
      ),
      body: Column(
        children: <Widget>[
          const _IntelligenceBanner(),
          Expanded(
            child: opportunities.when(
              loading: () => const LoadingView(label: 'Chargement des opportunités…'),
              error: (Object error, StackTrace stack) => ErrorView(
                message: error is ApiException ? error.message : 'Opportunités indisponibles.',
                technical: error is ApiException ? error.technical : error.toString(),
                onRetry: () => ref.invalidate(opportunitiesProvider),
              ),
              data: (Map<String, dynamic> payload) {
                final List<Map<String, dynamic>> items = <Map<String, dynamic>>[
                  ...?(payload['items'] as List<dynamic>?)
                      ?.map((dynamic e) => Map<String, dynamic>.from(e as Map)),
                ];
                if (items.isEmpty) {
                  return const EmptyState(
                    title: 'Aucune opportunité en cours',
                    message: 'C’est le cas le plus fréquent : le système n’ouvre une position '
                        'que lorsque plusieurs lectures concordent. Rester à l’écart des '
                        'heures durant est un fonctionnement normal.',
                    icon: Icons.auto_awesome_outlined,
                  );
                }
                return RefreshIndicator(
                  onRefresh: () async => ref.invalidate(opportunitiesProvider),
                  child: ListView.separated(
                    padding: AppSpacing.page,
                    itemCount: items.length,
                    separatorBuilder: (BuildContext context, int index) =>
                        const SizedBox(height: AppSpacing.sm),
                    itemBuilder: (BuildContext context, int index) =>
                        _OpportunityCard(item: items[index]),
                  ),
                );
              },
            ),
          ),
        ],
      ),
    );
  }

  Future<void> _scanNow(BuildContext context, WidgetRef ref) async {
    showToast(context, 'Analyse du marché en cours…');
    try {
      final Map<String, dynamic> response =
          await ref.read(apiClientProvider).postJson(Endpoints.intelligenceRun('scan'));
      ref
        ..invalidate(opportunitiesProvider)
        ..invalidate(intelligenceStatusProvider);
      if (!context.mounted) return;
      final Map<String, dynamic> result = Map<String, dynamic>.from(
        (response['result'] as Map<dynamic, dynamic>?) ?? const <dynamic, dynamic>{},
      );
      showToast(
        context,
        '${result['analysed'] ?? 0} instrument(s) analysé(s), '
        '${result['qualified'] ?? 0} opportunité(s) retenue(s).',
      );
    } on ApiException catch (error) {
      if (!context.mounted) return;
      showToast(context, error.message, error: true);
    }
  }
}

/// Bandeau d'état : dit quand le marché a été analysé pour la dernière fois.
class _IntelligenceBanner extends ConsumerWidget {
  const _IntelligenceBanner();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final AsyncValue<Map<String, dynamic>> status = ref.watch(intelligenceStatusProvider);
    final Map<String, dynamic>? payload = status.valueOrNull;
    if (payload == null) return const SizedBox.shrink();

    final Map<String, dynamic> scan = Map<String, dynamic>.from(
      (payload['scan'] as Map<dynamic, dynamic>?) ?? const <dynamic, dynamic>{},
    );
    final ThemeData theme = Theme.of(context);

    return Padding(
      padding: const EdgeInsets.fromLTRB(
        AppSpacing.lg,
        AppSpacing.md,
        AppSpacing.lg,
        0,
      ),
      child: AppCard(
        padding: const EdgeInsets.symmetric(horizontal: AppSpacing.md, vertical: 10),
        child: Row(
          children: <Widget>[
            Icon(
              payload['started'] == true ? Icons.autorenew : Icons.pause_circle_outline,
              size: 18,
              color: theme.colorScheme.primary,
            ),
            const SizedBox(width: AppSpacing.sm),
            Expanded(
              child: Text(
                payload['started'] == true
                    ? 'Analyse automatique active · dernier passage ${relativeMoment('${scan['lastRunAt']}')}'
                    : 'Analyse automatique arrêtée',
                style: theme.textTheme.bodySmall,
              ),
            ),
            if (scan['lastError'] != null)
              const StatusChip(label: 'Erreur', tone: StatusTone.bad, dense: true),
          ],
        ),
      ),
    );
  }
}

class _OpportunityCard extends StatelessWidget {
  const _OpportunityCard({required this.item});

  final Map<String, dynamic> item;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    final List<double> targets = <double>[
      ...?(item['takeProfits'] as List<dynamic>?)
          ?.whereType<num>()
          .map((num e) => e.toDouble()),
    ];
    final List<String> reasons = <String>[
      ...?(item['reasons'] as List<dynamic>?)?.map((dynamic e) => '$e'),
    ];
    final List<String> negatives = <String>[
      ...?(item['negativeFactors'] as List<dynamic>?)?.map((dynamic e) => '$e'),
    ];

    return AppCard(
      accent: item['status'] == 'PENDING',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Row(
            children: <Widget>[
              Text('${item['symbol'] ?? ''}', style: theme.textTheme.titleMedium),
              const SizedBox(width: AppSpacing.sm),
              StatusChip.direction('${item['direction']}'),
              const Spacer(),
              StatusChip(
                label: percentFromRatio(item['confidence']),
                tone: (item['confidence'] is num && (item['confidence'] as num) >= 0.75)
                    ? StatusTone.good
                    : StatusTone.warning,
                dense: true,
              ),
            ],
          ),
          const SizedBox(height: AppSpacing.xs),
          Text(
            '${item['strategy'] ?? ''} · ${relativeMoment('${item['createdAt']}')}'
            '${item['expiresAt'] != null ? ' · expire ${relativeMoment('${item['expiresAt']}')}' : ''}',
            style: theme.textTheme.labelSmall,
          ),
          const SizedBox(height: AppSpacing.md),
          Row(
            children: <Widget>[
              Expanded(
                child: MetricTile(
                  label: 'Entrée',
                  value: number(item['entryPrice'], digits: 5),
                  compact: true,
                ),
              ),
              Expanded(
                child: MetricTile(
                  label: 'Stop',
                  value: number(item['stopLoss'], digits: 5),
                  compact: true,
                ),
              ),
              Expanded(
                child: MetricTile(
                  label: 'R/R',
                  value: number(item['expectedRr'], digits: 2),
                  compact: true,
                ),
              ),
            ],
          ),
          if (targets.isNotEmpty) ...<Widget>[
            const SizedBox(height: AppSpacing.sm),
            DetailRow(
              label: 'Objectifs',
              value: targets.map((double t) => t.toStringAsFixed(5)).join('  ·  '),
              monospace: true,
            ),
          ],
          if (reasons.isNotEmpty) ...<Widget>[
            const SizedBox(height: AppSpacing.sm),
            for (final String reason in reasons.take(4))
              Padding(
                padding: const EdgeInsets.only(bottom: 2),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: <Widget>[
                    const Icon(Icons.add, size: 14, color: Colors.green),
                    const SizedBox(width: 6),
                    Expanded(child: Text(reason, style: theme.textTheme.bodySmall)),
                  ],
                ),
              ),
          ],
          if (negatives.isNotEmpty) ...<Widget>[
            const SizedBox(height: AppSpacing.xs),
            for (final String negative in negatives.take(3))
              Padding(
                padding: const EdgeInsets.only(bottom: 2),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: <Widget>[
                    const Icon(Icons.remove, size: 14, color: Colors.redAccent),
                    const SizedBox(width: 6),
                    Expanded(child: Text(negative, style: theme.textTheme.bodySmall)),
                  ],
                ),
              ),
          ],
        ],
      ),
    );
  }
}
