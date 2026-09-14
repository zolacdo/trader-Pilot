import 'package:flutter/foundation.dart';

import 'ai_settings.dart';
import 'json_read.dart';

/// État d'un moteur, tel que `AIProviderStatus.to_dict()` côté Bridge.
@immutable
class AiProviderState {
  const AiProviderState({
    required this.provider,
    required this.health,
    required this.configured,
    required this.available,
    this.model,
    this.visionModel,
    this.latencyMs,
    this.error,
    this.detail,
    this.supportsText = true,
    this.supportsJson = false,
    this.supportsTools = false,
    this.supportsVision = false,
    this.contextSize,
  });

  final String provider;

  /// `ONLINE`, `DEGRADED` ou `OFFLINE`.
  final String health;
  final bool configured;
  final bool available;
  final String? model;
  final String? visionModel;
  final int? latencyMs;
  final String? error;
  final String? detail;
  final bool supportsText;
  final bool supportsJson;
  final bool supportsTools;
  final bool supportsVision;
  final int? contextSize;

  factory AiProviderState.fromJson(Map<String, dynamic> json) {
    final Map<String, dynamic> caps = readMap(json['capabilities']);
    return AiProviderState(
      provider: readText(json['provider']) ?? '--',
      health: readText(json['health']) ?? 'OFFLINE',
      configured: readBool(json['configured']),
      available: readBool(json['available']),
      model: readText(json['model']),
      visionModel: readText(json['visionModel']),
      latencyMs: readInt(json['latencyMs']),
      error: readText(json['error']),
      detail: readText(json['detail']),
      supportsText: readBool(caps['text'], fallback: true),
      supportsJson: readBool(caps['json']),
      supportsTools: readBool(caps['tools']),
      supportsVision: readBool(caps['vision']),
      contextSize: readInt(caps['contextSize']),
    );
  }
}

/// Dernière décision du routeur (`lastRouting` de `GET /ai/status`).
@immutable
class AiRoutingDecision {
  const AiRoutingDecision({
    required this.task,
    this.chosen,
    this.fallbackUsed = false,
    this.reason,
    this.at,
  });

  final String task;
  final String? chosen;
  final bool fallbackUsed;
  final String? reason;
  final DateTime? at;

  factory AiRoutingDecision.fromJson(Map<String, dynamic> json) => AiRoutingDecision(
        task: readText(json['task']) ?? '--',
        chosen: readText(json['chosen']),
        fallbackUsed: readBool(json['fallbackUsed']),
        reason: readText(json['reason']),
        at: readDate(json['at']),
      );
}

/// Réponse complète de `GET /ai/status`.
@immutable
class AiStatus {
  const AiStatus({
    required this.mode,
    required this.openRouter,
    required this.settings,
    this.ensembleEnabled = false,
    this.requireConsensus = false,
    this.disagreementBehaviour,
    this.aiTradingEnabled = false,
    this.shadowMode = true,
    this.anyAvailable = false,
    this.detail,
    this.lastRouting,
  });

  final String mode;
  final AiProviderState openRouter;
  final AiSettings settings;
  final bool ensembleEnabled;
  final bool requireConsensus;
  final String? disagreementBehaviour;
  final bool aiTradingEnabled;
  final bool shadowMode;
  final bool anyAvailable;
  final String? detail;
  final AiRoutingDecision? lastRouting;

  /// La confrontation suppose que le fournisseur réponde.
  ///
  /// Les deux avis viennent du même fournisseur : c'est le second modèle qui
  /// les distingue, et son absence est signalée par le Bridge lui-même.
  bool get consensusOnline => ensembleEnabled && openRouter.available;

  factory AiStatus.fromJson(Map<String, dynamic> json) {
    final Object? routing = json['lastRouting'];
    return AiStatus(
      mode: readText(json['mode']) ?? AiMode.single,
      openRouter: AiProviderState.fromJson(readMap(json['openrouter'])),
      settings: AiSettings.fromJson(readMap(json['settings'])),
      ensembleEnabled: readBool(json['ensembleEnabled']),
      requireConsensus: readBool(json['requireConsensus']),
      disagreementBehaviour: readText(json['disagreementBehaviour']),
      aiTradingEnabled: readBool(json['aiTradingEnabled']),
      shadowMode: readBool(json['shadowMode'], fallback: true),
      anyAvailable: readBool(json['anyAvailable']),
      detail: readText(json['detail']),
      lastRouting: routing is Map ? AiRoutingDecision.fromJson(readMap(routing)) : null,
    );
  }
}

