import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_client.dart';
import '../../../core/api/api_exception.dart';
import '../../../core/api/endpoints.dart';
import '../../../core/api/ws_client.dart';
import '../../../core/connection/connection_controller.dart';
import '../models/json_read.dart';
import '../models/signal.dart';

/// Regroupements de statuts acceptés par `GET /signals?group=`.
abstract final class SignalGroups {
  static const String accepted = 'accepted';
  static const String executed = 'executed';
  static const String rejected = 'rejected';
  static const String error = 'error';
  static const String review = 'review';
  static const String observed = 'observed';
}

/// Filtres de la page Signaux (CDC section 33).
@immutable
class SignalFilters {
  const SignalFilters({
    this.group,
    this.today = false,
    this.channelId,
    this.symbol,
    this.direction,
  });

  /// `accepted`, `executed`, `rejected`, `error`, `review` ou `observed`.
  final String? group;
  final bool today;
  final int? channelId;
  final String? symbol;
  final String? direction;

  bool get isDefault =>
      group == null && !today && channelId == null && symbol == null && direction == null;

  SignalFilters copyWith({
    String? group,
    bool? today,
    int? channelId,
    String? symbol,
    String? direction,
    bool clearGroup = false,
    bool clearChannel = false,
    bool clearSymbol = false,
    bool clearDirection = false,
  }) {
    return SignalFilters(
      group: clearGroup ? null : (group ?? this.group),
      today: today ?? this.today,
      channelId: clearChannel ? null : (channelId ?? this.channelId),
      symbol: clearSymbol ? null : (symbol ?? this.symbol),
      direction: clearDirection ? null : (direction ?? this.direction),
    );
  }

  Map<String, dynamic> toQuery() {
    return <String, dynamic>{
      if (group != null) 'group': group,
      if (today) 'today': true,
      if (channelId != null) 'channelId': channelId,
      if (symbol != null) 'symbol': symbol,
      if (direction != null) 'direction': direction,
    };
  }

  @override
  bool operator ==(Object other) {
    return other is SignalFilters &&
        other.group == group &&
        other.today == today &&
        other.channelId == channelId &&
        other.symbol == symbol &&
        other.direction == direction;
  }

  @override
  int get hashCode => Object.hash(group, today, channelId, symbol, direction);
}

final StateProvider<SignalFilters> signalFiltersProvider =
    StateProvider<SignalFilters>((Ref ref) => const SignalFilters());

/// Compteur de rafraîchissement des signaux.
final StateProvider<int> signalsRefreshProvider = StateProvider<int>((Ref ref) => 0);

/// Page courante de la liste, chargée par blocs successifs.
@immutable
class SignalsPage {
  const SignalsPage({
    required this.items,
    required this.hasMore,
    this.loadingMore = false,
    this.loadMoreError,
  });

  final List<Signal> items;
  final bool hasMore;
  final bool loadingMore;
  final String? loadMoreError;

  SignalsPage copyWith({
    List<Signal>? items,
    bool? hasMore,
    bool? loadingMore,
    String? loadMoreError,
    bool clearError = false,
  }) {
    return SignalsPage(
      items: items ?? this.items,
      hasMore: hasMore ?? this.hasMore,
      loadingMore: loadingMore ?? this.loadingMore,
      loadMoreError: clearError ? null : (loadMoreError ?? this.loadMoreError),
    );
  }
}

/// Liste paginée des signaux (`GET /api/v1/signals`).
class SignalsFeed extends AutoDisposeAsyncNotifier<SignalsPage> {
  static const int pageSize = 30;

  bool _busy = false;

  @override
  Future<SignalsPage> build() async {
    ref.watch(signalsRefreshProvider);
    final SignalFilters filters = ref.watch(signalFiltersProvider);
    final List<Signal> items = await _fetch(filters, 0);
    return SignalsPage(items: items, hasMore: items.length >= pageSize);
  }

  Future<List<Signal>> _fetch(SignalFilters filters, int offset) async {
    final ApiClient api = ref.read(apiClientProvider);
    final Map<String, dynamic> payload = await api.getJson(
      Endpoints.signals,
      query: <String, dynamic>{...filters.toQuery(), 'limit': pageSize, 'offset': offset},
    );
    return readMapList(payload['items']).map(Signal.fromJson).toList(growable: false);
  }

