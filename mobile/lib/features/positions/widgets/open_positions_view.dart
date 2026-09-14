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
import 'position_actions.dart';
import 'trade_list_shell.dart';

/// Onglet « Ouverts » : positions réellement ouvertes chez le broker.
class OpenPositionsView extends ConsumerWidget {
  const OpenPositionsView({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final AsyncValue<PositionsSnapshot> positions = ref.watch(openPositionsProvider);
    final Map<int, String> channels = ref.watch(channelNamesProvider).valueOrNull ?? <int, String>{};

    return RefreshIndicator(
      onRefresh: () async {
        ref.invalidate(openPositionsProvider);
        ref.invalidate(channelNamesProvider);
        await ref.read(openPositionsProvider.future);
      },
      child: positions.when(
        loading: () => const LoadingView(label: 'Lecture des positions…'),
        error: (Object error, StackTrace stack) => FillViewport(
          child: ErrorView(
            message: error is ApiException ? error.message : 'Positions indisponibles.',
            technical: error is ApiException ? error.technical : error.toString(),
            onRetry: () => ref.invalidate(openPositionsProvider),
          ),
        ),
        data: (PositionsSnapshot snapshot) {
          if (snapshot.items.isEmpty) {
            return const FillViewport(
              child: EmptyState(
                title: 'Aucune position ouverte',
                message: 'Les positions apparaîtront ici dès qu\'un signal sera exécuté.',
                icon: Icons.trending_flat,
              ),
            );
          }
          return ListView.separated(
            padding: AppSpacing.page,
            physics: const AlwaysScrollableScrollPhysics(),
            itemCount: snapshot.items.length,
            separatorBuilder: (BuildContext context, int index) =>
                const SizedBox(height: AppSpacing.md),
            itemBuilder: (BuildContext context, int index) {
              final OpenPosition position = snapshot.items[index];
              return _PositionCard(
                position: position,
                channelName: position.channelId == null ? null : channels[position.channelId],
              );
            },
          );
        },
      ),
    );
  }
}

class _PositionCard extends ConsumerWidget {
  const _PositionCard({required this.position, this.channelName});

  final OpenPosition position;
  final String? channelName;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final ThemeData theme = Theme.of(context);
    final bool dark = theme.brightness == Brightness.dark;
    final double? profit = position.profit;

    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: <Widget>[
              Expanded(
                child: Row(
                  children: <Widget>[
                    Flexible(
                      child: Text(
                        position.symbol,
                        overflow: TextOverflow.ellipsis,
                        style: theme.textTheme.titleMedium,
                      ),
                    ),
                    const SizedBox(width: AppSpacing.sm),
                    StatusChip.direction(position.direction),
                  ],
                ),
              ),
              Text(
                Fmt.signedMoney(profit),
                style: theme.textTheme.titleMedium?.copyWith(
                  color: profit == null ? null : AppColors.forAmount(profit, dark: dark),
                  fontFeatures: const <FontFeature>[FontFeature.tabularFigures()],
                ),
              ),
            ],
          ),
          const SizedBox(height: AppSpacing.xs),
          Text(
            '${Fmt.lots(position.volume)} lot · ouverte ${Fmt.relative(position.openedAt)} · '
            'ticket ${position.ticket}',
            style: theme.textTheme.bodySmall,
          ),
          const SizedBox(height: AppSpacing.md),
          const Divider(height: 1),
          DetailRow(label: 'Prix d\'entrée', value: Fmt.price(position.openPrice), monospace: true),
          DetailRow(label: 'Prix actuel', value: Fmt.price(position.currentPrice), monospace: true),
          DetailRow(label: 'Stop loss', value: Fmt.price(position.stopLoss), monospace: true),
          DetailRow(label: 'Take profit', value: Fmt.price(position.takeProfit), monospace: true),
          if (position.takeProfitTargets.length > 1)
            DetailRow(
              label: 'Objectifs du signal',
              value: position.takeProfitTargets.map(Fmt.price).join(' · '),
            ),
          if (position.takeProfitTargets.length > 1)
            DetailRow(
              label: 'Objectifs atteints',
              value: '${position.tpIndex} sur ${position.takeProfitTargets.length}',
            ),
          const SizedBox(height: AppSpacing.sm),
          Wrap(
            spacing: AppSpacing.sm,
            runSpacing: AppSpacing.sm,
            children: <Widget>[
              if (position.breakEvenApplied)
                const StatusChip(label: 'Break even appliqué', tone: StatusTone.good, dense: true),
              if (!position.managedByTradePilot)
                const StatusChip(
                  label: 'Ouverte hors TradePilot',
                  tone: StatusTone.warning,
                  dense: true,
                ),
            ],
          ),
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
          if (position.signalId != null) ...<Widget>[
            const SizedBox(height: AppSpacing.xs),
            Align(
              alignment: Alignment.centerLeft,
              child: TextButton.icon(
                onPressed: () => context.push(Routes.signalDetail(position.signalId!)),
                icon: const Icon(Icons.podcasts_outlined, size: 17),
                label: Text('Signal d\'origine n° ${position.signalId}'),
                style: TextButton.styleFrom(padding: EdgeInsets.zero),
              ),
            ),
          ],
          const SizedBox(height: AppSpacing.sm),
          SizedBox(
            width: double.infinity,
            child: OutlinedButton.icon(
              onPressed: () => showPositionActions(context, ref, position),
              icon: const Icon(Icons.tune, size: 18),
              label: const Text('Gérer cette position'),
            ),
          ),
        ],
      ),
    );
  }
}
