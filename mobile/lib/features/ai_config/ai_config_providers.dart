import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api/api_client.dart';
import '../../core/api/api_exception.dart';
import '../../core/api/endpoints.dart';
import '../../core/connection/connection_controller.dart';
import 'models/ai_settings.dart';
import 'models/ai_status.dart';
import 'models/json_read.dart';

/// Appels d'écriture et de test de l'intelligence hybride.
///
/// Aucune de ces routes ne déclenche d'ordre : elles configurent le routage et
/// testent les connexions. Les messages d'erreur du Bridge sont remontés tels
/// quels, sans reformulation.
class AiConfigActions {
  const AiConfigActions(this._api);

  final ApiClient _api;

  Future<AiSettings> updateSettings(Map<String, dynamic> changes) async {
    final Map<String, dynamic> payload = await _api.putJson(
      Endpoints.aiRouterSettings,
      body: changes,
    );
    return AiSettings.fromJson(payload);
  }

  Future<AiTestResult> testOpenRouter() async {
    return AiTestResult.fromJson(await _api.postJson(Endpoints.aiOpenRouterTest));
  }
}

final AutoDisposeProvider<AiConfigActions> aiConfigActionsProvider =
    Provider.autoDispose<AiConfigActions>(
  (Ref ref) => AiConfigActions(ref.watch(apiClientProvider)),
);

/// `GET /ai/status` : état des deux moteurs, du routeur et du consensus.
final AutoDisposeFutureProvider<AiStatus> aiStatusProvider =
    FutureProvider.autoDispose<AiStatus>((Ref ref) async {
  return AiStatus.fromJson(await ref.watch(apiClientProvider).getJson(Endpoints.aiStatus));
});

/// `GET /ai/metrics` : fiabilité mesurée, par moteur et par type de tâche.
final AutoDisposeFutureProvider<List<AiMetricRow>> aiMetricsProvider =
    FutureProvider.autoDispose<List<AiMetricRow>>((Ref ref) async {
  final Map<String, dynamic> payload =
      await ref.watch(apiClientProvider).getJson(Endpoints.aiMetrics);
  return readMapList(payload['items']).map(AiMetricRow.fromJson).toList(growable: false);
});

/// `GET /ai/openrouter/models` : modèles gratuits et modèle actif.
final AutoDisposeFutureProvider<AiOpenRouterModels> aiOpenRouterModelsProvider =
    FutureProvider.autoDispose<AiOpenRouterModels>((Ref ref) async {
  return AiOpenRouterModels.fromJson(
    await ref.watch(apiClientProvider).getJson(Endpoints.aiOpenRouterModels),
  );
});

/// Brouillon des réglages IA : ce que l'utilisateur a modifié, et ce que le
/// Bridge a réellement enregistré.
@immutable
class AiConfigState {
  const AiConfigState({
    this.draft,
    this.saved,
    this.loading = true,
    this.saving = false,
    this.error,
    this.technical,
  });

  final AiSettings? draft;
  final AiSettings? saved;
  final bool loading;
  final bool saving;
  final String? error;
  final String? technical;

  bool get dirty {
    final AiSettings? current = draft;
    final AiSettings? reference = saved;
    if (current == null || reference == null) return false;
    return current.changesFrom(reference).isNotEmpty;
  }

  AiConfigState copyWith({
    AiSettings? draft,
    AiSettings? saved,
    bool? loading,
    bool? saving,
    String? error,
    String? technical,
    bool clearError = false,
  }) {
    return AiConfigState(
      draft: draft ?? this.draft,
      saved: saved ?? this.saved,
      loading: loading ?? this.loading,
      saving: saving ?? this.saving,
      error: clearError ? null : (error ?? this.error),
      technical: clearError ? null : (technical ?? this.technical),
    );
  }
}

