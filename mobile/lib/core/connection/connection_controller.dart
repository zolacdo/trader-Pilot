import 'dart:math';

import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../api/api_client.dart';
import '../api/api_exception.dart';
import '../api/endpoints.dart';
import '../api/ws_client.dart';
import '../security/secure_store.dart';

/// Etat de la liaison entre le telephone et le Bridge.
@immutable
class BridgeConnectionState {
  const BridgeConnectionState({
    this.baseUrl,
    this.fallbackUrl,
    this.paired = false,
    this.online = false,
    this.loading = true,
    this.error,
  });

  final String? baseUrl;
  final String? fallbackUrl;
  final bool paired;
  final bool online;
  final bool loading;
  final String? error;

  bool get configured => baseUrl != null && baseUrl!.isNotEmpty;

  /// Le Bridge est configure et appaire mais ne repond pas : l'application
  /// affiche clairement BRIDGE HORS LIGNE et ne pretend jamais avoir envoye
  /// un ordre (CDC section 40).
  bool get offline => configured && paired && !online;

  BridgeConnectionState copyWith({
    String? baseUrl,
    String? fallbackUrl,
    bool? paired,
    bool? online,
    bool? loading,
    String? error,
    bool clearError = false,
  }) {
    return BridgeConnectionState(
      baseUrl: baseUrl ?? this.baseUrl,
      fallbackUrl: fallbackUrl ?? this.fallbackUrl,
      paired: paired ?? this.paired,
      online: online ?? this.online,
      loading: loading ?? this.loading,
      error: clearError ? null : (error ?? this.error),
    );
  }
}

class ConnectionController extends StateNotifier<BridgeConnectionState> {
  ConnectionController({
    required ApiClient api,
    required WsClient ws,
    required SecureStore store,
  })  : _api = api,
        _ws = ws,
        _store = store,
        super(const BridgeConnectionState()) {
    _api.reachable.addListener(_onReachabilityChanged);
    _api.unauthorized.addListener(_onUnauthorized);
  }

  final ApiClient _api;
  final WsClient _ws;
  final SecureStore _store;

  String? _token;

  /// Recharge la configuration enregistree au lancement de l'application.
  Future<void> restore() async {
    state = state.copyWith(loading: true, clearError: true);
    final String? baseUrl = await _store.readBaseUrl();
    final String? fallback = await _store.readFallbackUrl();
    _token = await _store.readToken();

    if (baseUrl == null || baseUrl.isEmpty) {
      state = const BridgeConnectionState(loading: false);
      return;
    }

    _api.configure(baseUrl: baseUrl, token: _token);
    final bool online = await _reachAny(baseUrl, fallback);
    state = BridgeConnectionState(
      baseUrl: _api.baseUrl,
      fallbackUrl: fallback,
      paired: _token != null && _token!.isNotEmpty,
      online: online,
      loading: false,
    );
    if (state.paired && online) {
      _ws.connect(baseUrl: _api.baseUrl!, token: _token!);
    }
  }

  /// Essaie l'adresse principale puis l'adresse de repli locale.
  Future<bool> _reachAny(String primary, String? fallback) async {
    if (await _api.ping(baseUrl: primary)) {
      _api.configure(baseUrl: primary, token: _token);
      return true;
    }
    if (fallback != null && fallback.isNotEmpty && await _api.ping(baseUrl: fallback)) {
      _api.configure(baseUrl: fallback, token: _token);
      return true;
    }
    return false;
  }

  /// Teste une adresse saisie par l'utilisateur sans rien enregistrer.
  Future<bool> testAddress(String baseUrl) => _api.ping(baseUrl: baseUrl);

  Future<void> setBaseUrl(String baseUrl, {String? fallbackUrl}) async {
    await _store.writeBaseUrl(baseUrl);
    if (fallbackUrl != null) {
      await _store.writeFallbackUrl(fallbackUrl);
    }
    _api.configure(baseUrl: baseUrl, token: _token);
    final bool online = await _api.ping();
    state = state.copyWith(
      baseUrl: _api.baseUrl,
      fallbackUrl: fallbackUrl ?? state.fallbackUrl,
      online: online,
      loading: false,
      clearError: true,
    );
  }

