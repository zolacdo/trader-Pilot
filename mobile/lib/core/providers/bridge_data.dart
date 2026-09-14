import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../api/api_client.dart';
import '../api/api_exception.dart';
import '../api/endpoints.dart';
import '../api/ws_client.dart';
import '../connection/connection_controller.dart';
import '../database/local_database.dart';

/// Base locale partagee par toute l'application.
final Provider<LocalDatabase> localDatabaseProvider = Provider<LocalDatabase>((ref) {
  final LocalDatabase database = LocalDatabase();
  ref.onDispose(database.close);
  return database;
});

/// Resultat d'une lecture : donnees fraiches ou instantane hors ligne.
class BridgeData<T> {
  const BridgeData({required this.value, this.stale = false, this.updatedAt});

  final T value;

  /// True quand la valeur vient du cache local et non du Bridge.
  final bool stale;
  final DateTime? updatedAt;
}

/// Lit une route du Bridge et conserve un instantane pour le mode hors ligne.
///
/// En cas de coupure, l'application affiche les dernieres donnees connues en
/// les marquant explicitement comme telles : elle ne pretend jamais que le
/// Bridge a repondu (CDC section 40).
Future<BridgeData<Map<String, dynamic>>> fetchWithCache(
  Ref ref, {
  required String path,
  required String cacheKey,
  Map<String, dynamic>? query,
}) async {
  final ApiClient api = ref.watch(apiClientProvider);
  final LocalDatabase database = ref.watch(localDatabaseProvider);
  try {
    final Map<String, dynamic> payload = await api.getJson(path, query: query);
    await database.putSnapshot(cacheKey, payload);
    return BridgeData<Map<String, dynamic>>(value: payload, updatedAt: DateTime.now());
  } on ApiException {
    final ({Map<String, dynamic> payload, DateTime updatedAt})? cached =
        await database.readSnapshot(cacheKey);
    if (cached != null) {
      return BridgeData<Map<String, dynamic>>(
        value: cached.payload,
        stale: true,
        updatedAt: cached.updatedAt,
      );
    }
    rethrow;
  }
}

/// Tableau de bord (accueil).
final FutureProvider<BridgeData<Map<String, dynamic>>> dashboardProvider =
    FutureProvider<BridgeData<Map<String, dynamic>>>((ref) {
  ref.watch(_dashboardRefreshProvider);
  return fetchWithCache(ref, path: Endpoints.dashboard, cacheKey: CacheKeys.dashboard);
});

/// Etat consolide des connexions.
final FutureProvider<BridgeData<Map<String, dynamic>>> statusProvider =
    FutureProvider<BridgeData<Map<String, dynamic>>>((ref) {
  ref.watch(_dashboardRefreshProvider);
  return fetchWithCache(ref, path: Endpoints.status, cacheKey: CacheKeys.status);
});

/// Reglages de risque.
final FutureProvider<Map<String, dynamic>> riskSettingsProvider =
    FutureProvider<Map<String, dynamic>>((ref) async {
  final BridgeData<Map<String, dynamic>> data = await fetchWithCache(
    ref,
    path: Endpoints.riskSettings,
    cacheKey: CacheKeys.riskSettings,
  );
  return data.value;
});

/// Etat du moteur de trading (auto, pause, mode d'execution).
final FutureProvider<Map<String, dynamic>> tradingStateProvider =
    FutureProvider<Map<String, dynamic>>((ref) async {
  ref.watch(_dashboardRefreshProvider);
  return ref.watch(apiClientProvider).getJson(Endpoints.tradingState);
});

/// Compteur interne : l'incrementer force un rafraichissement des ecrans.
final StateProvider<int> _dashboardRefreshProvider = StateProvider<int>((ref) => 0);

/// Invalide les ecrans principaux (apres une action ou un evenement temps reel).
void refreshBridgeData(WidgetRef ref) {
  ref.read(_dashboardRefreshProvider.notifier).state++;
  ref.invalidate(dashboardProvider);
  ref.invalidate(statusProvider);
  ref.invalidate(tradingStateProvider);
}

/// Rafraichit automatiquement l'accueil quand le Bridge pousse un evenement.
final Provider<void> liveRefreshProvider = Provider<void>((ref) {
  final WsClient ws = ref.watch(wsClientProvider);
  final Set<String> triggers = <String>{
    BridgeEvents.accountUpdated,
    BridgeEvents.pnlUpdated,
    BridgeEvents.positionOpened,
    BridgeEvents.positionClosed,
    BridgeEvents.positionUpdated,
    BridgeEvents.signalNew,
    BridgeEvents.signalUpdated,
    BridgeEvents.signalRejected,
    BridgeEvents.tradingState,
    BridgeEvents.mt5Status,
    BridgeEvents.telegramStatus,
  };
  final subscription = ws.on(triggers).listen((_) {
    ref.invalidate(dashboardProvider);
    ref.invalidate(statusProvider);
    ref.invalidate(tradingStateProvider);
  });
  ref.onDispose(subscription.cancel);
});