/// Charge, modifie et enregistre les réglages IA.
///
/// Seuls les champs réellement changés sont envoyés : `PUT /ai/router/settings`
/// accepte une modification partielle et refuse un corps vide.
class AiConfigController extends StateNotifier<AiConfigState> {
  AiConfigController(this._api, this._actions) : super(const AiConfigState()) {
    load();
  }

  final ApiClient _api;
  final AiConfigActions _actions;

  Future<void> load() async {
    state = state.copyWith(loading: true, clearError: true);
    try {
      final Map<String, dynamic> payload = await _api.getJson(Endpoints.aiRouterSettings);
      final AiSettings settings = AiSettings.fromJson(payload);
      state = AiConfigState(draft: settings, saved: settings, loading: false);
    } on ApiException catch (error) {
      state = AiConfigState(
        draft: state.draft,
        saved: state.saved,
        loading: false,
        error: error.message,
        technical: error.technical,
      );
    }
  }

  /// Modifie le brouillon. Rien n'est envoyé au Bridge avant `save()`.
  void edit(AiSettings Function(AiSettings current) change) {
    final AiSettings? current = state.draft;
    if (current == null) return;
    state = state.copyWith(draft: change(current), clearError: true);
  }

  /// Abandonne les modifications non enregistrées.
  void reset() {
    final AiSettings? reference = state.saved;
    if (reference == null) return;
    state = AiConfigState(draft: reference, saved: reference, loading: false);
  }

  /// Enregistre les modifications. Retourne `null` si tout s'est bien passé,
  /// sinon le message à afficher.
  Future<String?> save() async {
    final AiSettings? current = state.draft;
    final AiSettings? reference = state.saved;
    if (current == null || reference == null) return 'Réglages non chargés.';

    final String? invalid = current.validate();
    if (invalid != null) {
      state = state.copyWith(error: invalid);
      return invalid;
    }

    final Map<String, dynamic> changes = current.changesFrom(reference);
    if (changes.isEmpty) return null;

    state = state.copyWith(saving: true, clearError: true);
    try {
      final AiSettings applied = await _actions.updateSettings(changes);
      state = AiConfigState(draft: applied, saved: applied, loading: false);
      return null;
    } on ApiException catch (error) {
      state = state.copyWith(
        saving: false,
        error: error.message,
        technical: error.technical,
      );
      return error.message;
    }
  }
}

final StateNotifierProvider<AiConfigController, AiConfigState> aiConfigProvider =
    StateNotifierProvider<AiConfigController, AiConfigState>((Ref ref) {
  return AiConfigController(ref.watch(apiClientProvider), ref.watch(aiConfigActionsProvider));
});

/// Dernier test d'un moteur, conservé le temps de la visite de l'écran.
@immutable
class AiTestState {
  const AiTestState({this.running = false, this.result});

  final bool running;
  final AiTestResult? result;
}

/// Lance `POST /ai/openrouter/test`.
class AiTestController extends StateNotifier<Map<String, AiTestState>> {
  AiTestController(this._actions) : super(const <String, AiTestState>{});

  final AiConfigActions _actions;

  static const String openRouter = 'openrouter';

  Future<void> run(String target) async {
    if (state[target]?.running ?? false) return;
    state = <String, AiTestState>{...state, target: const AiTestState(running: true)};
    try {
      final AiTestResult result = await _actions.testOpenRouter();
      state = <String, AiTestState>{...state, target: AiTestState(result: result)};
    } on ApiException catch (error) {
      // Le message du Bridge est affiché tel quel : il dit pourquoi ça échoue.
      state = <String, AiTestState>{
        ...state,
        target: AiTestState(
          result: AiTestResult(ok: false, error: error.message, at: DateTime.now()),
        ),
      };
    }
  }
}

final StateNotifierProvider<AiTestController, Map<String, AiTestState>> aiTestProvider =
    StateNotifierProvider<AiTestController, Map<String, AiTestState>>((Ref ref) {
  return AiTestController(ref.watch(aiConfigActionsProvider));
});