/// Une ligne de `GET /ai/metrics` : un moteur pour un type de tâche.
@immutable
class AiMetricRow {
  const AiMetricRow({
    required this.provider,
    required this.task,
    required this.calls,
    this.model,
    this.successRate,
    this.validJsonRate,
    this.averageLatencyMs,
    this.timeouts = 0,
    this.errors = 0,
    this.disagreements = 0,
    this.hallucinationsBlocked = 0,
    this.lastError,
    this.lastUsedAt,
  });

  final String provider;
  final String task;
  final int calls;
  final String? model;
  final double? successRate;
  final double? validJsonRate;
  final double? averageLatencyMs;
  final int timeouts;
  final int errors;
  final int disagreements;
  final int hallucinationsBlocked;
  final String? lastError;
  final DateTime? lastUsedAt;

  factory AiMetricRow.fromJson(Map<String, dynamic> json) => AiMetricRow(
        provider: readText(json['provider']) ?? '--',
        task: readText(json['task']) ?? '--',
        calls: readInt(json['calls']) ?? 0,
        model: readText(json['model']),
        successRate: readDouble(json['successRate']),
        validJsonRate: readDouble(json['validJsonRate']),
        averageLatencyMs: readDouble(json['averageLatencyMs']),
        timeouts: readInt(json['timeouts']) ?? 0,
        errors: readInt(json['errors']) ?? 0,
        disagreements: readInt(json['disagreements']) ?? 0,
        hallucinationsBlocked: readInt(json['hallucinationsBlocked']) ?? 0,
        lastError: readText(json['lastError']),
        lastUsedAt: readDate(json['lastUsedAt']),
      );
}

/// Résultat d'un test de connexion (`POST /ai/openrouter/test`).
@immutable
class AiTestResult {
  const AiTestResult({required this.ok, this.model, this.latencyMs, this.error, this.at});

  final bool ok;
  final String? model;
  final int? latencyMs;
  final String? error;
  final DateTime? at;

  factory AiTestResult.fromJson(Map<String, dynamic> json) => AiTestResult(
        ok: readBool(json['ok']),
        model: readText(json['model']),
        latencyMs: readInt(json['latencyMs']),
        error: readText(json['error']),
        at: DateTime.now(),
      );
}

/// Modèle gratuit proposé par OpenRouter.
@immutable
class AiFreeModel {
  const AiFreeModel({
    required this.id,
    this.vision = false,
    this.tools = false,
    this.contextSize,
  });

  final String id;
  final bool vision;
  final bool tools;
  final int? contextSize;

  factory AiFreeModel.fromJson(Map<String, dynamic> json) => AiFreeModel(
        id: readText(json['id']) ?? '',
        vision: readBool(json['vision']),
        tools: readBool(json['tools']),
        contextSize: readInt(json['context']),
      );
}

/// Modèles gratuits OpenRouter (`GET /ai/openrouter/models`).
@immutable
class AiOpenRouterModels {
  const AiOpenRouterModels({
    this.textModel,
    this.visionModel,
    this.autoMode = true,
    this.freeModels = const <AiFreeModel>[],
  });

  final String? textModel;
  final String? visionModel;
  final bool autoMode;
  final List<AiFreeModel> freeModels;

  factory AiOpenRouterModels.fromJson(Map<String, dynamic> json) => AiOpenRouterModels(
        textModel: readText(json['textModel']),
        visionModel: readText(json['visionModel']),
        autoMode: readBool(json['autoMode'], fallback: true),
        freeModels: readMapList(json['freeModels'])
            .map(AiFreeModel.fromJson)
            .where((AiFreeModel model) => model.id.isNotEmpty)
            .toList(growable: false),
      );
}
