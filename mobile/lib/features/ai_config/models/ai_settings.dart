import 'package:flutter/foundation.dart';

import 'json_read.dart';

/// Nombre d'avis sollicités avant une décision (CDC2 section 9).
///
/// Arbitrer entre deux fournisseurs n'a plus de sens depuis le retrait de l'IA
/// locale : ce qui reste réglable, c'est le nombre de modèles OpenRouter
/// confrontés sur une même question.
abstract final class AiMode {
  static const String single = 'SINGLE';
  static const String ensemble = 'ENSEMBLE';

  static const List<String> all = <String>[single, ensemble];
}

/// Comportements possibles en cas de désaccord entre les deux modèles.
abstract final class AiDisagreement {
  static const String noTrade = 'NO_TRADE';
  static const String manualReview = 'MANUAL_REVIEW';
}

/// Réglages de l'intelligence, tels que `GET /ai/router/settings`.
///
/// Le mode d'exécution du trading (PAPER / MT5 DEMO / MT5 LIVE) ne figure
/// volontairement pas ici : il reste dans les Paramètres.
@immutable
class AiSettings {
  const AiSettings({
    this.mode = AiMode.single,
    this.openRouterEnabled = true,
    this.ensembleEnabled = false,
    this.ensembleSecondaryModel = '',
    this.requireConsensus = true,
    this.disagreementBehaviour = AiDisagreement.noTrade,
    this.aiTradingEnabled = false,
    this.telegramTradingEnabled = true,
    this.shadowMode = true,
    this.verifySignalsWithAi = false,
    this.maxAiTradesPerDay = 3,
    this.maxTelegramTradesPerDay = 10,
    this.maxTradesPerSymbolPerDay = 2,
    this.minOpportunityConfidence = 0.75,
  });

  final String mode;

  final bool openRouterEnabled;

  final bool ensembleEnabled;

  /// Modèle du second avis. Vide = un seul avis, et le consensus le dit.
  final String ensembleSecondaryModel;
  final bool requireConsensus;
  final String disagreementBehaviour;

  final bool aiTradingEnabled;
  final bool telegramTradingEnabled;
  final bool shadowMode;

  /// Second avis d'une IA sur « ce message est-il vraiment un ordre ? ».
  /// Droit de veto uniquement : peut refuser un faux signal, jamais en créer.
  final bool verifySignalsWithAi;

  final int maxAiTradesPerDay;
  final int maxTelegramTradesPerDay;
  final int maxTradesPerSymbolPerDay;
  final double minOpportunityConfidence;

  factory AiSettings.fromJson(Map<String, dynamic> json) {
    final Map<String, dynamic> ensemble = readMap(json['ensemble']);
    final Map<String, dynamic> trading = readMap(json['trading']);
    const AiSettings fallback = AiSettings();
    return AiSettings(
      mode: readText(json['mode']) ?? fallback.mode,
      openRouterEnabled:
          readBool(json['openRouterEnabled'], fallback: fallback.openRouterEnabled),
      ensembleEnabled: readBool(ensemble['enabled']),
      ensembleSecondaryModel: readText(ensemble['secondaryModel']) ?? '',
      requireConsensus: readBool(ensemble['requireConsensus'], fallback: true),
      disagreementBehaviour:
          readText(ensemble['disagreementBehaviour']) ?? fallback.disagreementBehaviour,
      aiTradingEnabled: readBool(trading['aiTradingEnabled']),
      telegramTradingEnabled:
          readBool(trading['telegramTradingEnabled'], fallback: fallback.telegramTradingEnabled),
      shadowMode: readBool(trading['shadowMode'], fallback: fallback.shadowMode),
      verifySignalsWithAi: readBool(trading['verifySignalsWithAi']),
      maxAiTradesPerDay: readInt(trading['maxAiTradesPerDay']) ?? fallback.maxAiTradesPerDay,
      maxTelegramTradesPerDay:
          readInt(trading['maxTelegramTradesPerDay']) ?? fallback.maxTelegramTradesPerDay,
      maxTradesPerSymbolPerDay:
          readInt(trading['maxTradesPerSymbolPerDay']) ?? fallback.maxTradesPerSymbolPerDay,
      minOpportunityConfidence:
          readDouble(trading['minOpportunityConfidence']) ?? fallback.minOpportunityConfidence,
    );
  }

