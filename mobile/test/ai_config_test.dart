import 'dart:convert';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:intl/date_symbol_data_local.dart';
import 'package:tradepilot/core/api/api_client.dart';
import 'package:tradepilot/core/connection/connection_controller.dart';
import 'package:tradepilot/core/theme/app_theme.dart';
import 'package:tradepilot/features/ai_config/ai_config_screen.dart';
import 'package:tradepilot/features/ai_config/ai_diagnostic_screen.dart';
import 'package:tradepilot/features/ai_config/ai_labels.dart';
import 'package:tradepilot/features/ai_config/models/ai_settings.dart';
import 'package:tradepilot/features/ai_config/models/ai_status.dart';

/// Adaptateur Dio factice : il rend les réponses du Bridge sans réseau.
///
/// Les corps sont copiés sur `bridge/app/api/v1/ai.py` : si un nom de champ
/// change côté Bridge, ces tests cessent de refléter la réalité.
const Map<String, List<String>> _jsonHeaders = <String, List<String>>{
  Headers.contentTypeHeader: <String>[Headers.jsonContentType],
};

/// Message que le Bridge renvoie quand OpenRouter ne répond pas.
const String bridgeFailureDetail = 'Circuit ouvert apres 3 echecs consecutifs';

class _FakeAdapter implements HttpClientAdapter {
  _FakeAdapter({this.failing = false});

  /// Rejoue un Bridge qui répond en erreur sur toutes les routes IA.
  final bool failing;

  final List<RequestOptions> requests = <RequestOptions>[];

  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<Uint8List>? requestStream,
    Future<void>? cancelFuture,
  ) async {
    requests.add(options);
    if (failing) {
      return ResponseBody.fromString(
        jsonEncode(<String, dynamic>{'detail': bridgeFailureDetail}),
        503,
        headers: _jsonHeaders,
      );
    }
    return ResponseBody.fromString(
      jsonEncode(_bodyFor(options.path) ?? <String, dynamic>{}),
      200,
      headers: _jsonHeaders,
    );
  }

  Object? _bodyFor(String path) {
    if (path.endsWith('/ai/router/settings')) return settingsBody;
    if (path.endsWith('/ai/status')) return statusBody;
    if (path.endsWith('/ai/metrics')) return metricsBody;
    if (path.endsWith('/ai/openrouter/models')) return openRouterModelsBody;
    if (path.endsWith('/ai/openrouter/test')) return openRouterTestBody;
    return null;
  }

  @override
  void close({bool force = false}) {}
}

const Map<String, dynamic> settingsBody = <String, dynamic>{
  'mode': 'ENSEMBLE',
  'openRouterEnabled': true,
  'ensemble': <String, dynamic>{
    'enabled': true,
    'secondaryModel': 'nvidia/nemotron-nano-9b-v2:free',
    'requireConsensus': true,
    'disagreementBehaviour': 'NO_TRADE',
  },
  'trading': <String, dynamic>{
    'aiTradingEnabled': false, 'telegramTradingEnabled': true, 'shadowMode': true,
    'verifySignalsWithAi': true,
    'maxAiTradesPerDay': 3, 'maxTelegramTradesPerDay': 10, 'maxTradesPerSymbolPerDay': 2,
    'minOpportunityConfidence': 0.75,
  },
};

const Map<String, dynamic> statusBody = <String, dynamic>{
  'mode': 'ENSEMBLE',
  'openrouter': <String, dynamic>{
    'provider': 'OPENROUTER',
    'health': 'DEGRADED',
    'configured': true,
    'available': false,
    'model': 'meta-llama/llama-3.1-70b-instruct:free',
    'visionModel': null,
    'capabilities': <String, dynamic>{
      'text': true, 'json': true, 'tools': true, 'vision': false, 'contextSize': 131072,
    },
    'latencyMs': null,
    'error': 'Circuit ouvert apres 3 echecs consecutifs',
    'detail': null,
  },
  'ensembleEnabled': true,
  'requireConsensus': true,
  'disagreementBehaviour': 'NO_TRADE',
  'aiTradingEnabled': false,
  'shadowMode': true,
  'anyAvailable': true,
  'detail': null,
  'settings': settingsBody,
  'lastRouting': <String, dynamic>{
    'task': 'MARKET_ANALYSIS',
    'chosen': 'LOCAL',
    'fallbackUsed': true,
    'reason': 'OpenRouter indisponible : bascule sur le moteur local',
    'at': '2026-09-11T08:30:00+00:00',
  },
};

