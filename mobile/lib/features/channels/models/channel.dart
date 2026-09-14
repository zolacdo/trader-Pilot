import 'package:flutter/foundation.dart';
import 'package:intl/intl.dart';

import 'json_read.dart';

final NumberFormat _countFormat = NumberFormat.decimalPattern('fr_FR');

/// Nombre entier lisible (membres, messages). `--` quand la valeur est absente.
String formatCount(int? value) => value == null ? '--' : _countFormat.format(value);

/// Nombre décimal écrit à la française (virgule décimale).
String formatDecimal(num? value, {int digits = 1}) =>
    value == null ? '--' : value.toStringAsFixed(digits).replaceAll('.', ',');

/// Taux renvoyé par le Bridge, déjà exprimé en pourcentage.
String formatRate(num? value) => value == null ? '--' : '${formatDecimal(value)} %';

/// Les trois modes de fonctionnement d'un canal (CDC section 70).
abstract final class ChannelModes {
  static const String observe = 'OBSERVE';
  static const String manual = 'MANUAL';
  static const String auto = 'AUTO';

  static const List<String> all = <String>[observe, manual, auto];

  /// Ce que fait réellement chaque mode, dit en clair à l'utilisateur.
  static String explain(String mode) {
    return switch (mode) {
      observe => 'Le canal est reçu, analysé et simulé. Aucun ordre n\'est jamais envoyé.',
      manual => 'Chaque signal vous est proposé et attend votre confirmation avant exécution.',
      auto => 'Les signaux sont exécutés automatiquement si toutes les protections passent.',
      _ => '--',
    };
  }
}

/// Réglages par canal. Un champ `null` signifie « utiliser le réglage global ».
@immutable
class ChannelSettings {
  const ChannelSettings({
    this.enabled = true,
    this.mode = ChannelModes.observe,
    this.copyBuy = true,
    this.copySell = true,
    this.riskPercent,
    this.maxPositions,
    this.maxLot,
    this.maxSpreadPoints,
    this.maxSignalAgeSeconds,
    this.minConfidence,
    this.requireStopLoss,
    this.requireTakeProfit,
    this.multiTpStrategy,
    this.allowedSymbols = const <String>[],
  });

  final bool enabled;
  final String mode;
  final bool copyBuy;
  final bool copySell;
  final double? riskPercent;
  final int? maxPositions;
  final double? maxLot;
  final int? maxSpreadPoints;
  final int? maxSignalAgeSeconds;
  final double? minConfidence;
  final bool? requireStopLoss;
  final bool? requireTakeProfit;
  final String? multiTpStrategy;
  final List<String> allowedSymbols;

  factory ChannelSettings.fromJson(Map<String, dynamic> json) {
    return ChannelSettings(
      enabled: readBool(json['enabled'], fallback: true),
      mode: readText(json['mode']) ?? ChannelModes.observe,
      copyBuy: readBool(json['copyBuy'], fallback: true),
      copySell: readBool(json['copySell'], fallback: true),
      riskPercent: readDouble(json['riskPercent']),
      maxPositions: readInt(json['maxPositions']),
      maxLot: readDouble(json['maxLot']),
      maxSpreadPoints: readInt(json['maxSpreadPoints']),
      maxSignalAgeSeconds: readInt(json['maxSignalAgeSeconds']),
      minConfidence: readDouble(json['minConfidence']),
      requireStopLoss: json['requireStopLoss'] == null ? null : readBool(json['requireStopLoss']),
      requireTakeProfit:
          json['requireTakeProfit'] == null ? null : readBool(json['requireTakeProfit']),
      multiTpStrategy: readText(json['multiTpStrategy']),
      allowedSymbols: readTextList(json['allowedSymbols']),
    );
  }
}

/// Libellés français des stratégies de TP multiples.
String multiTpStrategyLabel(String? code) {
  return switch (code) {
    'FIRST_TP_ONLY' => 'Premier TP uniquement',
    'SPLIT_POSITIONS' => 'Une position par TP',
    'PARTIAL_CLOSE' => 'Fermetures partielles',
    'LAST_TP_ONLY' => 'Dernier TP uniquement',
    _ => code ?? '--',
  };
}

/// Canal surveillé.
@immutable
class Channel {
  const Channel({
    required this.id,
    required this.title,
    this.telegramId,
    this.username,
    this.description,
    this.membersCount,
    this.isPublic = true,
    this.joined = false,
    this.monitored = false,
    this.signalsCount = 0,
    this.lastMessageAt,
    this.lastSignalAt,
    this.settings,
  });

