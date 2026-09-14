import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_client.dart';
import '../../../core/api/api_exception.dart';
import '../../../core/api/endpoints.dart';
import '../../../core/connection/connection_controller.dart';
import '../../bridge/models/bridge_json.dart';

/// État de la configuration guidée, tel que le Bridge le calcule.
final FutureProvider<Map<String, dynamic>> onboardingStateProvider =
    FutureProvider<Map<String, dynamic>>((Ref ref) {
  return ref.watch(apiClientProvider).getJson(Endpoints.onboardingState);
});

/// État OpenRouter : clé masquée, modèles gratuits actifs, dernier test.
final FutureProvider<Map<String, dynamic>> openrouterStatusProvider =
    FutureProvider<Map<String, dynamic>>((Ref ref) {
  return ref.watch(apiClientProvider).getJson(Endpoints.openrouterStatus);
});

/// Étape de la connexion Telegram réellement en cours.
enum TelegramLoginPhase {
  /// Rien n'a encore été envoyé.
  idle,

  /// Le code a été envoyé par Telegram et doit être saisi.
  awaitingCode,

  /// La vérification en deux étapes réclame le mot de passe.
  awaitingPassword,

  /// Le compte est connecté.
  connected,
}

/// Avancement de la connexion Telegram.
///
/// Ni l'api_id, ni l'api_hash, ni le code, ni le mot de passe 2FA ne sont
/// conservés ici : ils traversent l'application et restent sur le Bridge.
@immutable
class TelegramLoginState {
  const TelegramLoginState({
    this.phase = TelegramLoginPhase.idle,
    this.requestId,
    this.busy = false,
    this.error,
    this.technical,
    this.account,
  });

  final TelegramLoginPhase phase;

  /// Identifiant opaque de la demande, renvoyé par le Bridge.
  final String? requestId;
  final bool busy;
  final String? error;
  final String? technical;

  /// Libellé du compte connecté, par exemple `@pseudo`.
  final String? account;

  TelegramLoginState copyWith({
    TelegramLoginPhase? phase,
    String? requestId,
    bool? busy,
    String? error,
    String? technical,
    String? account,
    bool clearError = false,
  }) {
    return TelegramLoginState(
      phase: phase ?? this.phase,
      requestId: requestId ?? this.requestId,
      busy: busy ?? this.busy,
      error: clearError ? null : (error ?? this.error),
      technical: clearError ? null : (technical ?? this.technical),
      account: account ?? this.account,
    );
  }
}

/// Pilote la connexion Telegram en trois appels : envoi du code, validation
/// du code, puis mot de passe 2FA si le compte en possède un.
class TelegramLoginController extends StateNotifier<TelegramLoginState> {
  TelegramLoginController(this._api) : super(const TelegramLoginState());

  final ApiClient _api;

  void reset() => state = const TelegramLoginState();

  Future<void> start({
    required String apiId,
    required String apiHash,
    required String phone,
  }) async {
    // Un champ laissé vide n'est pas envoyé : le Bridge reprend alors la valeur
    // de son fichier .env. Seul ce qui est saisi ici est validé.
    final int? identifier = int.tryParse(apiId.trim());
    if (apiId.trim().isNotEmpty && (identifier == null || identifier <= 0)) {
      state = state.copyWith(error: 'L\'API ID est un nombre, visible sur my.telegram.org.');
      return;
    }
    if (apiHash.trim().isNotEmpty && apiHash.trim().length < 8) {
      state = state.copyWith(error: 'L\'API Hash semble incomplet.');
      return;
    }
    if (phone.trim().isNotEmpty && phone.trim().length < 6) {
      state = state.copyWith(error: 'Saisissez le numéro au format international, ex. +33612345678.');
      return;
    }
    // Le Bridge complète avec son .env et renvoie lui-même un message précis
    // s'il manque encore quelque chose : inutile de dupliquer ce contrôle ici.
    final Map<String, dynamic> body = <String, dynamic>{
      if (identifier != null) 'apiId': identifier,
      if (apiHash.trim().isNotEmpty) 'apiHash': apiHash.trim(),
      if (phone.trim().isNotEmpty) 'phone': phone.trim(),
    };

    await _send(
      () => _api.postJson(Endpoints.telegramLoginStart, body: body),
      onSuccess: (Map<String, dynamic> result) {
        final String? requestId = Json.text(result['phoneCodeHash']);
        if (requestId == null) {
          state = state.copyWith(
            busy: false,
            error: 'Le Bridge n\'a pas renvoyé d\'identifiant de demande.',
          );
          return;
        }
        state = TelegramLoginState(
          phase: TelegramLoginPhase.awaitingCode,
          requestId: requestId,
        );
      },
    );
  }

  Future<void> submitCode(String code) async {
    final String? requestId = state.requestId;
    if (requestId == null || code.trim().length < 3) return;
    await _send(
      () => _api.postJson(
        Endpoints.telegramLoginCode,
        body: <String, dynamic>{'requestId': requestId, 'code': code.trim()},
      ),
      onSuccess: _applyLoginResult,
    );
  }

  Future<void> submitPassword(String password) async {
    final String? requestId = state.requestId;
    if (requestId == null || password.isEmpty) return;
    await _send(
      () => _api.postJson(
        Endpoints.telegramLogin2fa,
        body: <String, dynamic>{'requestId': requestId, 'password': password},
      ),
      onSuccess: _applyLoginResult,
    );
  }

  void _applyLoginResult(Map<String, dynamic> result) {
    final String? status = Json.text(result['status']);
    if (status == 'password_required') {
      state = state.copyWith(phase: TelegramLoginPhase.awaitingPassword, busy: false);
      return;
    }
    if (status == 'connected') {
      final Map<String, dynamic> user = Json.map(result['user']);
      final String? username = Json.text(user['username']);
      state = state.copyWith(
        phase: TelegramLoginPhase.connected,
        busy: false,
        account: username == null ? Json.text(user['firstName']) ?? 'Compte connecté' : '@$username',
        clearError: true,
      );
      return;
    }
    state = state.copyWith(
      busy: false,
      error: 'Réponse inattendue du Bridge : $status',
    );
  }

  Future<void> _send(
    Future<Map<String, dynamic>> Function() request, {
    required void Function(Map<String, dynamic>) onSuccess,
  }) async {
    state = state.copyWith(busy: true, clearError: true);
    try {
      onSuccess(await request());
    } on ApiException catch (error) {
      state = state.copyWith(busy: false, error: error.message, technical: error.technical);
    }
  }
}

final StateNotifierProvider<TelegramLoginController, TelegramLoginState> telegramLoginProvider =
    StateNotifierProvider<TelegramLoginController, TelegramLoginState>(
  (Ref ref) => TelegramLoginController(ref.watch(apiClientProvider)),
);