  /// Charge le bloc suivant quand l'utilisateur atteint le bas de la liste.
  Future<void> loadMore() async {
    final SignalsPage? current = state.valueOrNull;
    if (_busy || current == null || !current.hasMore) return;
    _busy = true;
    state = AsyncValue<SignalsPage>.data(
      current.copyWith(loadingMore: true, clearError: true),
    );
    try {
      final List<Signal> next =
          await _fetch(ref.read(signalFiltersProvider), current.items.length);
      state = AsyncValue<SignalsPage>.data(
        SignalsPage(
          items: <Signal>[...current.items, ...next],
          hasMore: next.length >= pageSize,
        ),
      );
    } on ApiException catch (error) {
      state = AsyncValue<SignalsPage>.data(
        current.copyWith(loadingMore: false, loadMoreError: error.message),
      );
    } finally {
      _busy = false;
    }
  }
}

final AutoDisposeAsyncNotifierProvider<SignalsFeed, SignalsPage> signalsFeedProvider =
    AsyncNotifierProvider.autoDispose<SignalsFeed, SignalsPage>(SignalsFeed.new);

/// Signaux en attente de validation manuelle (`GET /api/v1/signals/pending`).
final AutoDisposeFutureProvider<List<Signal>> pendingSignalsProvider =
    FutureProvider.autoDispose<List<Signal>>((Ref ref) async {
  ref.watch(signalsRefreshProvider);
  final ApiClient api = ref.watch(apiClientProvider);
  final List<dynamic> raw = await api.getList(Endpoints.signalsPending);
  return raw.map(readMap).map(Signal.fromJson).toList(growable: false);
});

/// Détail complet d'un signal (`GET /api/v1/signals/{id}`).
final AutoDisposeFutureProviderFamily<SignalDetail, int> signalDetailProvider =
    FutureProvider.autoDispose.family<SignalDetail, int>((Ref ref, int id) async {
  ref.watch(signalsRefreshProvider);
  final ApiClient api = ref.watch(apiClientProvider);
  return SignalDetail.fromJson(await api.getJson(Endpoints.signal(id)));
});

/// Horloge à la seconde : sert aux comptes à rebours de validation manuelle.
final AutoDisposeStreamProvider<DateTime> tickProvider =
    StreamProvider.autoDispose<DateTime>((Ref ref) {
  return Stream<DateTime>.periodic(const Duration(seconds: 1), (_) => DateTime.now());
});

/// Validation manuelle d'un signal (CDC section 51).
class SignalActions {
  const SignalActions(this._ref);

  final Ref _ref;

  void _refresh() => _ref.read(signalsRefreshProvider.notifier).state++;

  /// Exécute le signal. Le RiskManager du Bridge s'applique intégralement.
  Future<Map<String, dynamic>> approve(int signalId) async {
    final Map<String, dynamic> outcome =
        await _ref.read(apiClientProvider).postJson(Endpoints.signalApprove(signalId));
    _refresh();
    return outcome;
  }

  Future<Map<String, dynamic>> reject(int signalId, String reason) async {
    final Map<String, dynamic> outcome = await _ref.read(apiClientProvider).postJson(
          Endpoints.signalReject(signalId),
          body: <String, dynamic>{'reason': reason},
        );
    _refresh();
    return outcome;
  }
}

final Provider<SignalActions> signalActionsProvider = Provider<SignalActions>(SignalActions.new);

/// Recharge les signaux à chaque événement temps réel du Bridge.
final AutoDisposeProvider<void> signalsLiveProvider = Provider.autoDispose<void>((Ref ref) {
  final WsClient ws = ref.watch(wsClientProvider);
  final StreamSubscription<BridgeEvent> subscription = ws.on(<String>{
    BridgeEvents.signalNew,
    BridgeEvents.signalUpdated,
    BridgeEvents.signalRejected,
    BridgeEvents.signalNeedsReview,
  }).listen((_) => ref.read(signalsRefreshProvider.notifier).state++);
  ref.onDispose(subscription.cancel);
});