  final int id;
  final String title;
  final int? telegramId;
  final String? username;
  final String? description;
  final int? membersCount;
  final bool isPublic;
  final bool joined;
  final bool monitored;
  final int signalsCount;
  final DateTime? lastMessageAt;
  final DateTime? lastSignalAt;
  final ChannelSettings? settings;

  String get mode => settings?.mode ?? ChannelModes.observe;

  bool get enabled => settings?.enabled ?? true;

  String get handle => username == null ? '--' : '@$username';

  factory Channel.fromJson(Map<String, dynamic> json) {
    final Object? rawSettings = json['settings'];
    return Channel(
      id: readInt(json['id']) ?? 0,
      title: readText(json['title']) ?? 'Canal sans titre',
      telegramId: readInt(json['telegramId']),
      username: readText(json['username']),
      description: readText(json['description']),
      membersCount: readInt(json['membersCount']),
      isPublic: readBool(json['isPublic'], fallback: true),
      joined: readBool(json['joined']),
      monitored: readBool(json['monitored']),
      signalsCount: readInt(json['signalsCount']) ?? 0,
      lastMessageAt: readDate(json['lastMessageAt']),
      lastSignalAt: readDate(json['lastSignalAt']),
      settings: rawSettings == null ? null : ChannelSettings.fromJson(readMap(rawSettings)),
    );
  }
}

/// Profil de parsing appris pour un canal (CDC section 53).
@immutable
class ParserProfile {
  const ParserProfile({
    this.knownFormats = const <String>[],
    this.lastSuccessfulFormat,
    this.deterministicSuccess,
    this.aiFallbackCount,
    this.confidence,
    this.symbolAliases = const <String, String>{},
  });

  final List<String> knownFormats;
  final String? lastSuccessfulFormat;
  final int? deterministicSuccess;
  final int? aiFallbackCount;
  final double? confidence;
  final Map<String, String> symbolAliases;

  factory ParserProfile.fromJson(Map<String, dynamic> json) {
    final Map<String, dynamic> aliases = readMap(json['symbolAliases']);
    return ParserProfile(
      knownFormats: readTextList(json['knownFormats']),
      lastSuccessfulFormat: readText(json['lastSuccessfulFormat']),
      deterministicSuccess: readInt(json['deterministicSuccess']),
      aiFallbackCount: readInt(json['aiFallbackCount']),
      confidence: readDouble(json['confidence']),
      symbolAliases: aliases.map(
        (String key, Object? value) => MapEntry<String, String>(key, readText(value) ?? '--'),
      ),
    );
  }
}

/// Résumé d'une simulation historique (CDC section 14).
@immutable
class BacktestSummary {
  const BacktestSummary({
    this.testable,
    this.wins,
    this.losses,
    this.ambiguous,
    this.undetermined,
    this.stillOpen,
    this.averageR,
    this.totalR,
    this.theoreticalDrawdownR,
    this.tp1Hits,
    this.slHits,
    this.disclaimer,
  });

  final int? testable;
  final int? wins;
  final int? losses;
  final int? ambiguous;
  final int? undetermined;
  final int? stillOpen;
  final double? averageR;
  final double? totalR;
  final double? theoreticalDrawdownR;
  final int? tp1Hits;
  final int? slHits;
  final String? disclaimer;

  factory BacktestSummary.fromJson(Map<String, dynamic> json) {
    return BacktestSummary(
      testable: readInt(json['testable']),
      wins: readInt(json['wins']),
      losses: readInt(json['losses']),
      ambiguous: readInt(json['ambiguous']),
      undetermined: readInt(json['undetermined']),
      stillOpen: readInt(json['open']),
      averageR: readDouble(json['averageR']),
      totalR: readDouble(json['totalR']),
      theoreticalDrawdownR: readDouble(json['theoreticalDrawdownR']),
      tp1Hits: readInt(json['tp1Hits']),
      slHits: readInt(json['slHits']),
      disclaimer: readText(json['disclaimer']),
    );
  }
}

