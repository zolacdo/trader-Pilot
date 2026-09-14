import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/api/api_exception.dart';
import '../../../core/routing/app_router.dart';
import '../../../core/theme/app_theme.dart';
import '../../../core/utils/formatters.dart';
import '../../../core/widgets/app_widgets.dart';
import '../trades_models.dart';
import '../trades_providers.dart';
import 'position_actions.dart';
import 'trade_list_shell.dart';

/// Onglet « En attente » : ordres placés dans le carnet, pas encore déclenchés.
class PendingOrdersView extends ConsumerWidget {
  const PendingOrdersView({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final AsyncValue<OrdersSnapshot> orders = ref.watch(pendingOrdersProvider);

    return RefreshIndicator(
      onRefresh: () async {
        ref.invalidate(pendingOrdersProvider);
        await ref.read(pendingOrdersProvider.future);
      },
      child: orders.when(
        loading: () => const LoadingView(label: 'Lecture du carnet d\'ordres…'),
        error: (Object error, StackTrace stack) => FillViewport(
          child: ErrorView(
            message: error is ApiException ? error.message : 'Ordres en attente indisponibles.',
            technical: error is ApiException ? error.technical : error.toString(),
            onRetry: () => ref.invalidate(pendingOrdersProvider),
          ),
        ),
        data: (OrdersSnapshot snapshot) {
          if (snapshot.items.isEmpty) {
            return const FillViewport(
              child: EmptyState(
                title: 'Aucun ordre en attente',
                message: 'Les ordres limites et stops non déclenchés s\'afficheront ici.',
                icon: Icons.schedule_outlined,
              ),
            );
          }
          return ListView.separated(
            padding: AppSpacing.page,
            physics: const AlwaysScrollableScrollPhysics(),
            itemCount: snapshot.items.length,
            separatorBuilder: (BuildContext context, int index) =>
                const SizedBox(height: AppSpacing.md),
            itemBuilder: (BuildContext context, int index) =>
                _OrderCard(order: snapshot.items[index]),
          );
        },
      ),
    );
  }
}

class _OrderCard extends ConsumerWidget {
  const _OrderCard({required this.order});

  final PendingOrder order;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final ThemeData theme = Theme.of(context);

    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Row(
            children: <Widget>[
              Expanded(
                child: Text(
                  order.symbol,
                  overflow: TextOverflow.ellipsis,
                  style: theme.textTheme.titleMedium,
                ),
              ),
              StatusChip.direction(order.direction),
            ],
          ),
          const SizedBox(height: AppSpacing.xs),
          Text(
            '${order.orderTypeLabel} · ${Fmt.lots(order.volume)} lot · ticket ${order.ticket}',
            style: theme.textTheme.bodySmall,
          ),
          const SizedBox(height: AppSpacing.md),
          const Divider(height: 1),
          DetailRow(label: 'Prix de déclenchement', value: Fmt.price(order.price), monospace: true),
          DetailRow(label: 'Stop loss', value: Fmt.price(order.stopLoss), monospace: true),
          DetailRow(label: 'Take profit', value: Fmt.price(order.takeProfit), monospace: true),
          DetailRow(label: 'Placé le', value: Fmt.dayTime(order.createdAt)),
          DetailRow(
            label: 'Expire le',
            value: order.expiresAt == null ? 'Sans expiration' : Fmt.dayTime(order.expiresAt),
          ),
          if (!order.managedByTradePilot) ...<Widget>[
            const SizedBox(height: AppSpacing.sm),
            const StatusChip(
              label: 'Placé hors TradePilot',
              tone: StatusTone.warning,
              dense: true,
            ),
          ],
          if (order.signalId != null) ...<Widget>[
            const SizedBox(height: AppSpacing.xs),
            Align(
              alignment: Alignment.centerLeft,
              child: TextButton.icon(
                onPressed: () => context.push(Routes.signalDetail(order.signalId!)),
                icon: const Icon(Icons.podcasts_outlined, size: 17),
                label: Text('Signal d\'origine n° ${order.signalId}'),
                style: TextButton.styleFrom(padding: EdgeInsets.zero),
              ),
            ),
          ],
          const SizedBox(height: AppSpacing.sm),
          SizedBox(
            width: double.infinity,
            child: OutlinedButton.icon(
              onPressed: () => confirmCancelOrder(context, ref, order),
              icon: const Icon(Icons.cancel_outlined, size: 18),
              label: const Text('Annuler cet ordre'),
            ),
          ),
        ],
      ),
    );
  }
}
