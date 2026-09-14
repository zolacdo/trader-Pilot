/// Modèles de la page Trades, calqués sur le contrat exact du Bridge
/// (`GET /positions`, `GET /orders`, `GET /history`).
///
/// Aucune valeur n'est inventée : ce que le Bridge ne renvoie pas reste `null`
/// et l'interface affiche « -- ».
library;

// ---------------------------------------------------------------------------
// Conversions défensives
// ---------------------------------------------------------------------------

double? asDouble(Object? raw) {
  if (raw is num) return raw.toDouble();
  if (raw is String) return double.tryParse(raw.replaceAll(',', '.'));
  return null;
}

int? asInt(Object? raw) {
  if (raw is num) return raw.toInt();
  if (raw is String) return int.tryParse(raw);
  return null;
}

bool asBool(Object? raw, {bool fallback = false}) {
  if (raw is bool) return raw;
  if (raw is num) return raw != 0;
  if (raw is String) return raw.toLowerCase() == 'true';
  return fallback;
}

String? asText(Object? raw) {
  if (raw == null) return null;
  final String value = raw.toString().trim();
  return value.isEmpty ? null : value;
}

List<double> asDoubleList(Object? raw) {
  if (raw is! List) return const <double>[];
  return raw.map(asDouble).whereType<double>().toList(growable: false);
}

List<Map<String, dynamic>> asMapList(Object? raw) {
  if (raw is! List) return const <Map<String, dynamic>>[];
  return raw
      .whereType<Map<dynamic, dynamic>>()
      .map(Map<String, dynamic>.from)
      .toList(growable: false);
}

// ---------------------------------------------------------------------------
// Position ouverte
// ---------------------------------------------------------------------------

class OpenPosition {
  const OpenPosition({
    required this.ticket,
    required this.symbol,
    required this.direction,
    required this.volume,
    required this.openPrice,
    required this.currentPrice,
    required this.stopLoss,
    required this.takeProfit,
    required this.profit,
    required this.swap,
    required this.commission,
    required this.openedAt,
    required this.signalId,
    required this.channelId,
    required this.takeProfitTargets,
    required this.tpIndex,
    required this.breakEvenApplied,
    required this.managedByTradePilot,
  });

  factory OpenPosition.fromJson(Map<String, dynamic> json) {
    return OpenPosition(
      ticket: asInt(json['ticket']) ?? 0,
      symbol: asText(json['symbol']) ?? '--',
      direction: asText(json['direction']),
      volume: asDouble(json['volume']),
      openPrice: asDouble(json['openPrice']),
      currentPrice: asDouble(json['currentPrice']),
      stopLoss: asDouble(json['stopLoss']),
      takeProfit: asDouble(json['takeProfit']),
      profit: asDouble(json['profit']),
      swap: asDouble(json['swap']),
      commission: asDouble(json['commission']),
      openedAt: asText(json['openedAt']),
      signalId: asInt(json['signalId']),
      channelId: asInt(json['channelId']),
      takeProfitTargets: asDoubleList(json['takeProfitTargets']),
      tpIndex: asInt(json['tpIndex']) ?? 0,
      breakEvenApplied: asBool(json['breakEvenApplied']),
      managedByTradePilot: asBool(json['managedByTradePilot']),
    );
  }

  final int ticket;
  final String symbol;
  final String? direction;
  final double? volume;
  final double? openPrice;
  final double? currentPrice;
  final double? stopLoss;
  final double? takeProfit;
  final double? profit;
  final double? swap;
  final double? commission;
  final String? openedAt;
  final int? signalId;
  final int? channelId;
  final List<double> takeProfitTargets;
  final int tpIndex;
  final bool breakEvenApplied;
  final bool managedByTradePilot;

  bool get isBuy => direction?.toUpperCase() == 'BUY';
}

/// Réponse complète de `GET /positions`.
class PositionsSnapshot {
  const PositionsSnapshot({required this.executionMode, required this.items});

  factory PositionsSnapshot.fromJson(Map<String, dynamic> json) {
    return PositionsSnapshot(
      executionMode: asText(json['executionMode']),
      items: asMapList(json['items']).map(OpenPosition.fromJson).toList(growable: false),
    );
  }

  final String? executionMode;
  final List<OpenPosition> items;

  /// P&L flottant total : somme des profits communiqués par le broker.
  /// Reste `null` si aucune position ne porte de profit connu.
  double? get floatingPnl {
    if (items.isEmpty) return 0;
    final Iterable<double> values = items.map((OpenPosition p) => p.profit).whereType<double>();
    if (values.isEmpty) return null;
    return values.fold<double>(0, (double sum, double value) => sum + value);
  }
}

// ---------------------------------------------------------------------------
// Ordre en attente
// ---------------------------------------------------------------------------

