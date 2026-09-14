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

final FutureProvider<Map<String, dynamic>> watchlistProvider =
    FutureProvider<Map<String, dynamic>>((Ref ref) {
  return ref.watch(apiClientProvider).getJson(Endpoints.marketWatchlist);
});

final FutureProvider<Map<String, dynamic>> lastScanProvider =
    FutureProvider<Map<String, dynamic>>((Ref ref) {
  return ref.watch(apiClientProvider).getJson(Endpoints.marketScan);
});

/// Marchés suivis : watchlist et dernier état connu de chaque instrument.
class MarketsScreen extends ConsumerWidget {
  const MarketsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final AsyncValue<Map<String, dynamic>> watchlist = ref.watch(watchlistProvider);
    final AsyncValue<Map<String, dynamic>> scan = ref.watch(lastScanProvider);

    return Scaffold(
      appBar: AppBar(
        title: const Text('Marchés'),
        actions: <Widget>[
          IconButton(
            tooltip: 'Vérifier la disponibilité chez le broker',
            onPressed: () => _refreshWatchlist(context, ref),
            icon: const Icon(Icons.sync),
          ),
        ],
      ),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: () => _addSymbol(context, ref),
        icon: const Icon(Icons.add),
        label: const Text('Instrument'),
      ),
      body: watchlist.when(
        loading: () => const LoadingView(label: 'Chargement de la watchlist…'),
        error: (Object error, StackTrace stack) => ErrorView(
          message: error is ApiException ? error.message : 'Watchlist indisponible.',
          technical: error is ApiException ? error.technical : error.toString(),
          onRetry: () => ref.invalidate(watchlistProvider),
        ),
        data: (Map<String, dynamic> payload) {
          final List<Map<String, dynamic>> items = <Map<String, dynamic>>[
            ...?(payload['items'] as List<dynamic>?)
                ?.map((dynamic e) => Map<String, dynamic>.from(e as Map)),
          ];
          if (items.isEmpty) {
            return const EmptyState(
              title: 'Aucun instrument suivi',
              message: 'Ajoutez les instruments que TradePilot a le droit d’observer. '
                  'Chaque ajout est vérifié auprès du broker avant d’être accepté.',
              icon: Icons.show_chart_outlined,
            );
          }

          // Le dernier scan est facultatif : la watchlist reste lisible même
          // quand aucune analyse n'a encore été enregistrée.
          final Map<String, Map<String, dynamic>> snapshots =
              <String, Map<String, dynamic>>{
            for (final dynamic entry
                in (scan.valueOrNull?['items'] as List<dynamic>?) ?? const <dynamic>[])
              '${(entry as Map<dynamic, dynamic>)['symbol']}':
                  Map<String, dynamic>.from(entry),
          };

          return RefreshIndicator(
            onRefresh: () async {
              ref
                ..invalidate(watchlistProvider)
                ..invalidate(lastScanProvider);
            },
            child: ListView.separated(
              padding: AppSpacing.page,
              itemCount: items.length,
              separatorBuilder: (BuildContext context, int index) =>
                  const SizedBox(height: AppSpacing.sm),
              itemBuilder: (BuildContext context, int index) {
                final Map<String, dynamic> item = items[index];
                return _WatchlistTile(
                  item: item,
                  snapshot: snapshots['${item['symbol']}'],
                );
              },
            ),
          );
        },
      ),
    );
  }

  Future<void> _refreshWatchlist(BuildContext context, WidgetRef ref) async {
    try {
      final Map<String, dynamic> result =
          await ref.read(apiClientProvider).postJson(Endpoints.marketWatchlistRefresh);
      ref.invalidate(watchlistProvider);
      if (!context.mounted) return;
      showToast(context, '${result['checked'] ?? 0} instrument(s) vérifié(s).');
    } on ApiException catch (error) {
      if (!context.mounted) return;
      showToast(context, error.message, error: true);
    }
  }

  Future<void> _addSymbol(BuildContext context, WidgetRef ref) async {
    final TextEditingController controller = TextEditingController();
    final String? symbol = await showDialog<String>(
      context: context,
      builder: (BuildContext context) => AlertDialog(
        title: const Text('Ajouter un instrument'),
        content: TextField(
          controller: controller,
          autofocus: true,
          textCapitalization: TextCapitalization.characters,
          decoration: const InputDecoration(
            labelText: 'Symbole',
            hintText: 'XAUUSD, EURUSD, US30…',
          ),
        ),
        actions: <Widget>[
          TextButton(onPressed: () => Navigator.of(context).pop(), child: const Text('Annuler')),
          FilledButton(
            onPressed: () => Navigator.of(context).pop(controller.text.trim()),
            child: const Text('Ajouter'),
          ),
        ],
      ),
    );
    controller.dispose();
    if (symbol == null || symbol.isEmpty || !context.mounted) return;

    try {
      await ref.read(apiClientProvider).postJson(
            Endpoints.marketWatchlist,
            body: <String, dynamic>{'symbol': symbol},
          );
      ref.invalidate(watchlistProvider);
      if (!context.mounted) return;
      showToast(context, '$symbol ajouté à la watchlist.');
    } on ApiException catch (error) {
      if (!context.mounted) return;
      // Le Bridge explique pourquoi il refuse (instrument inconnu du broker,
      // suggestions proches) : on montre son message tel quel.
      showToast(context, error.message, error: true);
    }
  }
}

