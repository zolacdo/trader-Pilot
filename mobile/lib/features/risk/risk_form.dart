import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api/api_client.dart';
import '../../core/api/api_exception.dart';
import '../../core/api/endpoints.dart';
import '../../core/connection/connection_controller.dart';
import '../../core/providers/bridge_data.dart';

// ---------------------------------------------------------------------------
// Conversions défensives
// ---------------------------------------------------------------------------

double? riskDouble(Object? raw) {
  if (raw is num) return raw.toDouble();
  if (raw is String) return double.tryParse(raw.replaceAll(',', '.'));
  return null;
}

int? riskInt(Object? raw) {
  if (raw is num) return raw.toInt();
  if (raw is String) return int.tryParse(raw);
  return null;
}

/// Brouillon du formulaire de risque.
///
/// [original] est ce que le Bridge a renvoyé, [changes] uniquement ce que
/// l'utilisateur a modifié : c'est exactement ce corps qui part en PATCH.
class RiskDraft {
  const RiskDraft({
    required this.original,
    this.changes = const <String, Object?>{},
    this.saving = false,
    this.revision = 0,
  });

  final Map<String, dynamic> original;
  final Map<String, Object?> changes;
  final bool saving;

  /// Incrémentée à chaque rechargement : force la reconstruction des champs.
  final int revision;

  bool get dirty => changes.isNotEmpty;

  Object? value(String key) => changes.containsKey(key) ? changes[key] : original[key];

  double? number(String key) => riskDouble(value(key));

  int? integer(String key) => riskInt(value(key));

  bool boolean(String key, {bool fallback = false}) {
    final Object? raw = value(key);
    return raw is bool ? raw : fallback;
  }

  String? text(String key) {
    final Object? raw = value(key);
    if (raw == null) return null;
    final String result = raw.toString().trim();
    return result.isEmpty ? null : result;
  }

  List<double> doubles(String key) {
    final Object? raw = value(key);
    if (raw is! List) return const <double>[];
    return raw.map(riskDouble).whereType<double>().toList(growable: false);
  }

  List<int> integers(String key) {
    final Object? raw = value(key);
    if (raw is! List) return const <int>[];
    return raw.map(riskInt).whereType<int>().toList(growable: false);
  }

  List<String> strings(String key) {
    final Object? raw = value(key);
    if (raw is! List) return const <String>[];
    return raw.map((Object? item) => item.toString()).toList(growable: false);
  }

  RiskDraft copyWith({Map<String, Object?>? changes, bool? saving}) {
    return RiskDraft(
      original: original,
      changes: changes ?? this.changes,
      saving: saving ?? this.saving,
      revision: revision,
    );
  }
}

/// Charge, modifie et enregistre les réglages de risque.
class RiskFormController extends StateNotifier<AsyncValue<RiskDraft>> {
  RiskFormController(this._api) : super(const AsyncValue<RiskDraft>.loading()) {
    load();
  }

  final ApiClient _api;

  Future<void> load() async {
    state = const AsyncValue<RiskDraft>.loading();
    try {
      final Map<String, dynamic> payload = await _api.getJson(Endpoints.riskSettings);
      if (!mounted) return;
      state = AsyncValue<RiskDraft>.data(RiskDraft(original: payload));
    } on ApiException catch (error, stack) {
      if (!mounted) return;
      state = AsyncValue<RiskDraft>.error(error, stack);
    }
  }

  /// Enregistre une valeur modifiée. Revenir à la valeur d'origine — ou vider
  /// le champ — retire simplement le champ du corps envoyé au Bridge : la
  /// valeur enregistrée côté Bridge reste alors inchangée.
  void set(String key, Object? newValue) {
    final RiskDraft? draft = state.valueOrNull;
    if (draft == null) return;
    final Map<String, Object?> changes = Map<String, Object?>.from(draft.changes);
    if (newValue == null || _sameAsOriginal(draft.original[key], newValue)) {
      changes.remove(key);
    } else {
      changes[key] = newValue;
    }
    state = AsyncValue<RiskDraft>.data(draft.copyWith(changes: changes));
  }

  void discard() {
    final RiskDraft? draft = state.valueOrNull;
    if (draft == null) return;
    state = AsyncValue<RiskDraft>.data(
      RiskDraft(original: draft.original, revision: draft.revision + 1),
    );
  }

  /// Envoie uniquement les champs modifiés. Retourne le message d'erreur du
  /// Bridge (par exemple une validation 422) ou `null` en cas de succès.
  Future<String?> save() async {
    final RiskDraft? draft = state.valueOrNull;
    if (draft == null || !draft.dirty) return null;
    state = AsyncValue<RiskDraft>.data(draft.copyWith(saving: true));
    try {
      final Map<String, dynamic> updated =
          await _api.patchJson(Endpoints.riskSettings, body: draft.changes);
      if (!mounted) return null;
      state = AsyncValue<RiskDraft>.data(
        RiskDraft(original: updated, revision: draft.revision + 1),
      );
      return null;
    } on ApiException catch (error) {
      if (!mounted) return error.message;
      state = AsyncValue<RiskDraft>.data(draft.copyWith(saving: false));
      return error.message;
    }
  }

  static bool _sameAsOriginal(Object? original, Object? updated) {
    if (original is num && updated is num) return original.toDouble() == updated.toDouble();
    if (original is List && updated is List) {
      if (original.length != updated.length) return false;
      for (int i = 0; i < original.length; i++) {
        if (original[i].toString() != updated[i].toString()) return false;
      }
      return true;
    }
    return original == updated;
  }
}

final AutoDisposeStateNotifierProvider<RiskFormController, AsyncValue<RiskDraft>> riskFormProvider =
    StateNotifierProvider.autoDispose<RiskFormController, AsyncValue<RiskDraft>>(
  (Ref<Object?> ref) => RiskFormController(ref.watch(apiClientProvider)),
);

/// Solde de référence utilisé pour chiffrer l'exemple de risque par trade.
class RiskReference {
  const RiskReference({this.balance, this.currency});

  final double? balance;
  final String? currency;
}

/// Lit le solde réel depuis le tableau de bord, sans jamais l'inventer.
final AutoDisposeProvider<RiskReference> riskReferenceProvider =
    Provider.autoDispose<RiskReference>((Ref<Object?> ref) {
  final Map<String, dynamic>? dashboard = ref.watch(dashboardProvider).valueOrNull?.value;
  final Object? metrics = dashboard?['metrics'];
  if (metrics is! Map) return const RiskReference();
  return RiskReference(
    balance: riskDouble(metrics['balance']),
    currency: metrics['currency']?.toString(),
  );
});