class PendingOrder {
  const PendingOrder({
    required this.ticket,
    required this.symbol,
    required this.orderType,
    required this.direction,
    required this.volume,
    required this.price,
    required this.stopLoss,
    required this.takeProfit,
    required this.createdAt,
    required this.expiresAt,
    required this.signalId,
    required this.managedByTradePilot,
  });

  factory PendingOrder.fromJson(Map<String, dynamic> json) {
    return PendingOrder(
      ticket: asInt(json['ticket']) ?? 0,
      symbol: asText(json['symbol']) ?? '--',
      orderType: asText(json['orderType']),
      direction: asText(json['direction']),
      volume: asDouble(json['volume']),
      price: asDouble(json['price']),
      stopLoss: asDouble(json['stopLoss']),
      takeProfit: asDouble(json['takeProfit']),
      createdAt: asText(json['createdAt']),
      expiresAt: asText(json['expiresAt']),
      signalId: asInt(json['signalId']),
      managedByTradePilot: asBool(json['managedByTradePilot']),
    );
  }

  final int ticket;
  final String symbol;
  final String? orderType;
  final String? direction;
  final double? volume;
  final double? price;
  final double? stopLoss;
  final double? takeProfit;
  final String? createdAt;
  final String? expiresAt;
  final int? signalId;
  final bool managedByTradePilot;

  /// Libellé français du type d'ordre en attente.
  String get orderTypeLabel {
    return switch (orderType) {
      'BUY_LIMIT' => 'Achat limite',
      'SELL_LIMIT' => 'Vente limite',
      'BUY_STOP' => 'Achat stop',
      'SELL_STOP' => 'Vente stop',
      'BUY_STOP_LIMIT' => 'Achat stop limite',
      'SELL_STOP_LIMIT' => 'Vente stop limite',
      'MARKET' => 'Au marché',
      _ => orderType ?? '--',
    };
  }
}

class OrdersSnapshot {
  const OrdersSnapshot({required this.executionMode, required this.items});

  factory OrdersSnapshot.fromJson(Map<String, dynamic> json) {
    return OrdersSnapshot(
      executionMode: asText(json['executionMode']),
      items: asMapList(json['items']).map(PendingOrder.fromJson).toList(growable: false),
    );
  }

  final String? executionMode;
  final List<PendingOrder> items;
}

// ---------------------------------------------------------------------------
// Trade fermé
// ---------------------------------------------------------------------------

class ClosedTrade {
  const ClosedTrade({
    required this.id,
    required this.ticket,
    required this.symbol,
    required this.direction,
    required this.volume,
    required this.openPrice,
    required this.closePrice,
    required this.stopLoss,
    required this.takeProfit,
    required this.realizedPnl,
    required this.rMultiple,
    required this.openedAt,
    required this.closedAt,
    required this.closeReason,
    required this.channelId,
    required this.signalId,
  });

  factory ClosedTrade.fromJson(Map<String, dynamic> json) {
    return ClosedTrade(
      id: asInt(json['id']),
      ticket: asInt(json['ticket']) ?? 0,
      symbol: asText(json['symbol']) ?? '--',
      direction: asText(json['direction']),
      volume: asDouble(json['volume']),
      openPrice: asDouble(json['openPrice']),
      closePrice: asDouble(json['closePrice']),
      stopLoss: asDouble(json['stopLoss']),
      takeProfit: asDouble(json['takeProfit']),
      realizedPnl: asDouble(json['realizedPnl']),
      rMultiple: asDouble(json['rMultiple']),
      openedAt: asText(json['openedAt']),
      closedAt: asText(json['closedAt']),
      closeReason: asText(json['closeReason']),
      channelId: asInt(json['channelId']),
      signalId: asInt(json['signalId']),
    );
  }

  final int? id;
  final int ticket;
  final String symbol;
  final String? direction;
  final double? volume;
  final double? openPrice;
  final double? closePrice;
  final double? stopLoss;
  final double? takeProfit;
  final double? realizedPnl;
  final double? rMultiple;
  final String? openedAt;
  final String? closedAt;
  final String? closeReason;
  final int? channelId;
  final int? signalId;
}

/// Page d'historique : les éléments accumulés et l'état de la pagination.
class ClosedTradesPage {
  const ClosedTradesPage({
    this.items = const <ClosedTrade>[],
    this.days = 30,
    this.hasMore = false,
    this.loadingMore = false,
  });

  final List<ClosedTrade> items;
  final int days;
  final bool hasMore;
  final bool loadingMore;

  ClosedTradesPage copyWith({
    List<ClosedTrade>? items,
    int? days,
    bool? hasMore,
    bool? loadingMore,
  }) {
    return ClosedTradesPage(
      items: items ?? this.items,
      days: days ?? this.days,
      hasMore: hasMore ?? this.hasMore,
      loadingMore: loadingMore ?? this.loadingMore,
    );
  }
}