const Map<String, dynamic> metricsBody = <String, dynamic>{
  'count': 2,
  'items': <Map<String, dynamic>>[
    <String, dynamic>{
      'provider': 'LOCAL', 'task': 'MARKET_ANALYSIS', 'model': 'qwen2.5:14b-instruct',
      'calls': 248, 'successRate': 0.964, 'validJsonRate': 0.951, 'averageLatencyMs': 1840.0,
      'timeouts': 3, 'errors': 6, 'disagreements': 11, 'hallucinationsBlocked': 2,
      'lastError': 'Delai depasse apres 90 s', 'lastUsedAt': '2026-09-11T08:29:00+00:00',
    },
    <String, dynamic>{
      'provider': 'OPENROUTER', 'task': 'SIGNAL_PARSE',
      'model': 'meta-llama/llama-3.1-70b-instruct:free',
      'calls': 1320, 'successRate': 0.988, 'validJsonRate': 0.997, 'averageLatencyMs': 920.0,
      'timeouts': 1, 'errors': 2, 'disagreements': 4, 'hallucinationsBlocked': 0,
      'lastError': null, 'lastUsedAt': '2026-09-11T08:20:00+00:00',
    },
  ],
};

const Map<String, dynamic> openRouterModelsBody = <String, dynamic>{
  'textModel': 'meta-llama/llama-3.1-70b-instruct:free',
  'visionModel': 'qwen/qwen-2-vl-7b-instruct:free',
  'autoMode': true,
  'freeModels': <Map<String, dynamic>>[
    <String, dynamic>{
      'id': 'meta-llama/llama-3.1-70b-instruct:free',
      'free': true, 'vision': false, 'tools': true, 'context': 131072, 'score': 9.4,
    },
    <String, dynamic>{
      'id': 'qwen/qwen-2-vl-7b-instruct:free',
      'free': true, 'vision': true, 'tools': false, 'context': 32768, 'score': 7.1,
    },
  ],
};

const Map<String, dynamic> openRouterTestBody = <String, dynamic>{
  'ok': true,
  'model': 'meta-llama/llama-3.1-70b-instruct:free',
  'latencyMs': 412,
  'error': null,
};

/// Client pointé sur l'adaptateur factice, jeton inclus.
ApiClient _client(_FakeAdapter adapter) {
  final Dio dio = Dio()..httpClientAdapter = adapter;
  return ApiClient(dio: dio)..configure(baseUrl: 'http://bridge.test', token: 'jeton-de-test');
}

/// Rend un écran dans un téléphone étroit : tout débordement fait échouer.
Future<void> _pump(WidgetTester tester, Widget screen, {_FakeAdapter? adapter}) async {
  tester.view.physicalSize = const Size(360, 690);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(
    ProviderScope(
      overrides: <Override>[
        apiClientProvider.overrideWithValue(_client(adapter ?? _FakeAdapter())),
      ],
      child: MaterialApp(theme: AppTheme.light(), home: screen),
    ),
  );
  await tester.pumpAndSettle();
}

/// Parcourt tout l'écran et note les libellés rencontrés.
///
/// Un `ListView` ne construit que ce qui est visible : sans ce défilement,
/// les sections du bas ne seraient jamais mises en page, et un débordement
/// passerait inaperçu.
Future<Set<String>> _scrollAndCollect(WidgetTester tester, List<String> labels) async {
  final Set<String> seen = <String>{};
  void record() {
    for (final String label in labels) {
      if (find.text(label).evaluate().isNotEmpty) seen.add(label);
    }
  }

  record();
  for (int step = 0; step < 30; step++) {
    await tester.drag(find.byType(ListView), const Offset(0, -240), warnIfMissed: false);
    await tester.pumpAndSettle();
    record();
  }
  return seen;
}

/// Fait défiler jusqu'à ce que [target] soit construit, puis le rend visible.
Future<void> _scrollTo(WidgetTester tester, Finder target) async {
  for (int step = 0; step < 30 && target.evaluate().isEmpty; step++) {
    await tester.drag(find.byType(ListView), const Offset(0, -240), warnIfMissed: false);
    await tester.pumpAndSettle();
  }
  await tester.ensureVisible(target);
  await tester.pumpAndSettle();
}