/// Rapport d'analyse d'un canal (CDC section 13). Mesures factuelles seulement.
@immutable
class ChannelAnalysis {
  const ChannelAnalysis({
    required this.id,
    this.createdAt,
    this.messagesScanned,
    this.signalLikeMessages,
    this.parsedMessages,
    this.followUpMessages,
    this.closeMessages,
    this.modifyMessages,
    this.duplicateSignals,
    this.structureQuality,
    this.withStopLossRate,
    this.withTakeProfitRate,
    this.parseableRate,
    this.averageTakeProfits,
    this.signalsPerDay,
    this.firstMessageAt,
    this.lastMessageAt,
    this.symbols = const <String, int>{},
    this.directions = const <String, int>{},
    this.backtest,
    this.notes,
    this.disclaimer,
  });

  final int id;
  final DateTime? createdAt;
  final int? messagesScanned;
  final int? signalLikeMessages;
  final int? parsedMessages;
  final int? followUpMessages;
  final int? closeMessages;
  final int? modifyMessages;
  final int? duplicateSignals;
  final double? structureQuality;
  final double? withStopLossRate;
  final double? withTakeProfitRate;
  final double? parseableRate;
  final double? averageTakeProfits;
  final double? signalsPerDay;
  final DateTime? firstMessageAt;
  final DateTime? lastMessageAt;
  final Map<String, int> symbols;
  final Map<String, int> directions;
  final BacktestSummary? backtest;
  final String? notes;
  final String? disclaimer;

  factory ChannelAnalysis.fromJson(Map<String, dynamic> json) {
    final Object? rawBacktest = json['backtest'];
    final Map<String, dynamic> backtest = readMap(rawBacktest);
    return ChannelAnalysis(
      id: readInt(json['id']) ?? 0,
      createdAt: readDate(json['createdAt']),
      messagesScanned: readInt(json['messagesScanned']),
      signalLikeMessages: readInt(json['signalLikeMessages']),
      parsedMessages: readInt(json['parsedMessages']),
      followUpMessages: readInt(json['followUpMessages']),
      closeMessages: readInt(json['closeMessages']),
      modifyMessages: readInt(json['modifyMessages']),
      duplicateSignals: readInt(json['duplicateSignals']),
      structureQuality: readDouble(json['structureQuality']),
      withStopLossRate: readDouble(json['withStopLossRate']),
      withTakeProfitRate: readDouble(json['withTakeProfitRate']),
      parseableRate: readDouble(json['parseableRate']),
      averageTakeProfits: readDouble(json['averageTakeProfits']),
      signalsPerDay: readDouble(json['signalsPerDay']),
      firstMessageAt: readDate(json['firstMessageAt']),
      lastMessageAt: readDate(json['lastMessageAt']),
      symbols: readCounts(json['symbols']),
      directions: readCounts(json['directions']),
      backtest: backtest.isEmpty ? null : BacktestSummary.fromJson(backtest),
      notes: readText(json['notes']),
      disclaimer: readText(json['disclaimer']),
    );
  }
}

/// Signal récent listé dans le détail d'un canal.
@immutable
class ChannelRecentSignal {
  const ChannelRecentSignal({
    required this.id,
    required this.status,
    this.symbol,
    this.direction,
    this.confidence,
    this.receivedAt,
  });

  final int id;
  final String status;
  final String? symbol;
  final String? direction;
  final double? confidence;
  final DateTime? receivedAt;

  factory ChannelRecentSignal.fromJson(Map<String, dynamic> json) {
    return ChannelRecentSignal(
      id: readInt(json['id']) ?? 0,
      status: readText(json['status']) ?? 'RECEIVED',
      symbol: readText(json['symbol']),
      direction: readText(json['direction']),
      confidence: readDouble(json['confidence']),
      receivedAt: readDate(json['receivedAt']),
    );
  }
}

/// Réponse de `GET /channels/{id}`.
@immutable
class ChannelDetail {
  const ChannelDetail({
    required this.channel,
    required this.parserProfile,
    this.latestAnalysis,
    this.recentSignals = const <ChannelRecentSignal>[],
  });

  final Channel channel;
  final ParserProfile parserProfile;
  final ChannelAnalysis? latestAnalysis;
  final List<ChannelRecentSignal> recentSignals;

  factory ChannelDetail.fromJson(Map<String, dynamic> json) {
    final Map<String, dynamic> analysis = readMap(json['latestAnalysis']);
    return ChannelDetail(
      channel: Channel.fromJson(json),
      parserProfile: ParserProfile.fromJson(readMap(json['parserProfile'])),
      latestAnalysis: analysis.isEmpty ? null : ChannelAnalysis.fromJson(analysis),
      recentSignals: readMapList(json['recentSignals'])
          .map(ChannelRecentSignal.fromJson)
          .toList(growable: false),
    );
  }
}