  /// Appairage : echange le code affiche par le Bridge contre un jeton.
  Future<void> pair({required String baseUrl, required String code}) async {
    state = state.copyWith(loading: true, clearError: true);
    try {
      _api.configure(baseUrl: baseUrl, token: null);
      final String deviceId = await _deviceId();
      final Map<String, dynamic> response = await _api.postJson(
        Endpoints.pairing,
        authenticated: false,
        body: <String, dynamic>{
          'code': code.trim().toUpperCase(),
          'deviceId': deviceId,
          'name': 'Android',
          'platform': 'android',
        },
      );

      final String token = (response['token'] ?? '').toString();
      if (token.isEmpty) {
        throw const ApiException(message: 'Le Bridge n’a pas renvoyé de jeton.');
      }
      _token = token;
      _api.setToken(token);
      await _store.writeBaseUrl(_api.baseUrl!);
      await _store.writeToken(token);

      // Le Bridge indique son URL publique : on la garde comme adresse
      // principale et l'adresse saisie devient le repli local.
      final String? publicUrl = response['publicUrl']?.toString();
      if (publicUrl != null && publicUrl.isNotEmpty && publicUrl != _api.baseUrl) {
        await _store.writeFallbackUrl(_api.baseUrl);
        state = state.copyWith(fallbackUrl: _api.baseUrl);
      }

      state = state.copyWith(
        baseUrl: _api.baseUrl,
        paired: true,
        online: true,
        loading: false,
        clearError: true,
      );
      _ws.connect(baseUrl: _api.baseUrl!, token: token);
    } on ApiException catch (error) {
      state = state.copyWith(loading: false, error: error.message);
      rethrow;
    }
  }

  Future<void> unpair() async {
    _ws.disconnect();
    await _store.clearPairing();
    _token = null;
    _api.clear();
    state = state.copyWith(paired: false, online: false, loading: false);
  }

  /// Nouvelle tentative immediate apres une coupure.
  Future<bool> retry() async {
    final String? baseUrl = state.baseUrl;
    if (baseUrl == null) return false;
    final bool online = await _reachAny(baseUrl, state.fallbackUrl);
    state = state.copyWith(online: online);
    if (online && state.paired && _token != null) {
      _ws.retryNow();
    }
    return online;
  }

  Future<String> _deviceId() async {
    final String? existing = await _store.readDeviceId();
    if (existing != null && existing.isNotEmpty) return existing;
    final Random random = Random.secure();
    final String generated =
        'android-${List<int>.generate(8, (_) => random.nextInt(16)).map((v) => v.toRadixString(16)).join()}';
    await _store.writeDeviceId(generated);
    return generated;
  }

  void _onReachabilityChanged() {
    final bool value = _api.reachable.value;
    if (value != state.online) {
      state = state.copyWith(online: value);
      if (!value) {
        _ws.disconnect();
      } else if (state.paired && _token != null && _api.baseUrl != null) {
        _ws.connect(baseUrl: _api.baseUrl!, token: _token!);
      }
    }
  }

  void _onUnauthorized() {
    if (!_api.unauthorized.value) return;
    _ws.disconnect();
    state = state.copyWith(
      paired: false,
      error: 'Ce téléphone n’est plus autorisé par le Bridge. Refaites l’appairage.',
    );
  }

  @override
  void dispose() {
    _api.reachable.removeListener(_onReachabilityChanged);
    _api.unauthorized.removeListener(_onUnauthorized);
    super.dispose();
  }
}

// ---------------------------------------------------------------------------
// Fournisseurs
// ---------------------------------------------------------------------------

final Provider<SecureStore> secureStoreProvider = Provider<SecureStore>((ref) => const SecureStore());

final Provider<ApiClient> apiClientProvider = Provider<ApiClient>((ref) {
  final ApiClient client = ApiClient();
  ref.onDispose(client.clear);
  return client;
});

final Provider<WsClient> wsClientProvider = Provider<WsClient>((ref) {
  final WsClient client = WsClient();
  ref.onDispose(client.dispose);
  return client;
});

final StateNotifierProvider<ConnectionController, BridgeConnectionState> connectionProvider =
    StateNotifierProvider<ConnectionController, BridgeConnectionState>((ref) {
  return ConnectionController(
    api: ref.watch(apiClientProvider),
    ws: ref.watch(wsClientProvider),
    store: ref.watch(secureStoreProvider),
  );
});

/// Flux brut des evenements temps reel.
final StreamProvider<BridgeEvent> bridgeEventsProvider = StreamProvider<BridgeEvent>((ref) {
  return ref.watch(wsClientProvider).events;
});