void main() {
  setUpAll(() async => initializeDateFormatting('fr_FR'));

  group('Réglages IA', () {
    test('la lecture suit exactement le contrat du Bridge', () {
      final AiSettings settings = AiSettings.fromJson(settingsBody);
      expect(settings.mode, AiMode.ensemble);
      expect(settings.ensembleEnabled, isTrue);
      expect(settings.ensembleSecondaryModel, 'nvidia/nemotron-nano-9b-v2:free');
      expect(settings.verifySignalsWithAi, isTrue);
      expect(settings.disagreementBehaviour, AiDisagreement.noTrade);
      expect(settings.aiTradingEnabled, isFalse);
      expect(settings.shadowMode, isTrue);
      expect(settings.minOpportunityConfidence, 0.75);
    });

    test('seuls les champs modifiés sont envoyés, avec les alias camelCase', () {
      final AiSettings saved = AiSettings.fromJson(settingsBody);
      final AiSettings draft = saved.copyWith(shadowMode: false, maxAiTradesPerDay: 5);
      expect(
        draft.changesFrom(saved),
        <String, dynamic>{'shadowMode': false, 'maxAiTradesPerDay': 5},
      );
      expect(saved.changesFrom(saved), isEmpty);
    });

    test('les bornes du Bridge sont vérifiées avant l envoi', () {
      final AiSettings saved = AiSettings.fromJson(settingsBody);
      expect(saved.validate(), isNull);
      expect(saved.copyWith(maxAiTradesPerDay: 99).validate(), isNotNull);
      expect(saved.copyWith(minOpportunityConfidence: 1.5).validate(), isNotNull);
      // Le mode ensemble sans second modele ne confronte rien : on le refuse
      // avant l'envoi plutot que de laisser croire a une confrontation.
      expect(saved.copyWith(ensembleSecondaryModel: '  ').validate(), isNotNull);
    });

    test('le mode d exécution du trading n est jamais envoyé par cet écran', () {
      final Map<String, dynamic> request = AiSettings.fromJson(settingsBody).toRequest();
      expect(request.containsKey('executionMode'), isFalse);
      expect(request.containsKey('mode'), isTrue);
      expect(request['mode'], AiMode.ensemble);
    });
  });

  group('Diagnostic', () {
    test('l état des moteurs est lu sans interprétation', () {
      final AiStatus status = AiStatus.fromJson(statusBody);
      expect(status.openRouter.health, 'DEGRADED');
      expect(status.openRouter.error, 'Circuit ouvert apres 3 echecs consecutifs');
      expect(status.lastRouting?.chosen, 'LOCAL');
      expect(status.lastRouting?.fallbackUsed, isTrue);
      // Les deux moteurs ne répondent pas ensemble : pas de consensus possible.
      expect(status.consensusOnline, isFalse);
    });

    test('les libellés français couvrent les valeurs du Bridge', () {
      expect(AiLabels.mode(AiMode.ensemble), 'Deux avis confrontés');
      expect(AiLabels.mode(AiMode.single), 'Un seul avis');
      expect(AiLabels.health('DEGRADED'), 'Dégradé');
      expect(AiLabels.provider('OPENROUTER'), 'OpenRouter');
      expect(AiLabels.task('OPPORTUNITY_REVIEW'), 'Revue d’opportunité');
      expect(AiLabels.disagreement('MANUAL_REVIEW'), 'Revue manuelle');
      expect(AiLabels.rate(0.964), '96 %');
      expect(AiLabels.latency(1840), '1840 ms');
      expect(AiLabels.rate(null), '--');
    });
  });

  group('Mise en page à 360 points', () {
    testWidgets('écran de configuration IA', (WidgetTester tester) async {
      await _pump(tester, const AiConfigScreen());
      expect(find.text('Intelligence artificielle'), findsOneWidget);
      expect(find.text('Mode IA'), findsOneWidget);
      // Tout l'écran est parcouru : un RenderFlex qui déborde à 360 points
      // lève une exception pendant le défilement.
      final Set<String> seen = await _scrollAndCollect(tester, <String>[
        'OpenRouter',
        // Pastille d'état alimentée par GET /ai/status (§95 « Status »).
        'Dégradé',
        'Ensemble',
        'Exiger un consensus avant un trade automatique',
        'Garde-fous du trading IA',
        'Mode observation',
        'Confiance minimale d’une opportunité',
      ]);
      expect(seen, hasLength(7));
      expect(tester.takeException(), isNull);
    });

    testWidgets('la barre d enregistrement n apparaît qu après une modification',
        (WidgetTester tester) async {
      await _pump(tester, const AiConfigScreen());
      expect(find.text('Enregistrer'), findsNothing);

      await tester.tap(find.text('Un seul avis'));
      await tester.pumpAndSettle();
      expect(find.text('Enregistrer'), findsOneWidget);
      expect(find.text('Annuler'), findsOneWidget);

      await tester.tap(find.text('Annuler'));
      await tester.pumpAndSettle();
      expect(find.text('Enregistrer'), findsNothing);
    });

    testWidgets('l enregistrement n envoie que le champ modifié',
        (WidgetTester tester) async {
      final _FakeAdapter adapter = _FakeAdapter();
      await _pump(tester, const AiConfigScreen(), adapter: adapter);

      await tester.tap(find.text('Un seul avis'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Enregistrer'));
      await tester.pumpAndSettle();

      final RequestOptions put = adapter.requests.lastWhere(
        (RequestOptions request) => request.method == 'PUT',
      );
      expect(put.path, endsWith('/ai/router/settings'));
      expect(put.data, <String, dynamic>{'mode': AiMode.single});
      expect(find.text('Réglages IA enregistrés.'), findsOneWidget);
    });

    testWidgets('activer le trading IA exige une confirmation explicite',
        (WidgetTester tester) async {
      final _FakeAdapter adapter = _FakeAdapter();
      await _pump(tester, const AiConfigScreen(), adapter: adapter);

      final Finder toggle = find.text('Trading piloté par l’IA');
      await _scrollTo(tester, toggle);
      await tester.tap(toggle);
      await tester.pumpAndSettle();

      expect(find.byType(AlertDialog), findsOneWidget);
      expect(
        find.descendant(
          of: find.byType(AlertDialog),
          matching: find.textContaining('moteur de risque garde le dernier mot'),
        ),
        findsOneWidget,
      );
      await tester.tap(find.text('Annuler'));
      await tester.pumpAndSettle();
      // Refus : rien n'est modifié, donc rien à enregistrer.
      expect(find.text('Enregistrer'), findsNothing);
      expect(adapter.requests.any((RequestOptions r) => r.method == 'PUT'), isFalse);
    });

    testWidgets('le test de connexion affiche la latence mesurée',
        (WidgetTester tester) async {
      await _pump(tester, const AiConfigScreen());
      final Finder button = find.text('Tester OpenRouter');
      await _scrollTo(tester, button);
      await tester.tap(button);
      await tester.pumpAndSettle();
      expect(find.text('Connexion établie'), findsOneWidget);
      expect(find.text('Latence 412 ms'), findsOneWidget);
      expect(
        find.textContaining('meta-llama/llama-3.1-70b-instruct:free'),
        findsWidgets,
      );
      expect(tester.takeException(), isNull);
    });

    testWidgets('écran de diagnostic IA', (WidgetTester tester) async {
      await _pump(tester, const AiDiagnosticScreen());
      expect(find.text('Diagnostic IA'), findsOneWidget);
      expect(find.text('OpenRouter'), findsWidgets);
      final Set<String> seen = await _scrollAndCollect(tester, <String>[
        'Dégradé',
        'Circuit ouvert apres 3 echecs consecutifs',
        'Routeur IA',
        'Dernière décision de routage',
        'Repli utilisé',
        'Service de consensus',
        'Fiabilité mesurée',
        'Hallucinations bloquées',
        'Désaccords',
        'JSON valide',
        'Délais dépassés',
      ]);
      expect(seen, hasLength(11));
      expect(tester.takeException(), isNull);
    });

    testWidgets('une panne du Bridge affiche son message, pas une invention',
        (WidgetTester tester) async {
      await _pump(tester, const AiDiagnosticScreen(), adapter: _FakeAdapter(failing: true));
      expect(find.text(bridgeFailureDetail), findsOneWidget);
      expect(find.text('Détails techniques'), findsOneWidget);
      expect(tester.takeException(), isNull);
    });
  });
}
