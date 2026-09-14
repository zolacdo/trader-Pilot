import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_client.dart';
import '../../../core/api/endpoints.dart';
import '../../../core/api/ws_client.dart';
import '../../../core/connection/connection_controller.dart';
import '../models/channel.dart';
import '../models/discovery.dart';
import '../models/json_read.dart';

/// Compteur de rafraîchissement : l'incrémenter recharge les écrans de canaux.
final StateProvider<int> channelsRefreshProvider = StateProvider<int>((Ref ref) => 0);

/// Canaux surveillés (`GET /api/v1/channels`).
final FutureProvider<List<Channel>> channelsProvider =
    FutureProvider<List<Channel>>((Ref ref) async {
  ref.watch(channelsRefreshProvider);
  final ApiClient api = ref.watch(apiClientProvider);
  final List<dynamic> raw = await api.getList(Endpoints.channels);
  return raw.map(readMap).map(Channel.fromJson).toList(growable: false);
});

/// Détail d'un canal (`GET /api/v1/channels/{id}`).
final FutureProviderFamily<ChannelDetail, int> channelDetailProvider =
    FutureProvider.family<ChannelDetail, int>((Ref ref, int id) async {
  ref.watch(channelsRefreshProvider);
  final ApiClient api = ref.watch(apiClientProvider);
  return ChannelDetail.fromJson(await api.getJson(Endpoints.channel(id)));
});

/// Tableau de comparaison (`GET /api/v1/channels/compare/table`).
final AutoDisposeFutureProvider<CompareTable> channelCompareProvider =
    FutureProvider.autoDispose<CompareTable>((Ref ref) async {
  ref.watch(channelsRefreshProvider);
  final ApiClient api = ref.watch(apiClientProvider);
  return CompareTable.fromJson(await api.getJson(Endpoints.channelsCompare));
});

/// Suggestions de recherche proposées par le Bridge.
final AutoDisposeFutureProvider<List<String>> discoverSuggestionsProvider =
    FutureProvider.autoDispose<List<String>>((Ref ref) async {
  final ApiClient api = ref.watch(apiClientProvider);
  final Map<String, dynamic> payload = await api.getJson(Endpoints.telegramSuggestions);
  return readTextList(payload['suggestions']);
});

/// Requête de recherche saisie ou choisie par l'utilisateur.
final AutoDisposeStateProvider<String> discoverQueryProvider =
    StateProvider.autoDispose<String>((Ref ref) => '');

/// Résultats de recherche. `null` tant qu'aucune recherche n'a été lancée.
final AutoDisposeFutureProvider<DiscoveryResults?> discoverResultsProvider =
    FutureProvider.autoDispose<DiscoveryResults?>((Ref ref) async {
  final String query = ref.watch(discoverQueryProvider).trim();
  if (query.length < 2) return null;
  final ApiClient api = ref.watch(apiClientProvider);
  final Map<String, dynamic> payload = await api.postJson(
    Endpoints.telegramDiscover,
    body: <String, dynamic>{'query': query, 'limit': 30},
  );
  return DiscoveryResults.fromJson(payload);
});

/// Actions serveur sur les canaux. Aucune n'est déclenchée automatiquement.
class ChannelActions {
  const ChannelActions(this._ref);

  final Ref _ref;

  ApiClient get _api => _ref.read(apiClientProvider);

  void _refresh() => _ref.read(channelsRefreshProvider.notifier).state++;

  /// Modifie les réglages d'un canal. Seules les clés fournies sont envoyées.
  Future<ChannelSettings> updateSettings(int channelId, Map<String, dynamic> changes) async {
    final Map<String, dynamic> payload =
        await _api.patchJson(Endpoints.channelSettings(channelId), body: changes);
    _refresh();
    return ChannelSettings.fromJson(payload);
  }

  Future<void> setMonitoring(int channelId, bool enabled) async {
    await _api.postJson(
      Endpoints.channelMonitor(channelId),
      query: <String, dynamic>{'enabled': enabled},
    );
    _refresh();
  }

  /// Lance l'analyse des N derniers messages accessibles du canal.
  Future<ChannelAnalysis> analyze(
    int channelId, {
    required int messages,
    required bool backtest,
  }) async {
    final Map<String, dynamic> payload = await _api.postJson(
      Endpoints.channelAnalyze(channelId),
      body: <String, dynamic>{'messages': messages, 'backtest': backtest},
    );
    _refresh();
    return ChannelAnalysis.fromJson(payload);
  }

  /// Ajoute un canal à la surveillance. Il démarre toujours en mode OBSERVE.
  ///
  /// `join` reste faux par défaut : rejoindre le canal avec le compte Telegram
  /// de l'utilisateur est une action explicite, jamais implicite.
  /// [username] est transmis quand il existe : le Bridge le préfère à
  /// l'identifiant numérique, que Telegram ne sait plus résoudre après un
  /// redémarrage tant que le canal n'a pas été revu.
  Future<Channel> addChannel({
    required int telegramId,
    required bool join,
    String? username,
  }) async {
    final Map<String, dynamic> payload = await _api.postJson(
      Endpoints.channels,
      body: <String, dynamic>{
        'telegramId': telegramId,
        if (username != null && username.isNotEmpty) 'username': username,
        'join': join,
      },
    );
    _refresh();
    return Channel.fromJson(payload);
  }
}

final Provider<ChannelActions> channelActionsProvider =
    Provider<ChannelActions>(ChannelActions.new);

/// Recharge les canaux quand le Bridge signale une modification.
final AutoDisposeProvider<void> channelsLiveProvider = Provider.autoDispose<void>((Ref ref) {
  final WsClient ws = ref.watch(wsClientProvider);
  final StreamSubscription<BridgeEvent> subscription = ws
      .on(<String>{BridgeEvents.channelUpdated, BridgeEvents.channelAnalysis})
      .listen((_) => ref.read(channelsRefreshProvider.notifier).state++);
  ref.onDispose(subscription.cancel);
});
