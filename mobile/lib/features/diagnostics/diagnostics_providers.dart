import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api/api_client.dart';
import '../../core/api/api_exception.dart';
import '../../core/api/endpoints.dart';
import '../../core/connection/connection_controller.dart';

/// Cibles de test acceptées par `POST /api/v1/diagnostics/test/{target}`.
///
/// Aucune de ces cibles n'envoie d'ordre : ce sont uniquement des tests de
/// connexion (CDC section 60).
const List<({String target, String label, String hint})> diagnosticTests =
    <({String target, String label, String hint})>[
  (target: 'telegram', label: 'Tester Telegram', hint: 'Vérifie la session Telegram.'),
  (target: 'openrouter', label: 'Tester OpenRouter', hint: 'Interroge le modèle texte gratuit.'),
  (
    target: 'mt5',
    label: 'Tester MT5',
    hint: 'Lit l\'état du terminal et du compte, sans passer d\'ordre.'
  ),
  (target: 'websocket', label: 'Tester WebSocket', hint: 'Publie un message de test sur le bus.'),
  (target: 'notification', label: 'Tester notification', hint: 'Envoie une notification de test.'),
  (target: 'tunnel', label: 'Tester le tunnel', hint: 'Vérifie l\'accès distant ngrok.'),
];

/// Libellé accentué d'un mode d'exécution.
String diagnosticExecutionModeLabel(String? code) {
  return switch (code) {
    'PAPER' => 'Paper Trading (aucun ordre réel)',
    'MT5_DEMO' => 'MetaTrader 5 — compte démo',
    'MT5_LIVE' => 'MetaTrader 5 — compte réel',
    _ => code ?? '--',
  };
}

/// Résultat d'un test de diagnostic.
@immutable
class DiagnosticTestResult {
  const DiagnosticTestResult({this.running = false, this.ok, this.detail, this.at});

  final bool running;
  final bool? ok;
  final String? detail;
  final DateTime? at;
}

/// Lance les tests unitaires de connexion et conserve leur dernier résultat.
class DiagnosticTestsController extends StateNotifier<Map<String, DiagnosticTestResult>> {
  DiagnosticTestsController(this._api) : super(const <String, DiagnosticTestResult>{});

  final ApiClient _api;

  Future<void> run(String target) async {
    if (state[target]?.running ?? false) return;
    state = <String, DiagnosticTestResult>{
      ...state,
      target: const DiagnosticTestResult(running: true),
    };
    try {
      final Map<String, dynamic> payload = await _api.postJson(Endpoints.diagnosticTest(target));
      state = <String, DiagnosticTestResult>{
        ...state,
        target: DiagnosticTestResult(
          ok: payload['ok'] == true,
          detail: describeTestPayload(payload),
          at: DateTime.now(),
        ),
      };
    } on ApiException catch (error) {
      state = <String, DiagnosticTestResult>{
        ...state,
        target: DiagnosticTestResult(ok: false, detail: error.message, at: DateTime.now()),
      };
    }
  }
}

/// Résume la réponse d'un test sans en inventer le contenu.
String? describeTestPayload(Map<String, dynamic> payload) {
  final Object? detail = payload['detail'];
  if (detail is String && detail.trim().isNotEmpty) return detail.trim();
  final Object? error = payload['error'];
  if (error is String && error.trim().isNotEmpty) return error.trim();

  final List<String> parts = <String>[];
  final Object? model = payload['model'];
  if (model is String && model.isNotEmpty) parts.add('modèle $model');
  final Object? latency = payload['latencyMs'];
  if (latency is num) parts.add('${latency.round()} ms');
  final Object? subscribers = payload['subscribers'];
  if (subscribers is num) parts.add('${subscribers.round()} client(s) abonné(s)');
  final Object? publicUrl = payload['publicUrl'];
  if (publicUrl is String && publicUrl.isNotEmpty) parts.add(publicUrl);
  return parts.isEmpty ? null : parts.join(' · ');
}

final StateNotifierProvider<DiagnosticTestsController, Map<String, DiagnosticTestResult>>
    diagnosticTestsProvider =
    StateNotifierProvider<DiagnosticTestsController, Map<String, DiagnosticTestResult>>((Ref ref) {
  return DiagnosticTestsController(ref.watch(apiClientProvider));
});

/// `GET /api/v1/diagnostics`.
final AutoDisposeFutureProvider<Map<String, dynamic>> diagnosticsProvider =
    FutureProvider.autoDispose<Map<String, dynamic>>((Ref ref) {
  return ref.watch(apiClientProvider).getJson(Endpoints.diagnostics);
});

/// `GET /api/v1/go-live-checklist`.
final AutoDisposeFutureProvider<Map<String, dynamic>> goLiveChecklistProvider =
    FutureProvider.autoDispose<Map<String, dynamic>>((Ref ref) {
  return ref.watch(apiClientProvider).getJson(Endpoints.goLiveChecklist);
});

/// Lignes d'une réponse (`checks`, `items`).
List<Map<String, dynamic>> diagnosticRows(Map<String, dynamic> source, String key) {
  final Object? raw = source[key];
  if (raw is! List) return const <Map<String, dynamic>>[];
  return raw
      .whereType<Map<dynamic, dynamic>>()
      .map((Map<dynamic, dynamic> row) => Map<String, dynamic>.from(row))
      .toList(growable: false);
}

/// Textes d'une liste d'avertissements.
List<String> diagnosticStrings(Map<String, dynamic> source, String key) {
  final Object? raw = source[key];
  if (raw is! List) return const <String>[];
  return raw
      .map((Object? value) => value?.toString().trim() ?? '')
      .where((String value) => value.isNotEmpty)
      .toList(growable: false);
}

/// Sous-objet d'une réponse (`environment`, `runtime`, `lastSignal`…).
Map<String, dynamic>? diagnosticMap(Map<String, dynamic> source, String key) {
  final Object? raw = source[key];
  if (raw is Map) return Map<String, dynamic>.from(raw);
  return null;
}