class _WatchlistTile extends ConsumerWidget {
  const _WatchlistTile({required this.item, this.snapshot});

  final Map<String, dynamic> item;
  final Map<String, dynamic>? snapshot;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final ThemeData theme = Theme.of(context);
    final String symbol = '${item['symbol'] ?? ''}';
    final bool available = item['available'] == true;
    final Map<String, dynamic> trends = Map<String, dynamic>.from(
      (snapshot?['trends'] as Map<dynamic, dynamic>?) ?? const <dynamic, dynamic>{},
    );

    return AppCard(
      onTap: () => context.push(Routes.marketDetail(symbol)),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Row(
            children: <Widget>[
              Text(symbol, style: theme.textTheme.titleSmall),
              const SizedBox(width: AppSpacing.sm),
              if (!available)
                const StatusChip(
                  label: 'Indisponible chez le broker',
                  tone: StatusTone.bad,
                  dense: true,
                ),
              const Spacer(),
              Switch(
                value: item['enabled'] == true,
                onChanged: (bool value) => _toggle(context, ref, symbol, value),
              ),
            ],
          ),
          if (snapshot != null) ...<Widget>[
            const SizedBox(height: AppSpacing.xs),
            Row(
              children: <Widget>[
                Expanded(
                  child: MetricTile(
                    label: 'Prix',
                    value: number(snapshot?['bid'], digits: 5),
                    compact: true,
                  ),
                ),
                Expanded(
                  child: MetricTile(
                    label: 'Spread',
                    value: '${snapshot?['spreadPoints'] ?? '—'} pts',
                    compact: true,
                  ),
                ),
                Expanded(
                  child: MetricTile(
                    label: 'Régime',
                    value: labelFor(kRegimeLabels, '${snapshot?['regime']}'),
                    compact: true,
                  ),
                ),
              ],
            ),
            const SizedBox(height: AppSpacing.sm),
            Wrap(
              spacing: AppSpacing.sm,
              children: <Widget>[
                for (final String frame in <String>['D1', 'H4', 'H1'])
                  StatusChip(
                    label: '$frame ${labelFor(kTrendLabels, '${trends[frame]}').toLowerCase()}',
                    dense: true,
                  ),
              ],
            ),
            const SizedBox(height: AppSpacing.xs),
            Text(
              'Analysé ${relativeMoment('${snapshot?['capturedAt']}')}',
              style: theme.textTheme.labelSmall,
            ),
          ] else ...<Widget>[
            const SizedBox(height: AppSpacing.xs),
            Text(
              'Pas encore analysé.',
              style: theme.textTheme.labelSmall,
            ),
          ],
        ],
      ),
    );
  }

  Future<void> _toggle(
    BuildContext context,
    WidgetRef ref,
    String symbol,
    bool enabled,
  ) async {
    try {
      await ref.read(apiClientProvider).patchJson(
            Endpoints.marketWatchlistItem(symbol),
            body: <String, dynamic>{'enabled': enabled},
          );
      ref.invalidate(watchlistProvider);
    } on ApiException catch (error) {
      if (!context.mounted) return;
      showToast(context, error.message, error: true);
    }
  }
}
