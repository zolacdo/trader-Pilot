import 'package:flutter/foundation.dart';

import 'json_read.dart';

/// Signal tel que le Bridge le renvoie (`_signal_payload`).
@immutable
class Signal {
  const Signal({
    required this.id,
    required this.status,
    this.channelId,
    this.channelTitle,
    this.telegramMessageId,
    this.replyToMessageId,
    this.receivedAt,
    this.messageDate,
    this.rawText,
    this.symbol,
    this.normalizedSymbol,
    this.brokerSymbol,
    this.direction,
    this.orderType,
    this.entryMin,
    this.entryMax,
    this.entryPrice,
    this.stopLoss,
    this.takeProfits = const <double>[],
    this.confidence,
    this.parserSource,
    this.aiModel,
    this.rejectionReason,
    this.rejectionDetail,
    this.originalSignalId,
    this.followUpAction,
    this.followUpPayload = const <String, dynamic>{},
    this.executionMode,
    this.computedLot,
    this.riskAmount,
    this.riskReward,
    this.expiresAt,
  });

  final int id;
  final String status;
  final int? channelId;
  final String? channelTitle;
  final int? telegramMessageId;
  final int? replyToMessageId;
  final DateTime? receivedAt;
  final DateTime? messageDate;
  final String? rawText;
  final String? symbol;
  final String? normalizedSymbol;
  final String? brokerSymbol;
  final String? direction;
  final String? orderType;
  final double? entryMin;
  final double? entryMax;
  final double? entryPrice;
  final double? stopLoss;
  final List<double> takeProfits;
  final double? confidence;
  final String? parserSource;
  final String? aiModel;
  final String? rejectionReason;
  final String? rejectionDetail;
  final int? originalSignalId;
  final String? followUpAction;
  final Map<String, dynamic> followUpPayload;
  final String? executionMode;
  final double? computedLot;
  final double? riskAmount;
  final double? riskReward;
  final DateTime? expiresAt;

  factory Signal.fromJson(Map<String, dynamic> json) {
    final Map<String, dynamic> channel = readMap(json['channel']);
    return Signal(
      id: readInt(json['id']) ?? 0,
      status: readText(json['status']) ?? 'RECEIVED',
      channelId: readInt(json['channelId']),
      channelTitle: readText(channel['title']),
      telegramMessageId: readInt(json['telegramMessageId']),
      replyToMessageId: readInt(json['replyToMessageId']),
      receivedAt: readDate(json['receivedAt']),
      messageDate: readDate(json['messageDate']),
      rawText: readText(json['rawText']),
      symbol: readText(json['symbol']),
      normalizedSymbol: readText(json['normalizedSymbol']),
      brokerSymbol: readText(json['brokerSymbol']),
      direction: readText(json['direction']),
      orderType: readText(json['orderType']),
      entryMin: readDouble(json['entryMin']),
      entryMax: readDouble(json['entryMax']),
      entryPrice: readDouble(json['entryPrice']),
      stopLoss: readDouble(json['stopLoss']),
      takeProfits: readDoubleList(json['takeProfits']),
      confidence: readDouble(json['confidence']),
      parserSource: readText(json['parserSource']),
      aiModel: readText(json['aiModel']),
      rejectionReason: readText(json['rejectionReason']),
      rejectionDetail: readText(json['rejectionDetail']),
      originalSignalId: readInt(json['originalSignalId']),
      followUpAction: readText(json['followUpAction']),
      followUpPayload: readMap(json['followUpPayload']),
      executionMode: readText(json['executionMode']),
      computedLot: readDouble(json['computedLot']),
      riskAmount: readDouble(json['riskAmount']),
      riskReward: readDouble(json['riskReward']),
      expiresAt: readDate(json['expiresAt']),
    );
  }

  /// Instrument le plus parlant disponible, `null` si le parser n'a rien trouvé.
  String? get displaySymbol => normalizedSymbol ?? symbol ?? brokerSymbol;

  bool get needsReview => status == 'NEEDS_REVIEW';

  /// Un signal à valider dont le délai est dépassé n'est plus exécutable.
  bool get expired {
    final DateTime? limit = expiresAt;
    return limit != null && limit.isBefore(DateTime.now());
  }

  Duration? get remaining {
    final DateTime? limit = expiresAt;
    if (limit == null) return null;
    final Duration delta = limit.difference(DateTime.now());
    return delta.isNegative ? Duration.zero : delta;
  }

  /// Zone d'entrée : prix unique, fourchette, ou `null` si rien n'est connu.
  ({double? min, double? max, double? single}) get entry =>
      (min: entryMin, max: entryMax, single: entryPrice);
}

/// Étape de la chronologie d'un signal (`timeline` du détail).
@immutable
class SignalStep {
  const SignalStep({
    required this.stage,
    required this.success,
    this.status,
    this.message,
    this.data = const <String, dynamic>{},
    this.createdAt,
  });

  final String stage;
  final bool success;
  final String? status;
  final String? message;
  final Map<String, dynamic> data;
  final DateTime? createdAt;

  factory SignalStep.fromJson(Map<String, dynamic> json) {
    return SignalStep(
      stage: readText(json['stage']) ?? 'inconnu',
      success: readBool(json['success'], fallback: true),
      status: readText(json['status']),
      message: readText(json['message']),
      data: readMap(json['data']),
      createdAt: readDate(json['createdAt']),
    );
  }