  /// Corps accepté par `PUT /ai/router/settings` (`AISettingsRequest`).
  ///
  /// Le Bridge ignore les valeurs `null` : un champ texte vidé est donc envoyé
  /// comme chaîne vide, seule façon de l'effacer réellement.
  Map<String, dynamic> toRequest() => <String, dynamic>{
        'mode': mode,
        'openRouterEnabled': openRouterEnabled,
        'ensembleEnabled': ensembleEnabled,
        'ensembleSecondaryModel': ensembleSecondaryModel,
        'requireConsensus': requireConsensus,
        'disagreementBehaviour': disagreementBehaviour,
        'aiTradingEnabled': aiTradingEnabled,
        'telegramTradingEnabled': telegramTradingEnabled,
        'shadowMode': shadowMode,
        'verifySignalsWithAi': verifySignalsWithAi,
        'maxAiTradesPerDay': maxAiTradesPerDay,
        'maxTelegramTradesPerDay': maxTelegramTradesPerDay,
        'maxTradesPerSymbolPerDay': maxTradesPerSymbolPerDay,
        'minOpportunityConfidence': minOpportunityConfidence,
      };

  /// Champs réellement modifiés par rapport à [reference].
  Map<String, dynamic> changesFrom(AiSettings reference) {
    final Map<String, dynamic> mine = toRequest();
    final Map<String, dynamic> theirs = reference.toRequest();
    final Map<String, dynamic> diff = <String, dynamic>{};
    mine.forEach((String key, Object? value) {
      if (theirs[key] != value) diff[key] = value;
    });
    return diff;
  }

  /// Message d'erreur en français si une valeur sortirait des bornes du Bridge.
  String? validate() {
    if (!AiMode.all.contains(mode)) {
      return 'Mode IA inconnu : $mode.';
    }
    if (mode == AiMode.ensemble && ensembleSecondaryModel.trim().isEmpty) {
      return 'Choisissez un second modèle : sans lui, il n’y a qu’un seul avis.';
    }
    if (maxAiTradesPerDay < 0 || maxAiTradesPerDay > 50) {
      return 'Le nombre de trades IA par jour doit rester entre 0 et 50.';
    }
    if (maxTelegramTradesPerDay < 0 || maxTelegramTradesPerDay > 100) {
      return 'Le nombre de trades Telegram par jour doit rester entre 0 et 100.';
    }
    if (maxTradesPerSymbolPerDay < 0 || maxTradesPerSymbolPerDay > 50) {
      return 'Le nombre de trades par instrument doit rester entre 0 et 50.';
    }
    if (minOpportunityConfidence < 0 || minOpportunityConfidence > 1) {
      return 'La confiance minimale doit être comprise entre 0 et 100 %.';
    }
    return null;
  }

  AiSettings copyWith({
    String? mode,
    bool? openRouterEnabled,
    bool? ensembleEnabled,
    String? ensembleSecondaryModel,
    bool? requireConsensus,
    String? disagreementBehaviour,
    bool? aiTradingEnabled,
    bool? telegramTradingEnabled,
    bool? shadowMode,
    bool? verifySignalsWithAi,
    int? maxAiTradesPerDay,
    int? maxTelegramTradesPerDay,
    int? maxTradesPerSymbolPerDay,
    double? minOpportunityConfidence,
  }) {
    return AiSettings(
      mode: mode ?? this.mode,
      openRouterEnabled: openRouterEnabled ?? this.openRouterEnabled,
      ensembleEnabled: ensembleEnabled ?? this.ensembleEnabled,
      ensembleSecondaryModel: ensembleSecondaryModel ?? this.ensembleSecondaryModel,
      requireConsensus: requireConsensus ?? this.requireConsensus,
      disagreementBehaviour: disagreementBehaviour ?? this.disagreementBehaviour,
      aiTradingEnabled: aiTradingEnabled ?? this.aiTradingEnabled,
      telegramTradingEnabled: telegramTradingEnabled ?? this.telegramTradingEnabled,
      shadowMode: shadowMode ?? this.shadowMode,
      verifySignalsWithAi: verifySignalsWithAi ?? this.verifySignalsWithAi,
      maxAiTradesPerDay: maxAiTradesPerDay ?? this.maxAiTradesPerDay,
      maxTelegramTradesPerDay: maxTelegramTradesPerDay ?? this.maxTelegramTradesPerDay,
      maxTradesPerSymbolPerDay: maxTradesPerSymbolPerDay ?? this.maxTradesPerSymbolPerDay,
      minOpportunityConfidence: minOpportunityConfidence ?? this.minOpportunityConfidence,
    );
  }
}
