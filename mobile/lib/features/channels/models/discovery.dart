import 'package:flutter/foundation.dart';

import 'json_read.dart';

/// Canal trouvé par la recherche Telegram (`POST /telegram/discover`).
///
/// Aucun canal n'est jamais rejoint par cette recherche : `alreadyJoined`
/// décrit seulement ce que le compte Telegram suit déjà.
@immutable
class DiscoveredChannel {
  const DiscoveredChannel({
    required this.id,
    required this.title,
    this.username,
    this.description,
    this.membersCount,
    this.isPublic = true,
    this.alreadyJoined = false,
    this.lastMessageAt,
    this.estimatedMessages,
    this.sampleSize,
    this.signalLikeCount,
    this.signalRate,
    this.previewAvailable = false,
    this.previewReason,
  });

  final int id;
  final String title;
  final String? username;
  final String? description;
  final int? membersCount;
  final bool isPublic;
  final bool alreadyJoined;
  final DateTime? lastMessageAt;
  final int? estimatedMessages;

  /// Nombre de messages récents réellement examinés par le Bridge.
  final int? sampleSize;

  /// Parmi eux, combien ressemblent à un signal exploitable.
  final int? signalLikeCount;

  /// Proportion correspondante, entre 0 et 1.
  final double? signalRate;

  /// Faux quand le contenu n'a pas pu être lu : [previewReason] dit pourquoi.
  final bool previewAvailable;
  final String? previewReason;

  String get handle => username == null ? '--' : '@$username';

  /// Résumé court affiché sur la carte, ex. « 12 / 30 messages ».
  String get analysableLabel {
    if (!previewAvailable || sampleSize == null || signalLikeCount == null) return '--';
    return '$signalLikeCount / $sampleSize';
  }

  factory DiscoveredChannel.fromJson(Map<String, dynamic> json) {
    return DiscoveredChannel(
      id: readInt(json['id']) ?? 0,
      title: readText(json['title']) ?? 'Canal sans titre',
      username: readText(json['username']),
      description: readText(json['description']),
      membersCount: readInt(json['membersCount']),
      isPublic: readBool(json['isPublic'], fallback: true),
      alreadyJoined: readBool(json['alreadyJoined']),
      lastMessageAt: readDate(json['lastMessageAt']),
      estimatedMessages: readInt(json['estimatedMessages']),
      sampleSize: readInt(json['sampleSize']),
      signalLikeCount: readInt(json['signalLikeCount']),
      signalRate: readDouble(json['signalRate']),
      previewAvailable: readBool(json['previewAvailable']),
      previewReason: readText(json['previewReason']),
    );
  }
}

/// Résultat complet d'une recherche.
@immutable
class DiscoveryResults {
  const DiscoveryResults({required this.query, this.results = const <DiscoveredChannel>[]});

  final String query;
  final List<DiscoveredChannel> results;

  factory DiscoveryResults.fromJson(Map<String, dynamic> json) {
    return DiscoveryResults(
      query: readText(json['query']) ?? '',
      results:
          readMapList(json['results']).map(DiscoveredChannel.fromJson).toList(growable: false),
    );
  }
}

/// Ligne du tableau de comparaison (`GET /channels/compare/table`).
@immutable
class CompareRow {
  const CompareRow({
    required this.channelId,
    required this.title,
    this.username,
    this.monitored = false,
    this.signalsDetected,
    this.messagesScanned,
    this.parseRate,
    this.slRate,
    this.tpRate,
    this.signalsPerDay,
    this.analysedAt,
    this.historyAvailable = false,
    this.paperTrades,
    this.paperPnl,
    this.paperWinRate,
    this.paperDrawdown,
    this.averageR,
  });

  final int channelId;
  final String title;
  final String? username;
  final bool monitored;
  final int? signalsDetected;
  final int? messagesScanned;
  final double? parseRate;
  final double? slRate;
  final double? tpRate;
  final double? signalsPerDay;
  final DateTime? analysedAt;
  final bool historyAvailable;
  final int? paperTrades;
  final double? paperPnl;
  final double? paperWinRate;
  final double? paperDrawdown;
  final double? averageR;

  factory CompareRow.fromJson(Map<String, dynamic> json) {
    return CompareRow(
      channelId: readInt(json['channelId']) ?? 0,
      title: readText(json['title']) ?? 'Canal sans titre',
      username: readText(json['username']),
      monitored: readBool(json['monitored']),
      signalsDetected: readInt(json['signalsDetected']),
      messagesScanned: readInt(json['messagesScanned']),
      parseRate: readDouble(json['parseRate']),
      slRate: readDouble(json['slRate']),
      tpRate: readDouble(json['tpRate']),
      signalsPerDay: readDouble(json['signalsPerDay']),
      analysedAt: readDate(json['analysedAt']),
      historyAvailable: readBool(json['historyAvailable']),
      paperTrades: readInt(json['paperTrades']),
      paperPnl: readDouble(json['paperPnl']),
      paperWinRate: readDouble(json['paperWinRate']),
      paperDrawdown: readDouble(json['paperDrawdown']),
      averageR: readDouble(json['averageR']),
    );
  }
}

/// Tableau de comparaison complet, avec l'avertissement renvoyé par l'API.
@immutable
class CompareTable {
  const CompareTable({this.rows = const <CompareRow>[], this.disclaimer});

  final List<CompareRow> rows;
  final String? disclaimer;

  factory CompareTable.fromJson(Map<String, dynamic> json) {
    return CompareTable(
      rows: readMapList(json['rows']).map(CompareRow.fromJson).toList(growable: false),
      disclaimer: readText(json['disclaimer']),
    );
  }
}