  /// Libellé français d'une étape du pipeline (CDC section 34).
  static String label(String stage) {
    return switch (stage) {
      'received' => 'Message reçu',
      'parser' => 'Parser',
      'validation' => 'Validation',
      'risk' => 'Contrôle du risque',
      'order_check' => 'Contrôle broker (order_check)',
      'order_send' => 'Envoi de l\'ordre (order_send)',
      'execution' => 'Exécution',
      'execution_failed' => 'Échec d\'exécution',
      'executed' => 'Exécuté',
      'lifecycle' => 'Position ouverte et suivi',
      'follow_up' => 'Message de suivi',
      'manual' => 'Validation manuelle',
      'needs_review' => 'Validation manuelle requise',
      'expired' => 'Délai dépassé',
      'rejected' => 'Refus',
      'duplicate' => 'Doublon détecté',
      'observed' => 'Observation (aucun ordre)',
      'no_action' => 'Aucune intention de trade',
      'ignored' => 'Message ignoré',
      _ => stage.replaceAll('_', ' '),
    };
  }
}

/// Trade issu d'un signal.
@immutable
class SignalTrade {
  const SignalTrade({
    required this.id,
    this.ticket,
    this.symbol,
    this.direction,
    this.state,
    this.volume,
    this.initialVolume,
    this.openPrice,
    this.closePrice,
    this.stopLoss,
    this.takeProfit,
    this.profit,
    this.realizedPnl,
    this.rMultiple,
    this.breakEvenApplied = false,
    this.tpIndex,
    this.openedAt,
    this.closedAt,
    this.closeReason,
  });

  final int id;
  final int? ticket;
  final String? symbol;
  final String? direction;
  final String? state;
  final double? volume;
  final double? initialVolume;
  final double? openPrice;
  final double? closePrice;
  final double? stopLoss;
  final double? takeProfit;
  final double? profit;
  final double? realizedPnl;
  final double? rMultiple;
  final bool breakEvenApplied;
  final int? tpIndex;
  final DateTime? openedAt;
  final DateTime? closedAt;
  final String? closeReason;

  factory SignalTrade.fromJson(Map<String, dynamic> json) {
    return SignalTrade(
      id: readInt(json['id']) ?? 0,
      ticket: readInt(json['ticket']),
      symbol: readText(json['symbol']),
      direction: readText(json['direction']),
      state: readText(json['state']),
      volume: readDouble(json['volume']),
      initialVolume: readDouble(json['initialVolume']),
      openPrice: readDouble(json['openPrice']),
      closePrice: readDouble(json['closePrice']),
      stopLoss: readDouble(json['stopLoss']),
      takeProfit: readDouble(json['takeProfit']),
      profit: readDouble(json['profit']),
      realizedPnl: readDouble(json['realizedPnl']),
      rMultiple: readDouble(json['rMultiple']),
      breakEvenApplied: readBool(json['breakEvenApplied']),
      tpIndex: readInt(json['tpIndex']),
      openedAt: readDate(json['openedAt']),
      closedAt: readDate(json['closedAt']),
      closeReason: readText(json['closeReason']),
    );
  }
}

/// Ordre en attente rattaché au signal.
@immutable
class SignalPendingOrder {
  const SignalPendingOrder({
    required this.id,
    this.ticket,
    this.orderType,
    this.price,
    this.volume,
    this.state,
  });

  final int id;
  final int? ticket;
  final String? orderType;
  final double? price;
  final double? volume;
  final String? state;

  factory SignalPendingOrder.fromJson(Map<String, dynamic> json) {
    return SignalPendingOrder(
      id: readInt(json['id']) ?? 0,
      ticket: readInt(json['ticket']),
      orderType: readText(json['orderType']),
      price: readDouble(json['price']),
      volume: readDouble(json['volume']),
      state: readText(json['state']),
    );
  }
}

/// Trace d'audit rattachée au signal.
@immutable
class SignalAuditEntry {
  const SignalAuditEntry({this.createdAt, this.action, this.actor, this.details});

  final DateTime? createdAt;
  final String? action;
  final String? actor;
  final Map<String, dynamic>? details;

  factory SignalAuditEntry.fromJson(Map<String, dynamic> json) {
    final Map<String, dynamic> details = readMap(json['details']);
    return SignalAuditEntry(
      createdAt: readDate(json['createdAt']),
      action: readText(json['action']),
      actor: readText(json['actor']),
      details: details.isEmpty ? null : details,
    );
  }
}

/// Réponse complète de `GET /signals/{id}`.
@immutable
class SignalDetail {
  const SignalDetail({
    required this.signal,
    this.timeline = const <SignalStep>[],
    this.trades = const <SignalTrade>[],
    this.pendingOrders = const <SignalPendingOrder>[],
    this.followUps = const <Signal>[],
    this.audit = const <SignalAuditEntry>[],
  });

  final Signal signal;
  final List<SignalStep> timeline;
  final List<SignalTrade> trades;
  final List<SignalPendingOrder> pendingOrders;
  final List<Signal> followUps;
  final List<SignalAuditEntry> audit;

  factory SignalDetail.fromJson(Map<String, dynamic> json) {
    return SignalDetail(
      signal: Signal.fromJson(json),
      timeline: readMapList(json['timeline']).map(SignalStep.fromJson).toList(growable: false),
      trades: readMapList(json['trades']).map(SignalTrade.fromJson).toList(growable: false),
      pendingOrders:
          readMapList(json['pendingOrders']).map(SignalPendingOrder.fromJson).toList(growable: false),
      followUps: readMapList(json['followUps']).map(Signal.fromJson).toList(growable: false),
      audit: readMapList(json['audit']).map(SignalAuditEntry.fromJson).toList(growable: false),
    );
  }
}
