import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/api/api_exception.dart';
import '../../../core/routing/app_router.dart';
import '../../../core/theme/app_colors.dart';
import '../../../core/theme/app_theme.dart';
import '../../../core/utils/formatters.dart';
import '../../../core/widgets/app_widgets.dart';
import '../trades_models.dart';
import '../trades_providers.dart';
import 'trade_list_shell.dart';

/// Onglet « Fermés » : historique paginé des trades clôturés.
class ClosedTradesView extends ConsumerWidget {
  const ClosedTradesView({super.key});

  static const List<int> _depths = <int>[7, 30, 90, 365];

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final AsyncValue<ClosedTradesPage> history = ref.watch(closedTradesProvider);
    final ClosedTradesController controller = ref.read(closedTradesProvider.notifier);
    final Map<int, String> channels = ref.watch(channelNamesProvider).valueOrNull ?? <int, String>{};

    return Column(
      children: <Widget>[
        Padding(
          padding: const EdgeInsets.fromLTRB(AppSpacing.lg, AppSpacing.md, AppSpacing.lg, 0),
          child: Row(
            children: <Widget>[
              Text('Période', style: Theme.of(context).textTheme.bodySmall),
              const SizedBox(width: AppSpacing.md),
              Expanded(
                child: SingleChildScrollView(
                  scrollDirection: Axis.horizontal,
                  child: Row(
                    children: <Widget>[
                      for (final int days in _depths) ...<Widget>[
                        ChoiceChip(
                          label: Text(days == 365 ? '1 an' : '$days j'),
                          selected: controller.days == days,
                          onSelected: (bool selected) {
                            if (selected) controller.reload(days: days);
                          },
                        ),
                        const SizedBox(width: AppSpacing.sm),
                      ],
                    ],
                  ),
                ),
              ),
            ],
          ),
        ),
        Expanded(
          child: RefreshIndicator(
            onRefresh: () => controller.reload(),
            child: history.when(
              loading: () => const LoadingView(label: 'Lecture de l\'historique…'),
              error: (Object error, StackTrace stack) => FillViewport(
                child: ErrorView(
                  message: error is ApiException ? error.message : 'Historique indisponible.',
                  technical: error is ApiException ? error.technical : error.toString(),
                  onRetry: controller.reload,
                ),
              ),
              data: (ClosedTradesPage page) {
                if (page.items.isEmpty) {
                  return const FillViewport(
                    child: EmptyState(
                      title: 'Aucun trade fermé',
                      message: 'Aucun trade clôturé sur la période sélectionnée.',
                      icon: Icons.history,
                    ),
                  );
                }
                return ListView.separated(
                  padding: AppSpacing.page,
                  physics: const AlwaysScrollableScrollPhysics(),
                  itemCount: page.items.length + (page.hasMore ? 1 : 0),
                  separatorBuilder: (BuildContext context, int index) =>
                      const SizedBox(height: AppSpacing.md),
                  itemBuilder: (BuildContext context, int index) {
                    if (index >= page.items.length) {
                      return _LoadMoreButton(page: page, controller: controller);
                    }
                    final ClosedTrade trade = page.items[index];
                    return _ClosedTradeCard(
                      trade: trade,
                      channelName: trade.channelId == null ? null : channels[trade.channelId],
                    );
                  },
                );
              },
            ),
          ),
        ),
      ],
    );
  }
}

class _LoadMoreButton extends StatelessWidget {
  const _LoadMoreButton({required this.page, required this.controller});

  final ClosedTradesPage page;
  final ClosedTradesController controller;

  @override
  Widget build(BuildContext context) {
    if (page.loadingMore) {
      return const Padding(
        padding: EdgeInsets.symmetric(vertical: AppSpacing.lg),
        child: LoadingView(),
      );
    }
    return OutlinedButton(
      onPressed: () async {
        final String? error = await controller.loadMore();
        if (error != null && context.mounted) showToast(context, error, error: true);
      },
      child: const Text('Charger les trades suivants'),
    );
  }
}

class _ClosedTradeCard extends StatelessWidget {
  const _ClosedTradeCard({required this.trade, this.channelName});

  final ClosedTrade trade;
  final String? channelName;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    final bool dark = theme.brightness == Brightness.dark;
    final double? pnl = trade.realizedPnl;

    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Row(
            children: <Widget>[
              Expanded(
                child: Row(
                  children: <Widget>[
                    Flexible(
                      child: Text(
                        trade.symbol,
                        overflow: TextOverflow.ellipsis,
                        style: theme.textTheme.titleMedium,
                      ),
                    ),
                    const SizedBox(width: AppSpacing.sm),
                    StatusChip.direction(trade.direction),
                  ],
                ),
              ),
              Text(
                Fmt.signedMoney(pnl),
                style: theme.textTheme.titleMedium?.copyWith(
                  color: pnl == null ? null : AppColors.forAmount(pnl, dark: dark),
                  fontFeatures: const <FontFeature>[FontFeature.tabularFigures()],
                ),
              ),
            ],
          ),
          const SizedBox(height: AppSpacing.xs),
          Text(
            '${Fmt.lots(trade.volume)} lot · fermé ${Fmt.dayTime(trade.closedAt)} · '
            'ticket ${trade.ticket}',
            style: theme.textTheme.bodySmall,
          ),
          const SizedBox(height: AppSpacing.md),
          const Divider(height: 1),
          DetailRow(label: 'Entrée', value: Fmt.price(trade.openPrice), monospace: true),
          DetailRow(label: 'Sortie', value: Fmt.price(trade.closePrice), monospace: true),
          DetailRow(
            label: 'Multiple de R',
            value: trade.rMultiple == null ? '--' : '${trade.rMultiple!.toStringAsFixed(2)} R',
          ),
          DetailRow(label: 'Motif de clôture', value: trade.closeReason ?? '--'),
          DetailRow(label: 'Ouvert le', value: Fmt.dayTime(trade.openedAt)),
          if (channelName != null) ...<Widget>[
            const SizedBox(height: AppSpacing.sm),
            Row(
              children: <Widget>[
                const Icon(Icons.forum_outlined, size: 15),
                const SizedBox(width: 6),
                Expanded(
                  child: Text(
                    'Canal source : $channelName',
                    overflow: TextOverflow.ellipsis,
                    style: theme.textTheme.bodySmall,
                  ),
                ),
              ],
            ),
          ],
          if (trade.signalId != null) ...<Widget>[
            const SizedBox(height: AppSpacing.xs),
            Align(
              alignment: Alignment.centerLeft,
              child: TextButton.icon(
                onPressed: () => context.push(Routes.signalDetail(trade.signalId!)),
                icon: const Icon(Icons.podcasts_outlined, size: 17),
                label: Text('Signal d\'origine n° ${trade.signalId}'),
                style: TextButton.styleFrom(padding: EdgeInsets.zero),
              ),
            ),
          ],
        ],
      ),
    );
  }
}
