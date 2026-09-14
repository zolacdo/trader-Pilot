import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api/api_client.dart';
import '../../core/api/endpoints.dart';
import '../../core/connection/connection_controller.dart';

/// Phrase exacte exigée par le Bridge pour toute action liée au compte réel.
const String liveConfirmationPhrase = 'JE COMPRENDS LES RISQUES';

/// Version de l'application mobile, alignée sur `pubspec.yaml`.
const String mobileAppVersion = '1.0.0';

/// État OpenRouter (clé, modèles, dernier test).
final AutoDisposeFutureProvider<Map<String, dynamic>> openrouterStatusProvider =
    FutureProvider.autoDispose<Map<String, dynamic>>((Ref<Object?> ref) {
  return ref.watch(apiClientProvider).getJson(Endpoints.openrouterStatus);
});

/// Modèles gratuits proposés par OpenRouter.
final AutoDisposeFutureProvider<Map<String, dynamic>> openrouterModelsProvider =
    FutureProvider.autoDispose<Map<String, dynamic>>((Ref<Object?> ref) {
  return ref.watch(apiClientProvider).getJson(Endpoints.openrouterModels);
});

/// Appareils appairés avec le Bridge.
final AutoDisposeFutureProvider<List<Map<String, dynamic>>> devicesProvider =
    FutureProvider.autoDispose<List<Map<String, dynamic>>>((Ref<Object?> ref) async {
  final List<dynamic> raw = await ref.watch(apiClientProvider).getList(Endpoints.devices);
  return raw
      .whereType<Map<dynamic, dynamic>>()
      .map(Map<String, dynamic>.from)
      .toList(growable: false);
});

/// Écritures déclenchées depuis les Paramètres.
///
/// Aucune de ces méthodes ne réécrit le message d'erreur du Bridge : c'est lui
/// qui explique pourquoi une action est refusée.
class SettingsActions {
  const SettingsActions(this._api);

  final ApiClient _api;

  // --- trading ---

  Future<void> setAutoTrading(bool enabled) async {
    await _api.postJson(Endpoints.tradingAuto, query: <String, dynamic>{'enabled': enabled});
  }

  Future<void> setExecutionMode(String mode, {String? confirmation}) async {
    await _api.postJson(
      Endpoints.tradingExecutionMode,
      body: <String, dynamic>{
        'mode': mode,
        if (confirmation != null) 'confirmation': confirmation,
      },
    );
  }

  Future<void> unlockLive() async {
    await _api.postJson(
      Endpoints.tradingLiveUnlock,
      body: <String, dynamic>{
        'confirmation': liveConfirmationPhrase,
        'acknowledgedRisks': true,
      },
    );
  }

  Future<void> lockLive() async {
    await _api.postJson(Endpoints.tradingLiveLock);
  }

  // --- OpenRouter ---

  Future<void> setOpenRouterKey(String? apiKey) async {
    await _api.putJson(
      Endpoints.openrouterKey,
      body: <String, dynamic>{'apiKey': apiKey},
    );
  }

  Future<void> setOpenRouterModels({
    required bool autoMode,
    String? textModel,
    String? visionModel,
  }) async {
    await _api.putJson(
      Endpoints.openrouterModels,
      body: <String, dynamic>{
        'autoMode': autoMode,
        'textModel': textModel,
        'visionModel': visionModel,
      },
    );
  }

  Future<Map<String, dynamic>> testOpenRouter() {
    return _api.postJson(Endpoints.openrouterTest);
  }

  // --- sauvegarde ---

  Future<Map<String, dynamic>> exportSettings() {
    return _api.getJson(Endpoints.settingsExport);
  }

  Future<Map<String, dynamic>> importSettings(Map<String, dynamic> payload) {
    return _api.postJson(
      Endpoints.settingsImport,
      body: <String, dynamic>{'payload': payload},
    );
  }

  // --- journal ---

  Future<Map<String, dynamic>> purgeJournal({int keepLast = 5000}) {
    return _api.deleteJson(Endpoints.journal, query: <String, dynamic>{'keepLast': keepLast});
  }
}

final AutoDisposeProvider<SettingsActions> settingsActionsProvider =
    Provider.autoDispose<SettingsActions>(
  (Ref<Object?> ref) => SettingsActions(ref.watch(apiClientProvider)),
);
