import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api/ws_client.dart';
import '../../core/connection/connection_controller.dart';
import 'trades_providers.dart';
import 'widgets/closed_trades_view.dart';
import 'widgets/open_positions_view.dart';
import 'widgets/pending_orders_view.dart';
import 'widgets/trades_header.dart';

/// Page Trades (CDC section 35).
///
/// Trois onglets : positions ouvertes, ordres en attente, historique fermé.
/// Les données se rafraîchissent sur les événements temps réel du Bridge et
/// sur le geste « tirer pour rafraîchir ».
class TradesScreen extends ConsumerStatefulWidget {
  const TradesScreen({super.key});

  @override
  ConsumerState<TradesScreen> createState() => _TradesScreenState();
}

class _TradesScreenState extends ConsumerState<TradesScreen>
    with SingleTickerProviderStateMixin {
  /// Événements qui rendent obsolète ce qui est affiché ici.
  static const Set<String> _liveEvents = <String>{
    BridgeEvents.positionOpened,
    BridgeEvents.positionUpdated,
    BridgeEvents.positionClosed,
    BridgeEvents.orderPlaced,
    BridgeEvents.orderCancelled,
  };

  late final TabController _controller = TabController(length: 3, vsync: this);

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  void _refreshFromEvent(String type) {
    ref.invalidate(openPositionsProvider);
    ref.invalidate(pendingOrdersProvider);
    if (type == BridgeEvents.positionClosed) {
      ref.read(closedTradesProvider.notifier).reload();
    }
  }

  @override
  Widget build(BuildContext context) {
    ref.listen<AsyncValue<BridgeEvent>>(bridgeEventsProvider,
        (AsyncValue<BridgeEvent>? previous, AsyncValue<BridgeEvent> next) {
      final BridgeEvent? event = next.value;
      if (event != null && _liveEvents.contains(event.type)) {
        _refreshFromEvent(event.type);
      }
    });

    return Scaffold(
      appBar: AppBar(
        title: const Text('Trades'),
        bottom: TabBar(
          controller: _controller,
          tabs: const <Widget>[
            Tab(text: 'Ouverts'),
            Tab(text: 'En attente'),
            Tab(text: 'Fermés'),
          ],
        ),
      ),
      body: Column(
        children: <Widget>[
          const TradesHeader(),
          Expanded(
            child: TabBarView(
              controller: _controller,
              children: const <Widget>[
                OpenPositionsView(),
                PendingOrdersView(),
                ClosedTradesView(),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
