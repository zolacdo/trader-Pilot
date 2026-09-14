import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api/api_client.dart';
import '../../core/api/api_exception.dart';
import '../../core/api/endpoints.dart';
import '../../core/connection/connection_controller.dart';
import 'trades_models.dart';

/// Positions actuellement ouvertes chez le broker actif.
final AutoDisposeFutureProvider<PositionsSnapshot> openPositionsProvider =
    FutureProvider.autoDispose<PositionsSnapshot>((Ref<Object?> ref) async {
  final Map<String, dynamic> payload =
      await ref.watch(apiClientProvider).getJson(Endpoints.positions);
  return PositionsSnapshot.fromJson(payload);
});

/// Ordres en attente (limites et stops non déclenchés).
final AutoDisposeFutureProvider<OrdersSnapshot> pendingOrdersProvider =
    FutureProvider.autoDispose<OrdersSnapshot>((Ref<Object?> ref) async {
  final Map<String, dynamic> payload = await ref.watch(apiClientProvider).getJson(Endpoints.orders);
  return OrdersSnapshot.fromJson(payload);
});

/// Noms des canaux suivis, pour afficher la source d'un trade plutôt qu'un
/// simple identifiant.
final AutoDisposeFutureProvider<Map<int, String>> channelNamesProvider =
    FutureProvider.autoDispose<Map<int, String>>((Ref<Object?> ref) async {
  final List<dynamic> raw = await ref.watch(apiClientProvider).getList(Endpoints.channels);
  final Map<int, String> names = <int, String>{};
  for (final Map<String, dynamic> channel in asMapList(raw)) {
    final int? id = asInt(channel['id']);
    final String? title = asText(channel['title']) ?? asText(channel['username']);
    if (id != null && title != null) names[id] = title;
  }
  return names;
});

/// Historique paginé des trades fermés (`GET /history`).
class ClosedTradesController extends StateNotifier<AsyncValue<ClosedTradesPage>> {
  ClosedTradesController(this._api) : super(const AsyncValue<ClosedTradesPage>.loading()) {
    reload();
  }

  static const int pageSize = 50;

  final ApiClient _api;
  int _days = 30;

  int get days => _days;

  /// Recharge la première page, éventuellement sur une autre profondeur.
  Future<void> reload({int? days}) async {
    if (days != null) _days = days;
    state = const AsyncValue<ClosedTradesPage>.loading();
    try {
      final List<ClosedTrade> items = await _fetch(offset: 0);
      if (!mounted) return;
      state = AsyncValue<ClosedTradesPage>.data(
        ClosedTradesPage(items: items, days: _days, hasMore: items.length >= pageSize),
      );
    } on ApiException catch (error, stack) {
      if (!mounted) return;
      state = AsyncValue<ClosedTradesPage>.error(error, stack);
    }
  }

  /// Charge la page suivante et l'ajoute à la liste déjà affichée.
  ///
  /// Retourne le message d'erreur si la page suivante n'a pas pu être lue :
  /// ce qui est déjà affiché n'est jamais effacé pour autant.
  Future<String?> loadMore() async {
    final ClosedTradesPage? current = state.valueOrNull;
    if (current == null || !current.hasMore || current.loadingMore) return null;
    state = AsyncValue<ClosedTradesPage>.data(current.copyWith(loadingMore: true));
    try {
      final List<ClosedTrade> next = await _fetch(offset: current.items.length);
      if (!mounted) return null;
      state = AsyncValue<ClosedTradesPage>.data(
        current.copyWith(
          items: <ClosedTrade>[...current.items, ...next],
          hasMore: next.length >= pageSize,
          loadingMore: false,
        ),
      );
      return null;
    } on ApiException catch (error) {
      if (!mounted) return null;
      state = AsyncValue<ClosedTradesPage>.data(current.copyWith(loadingMore: false));
      return error.message;
    }
  }

  Future<List<ClosedTrade>> _fetch({required int offset}) async {
    final Map<String, dynamic> payload = await _api.getJson(
      Endpoints.history,
      query: <String, dynamic>{'days': _days, 'limit': pageSize, 'offset': offset},
    );
    return asMapList(payload['items']).map(ClosedTrade.fromJson).toList(growable: false);
  }
}

final AutoDisposeStateNotifierProvider<ClosedTradesController, AsyncValue<ClosedTradesPage>>
    closedTradesProvider =
    StateNotifierProvider.autoDispose<ClosedTradesController, AsyncValue<ClosedTradesPage>>(
  (Ref<Object?> ref) => ClosedTradesController(ref.watch(apiClientProvider)),
);

/// Actions manuelles sur une position ou un ordre.
///
/// Chaque appel remonte l'`ApiException` telle quelle : l'écran affiche le
/// message du Bridge sans le réécrire.
class TradeActions {
  const TradeActions(this._api);

  final ApiClient _api;

  /// Fermeture totale : corps vide, conformément au contrat.
  Future<void> closeFully(int ticket) async {
    await _api.postJson(Endpoints.positionClose(ticket), body: <String, dynamic>{});
  }

  Future<void> closePercentage(int ticket, double percentage) async {
    await _api.postJson(
      Endpoints.positionClose(ticket),
      body: <String, dynamic>{'percentage': percentage},
    );
  }

  Future<void> closeVolume(int ticket, double volume) async {
    await _api.postJson(
      Endpoints.positionClose(ticket),
      body: <String, dynamic>{'volume': volume},
    );
  }

  Future<void> modifyStopLoss(int ticket, double stopLoss) async {
    await _api.postJson(
      Endpoints.positionModify(ticket),
      body: <String, dynamic>{'stopLoss': stopLoss},
    );
  }

  Future<void> modifyTakeProfit(int ticket, double takeProfit) async {
    await _api.postJson(
      Endpoints.positionModify(ticket),
      body: <String, dynamic>{'takeProfit': takeProfit},
    );
  }

  Future<void> breakEven(int ticket, int offsetPoints) async {
    await _api.postJson(
      Endpoints.positionBreakEven(ticket),
      body: <String, dynamic>{'offsetPoints': offsetPoints},
    );
  }

  Future<void> cancelOrder(int ticket) async {
    await _api.postJson(Endpoints.orderCancel(ticket));
  }
}

final AutoDisposeProvider<TradeActions> tradeActionsProvider =
    Provider.autoDispose<TradeActions>(
  (Ref<Object?> ref) => TradeActions(ref.watch(apiClientProvider)),
);
