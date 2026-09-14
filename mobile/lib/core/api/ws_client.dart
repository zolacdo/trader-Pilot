import 'dart:async';
import 'dart:convert';
import 'dart:math';

import 'package:flutter/foundation.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

import 'endpoints.dart';

/// Evenement pousse par le Bridge : `{type, ts, data}`.
@immutable
class BridgeEvent {
  const BridgeEvent({required this.type, required this.data, required this.receivedAt});

  final String type;
  final Map<String, dynamic> data;
  final DateTime receivedAt;

  factory BridgeEvent.fromJson(Map<String, dynamic> json) {
    final Object? payload = json['data'];
    return BridgeEvent(
      type: (json['type'] ?? 'unknown').toString(),
      data: payload is Map ? Map<String, dynamic>.from(payload) : <String, dynamic>{},
      receivedAt: DateTime.now(),
    );
  }

  @override
  String toString() => 'BridgeEvent($type)';
}

enum WsStatus { disconnected, connecting, connected }

/// Noms d'evenements emis par le Bridge.
abstract final class BridgeEvents {
  static const String hello = 'hello';
  static const String ping = 'ping';
  static const String signalNew = 'signal.new';
  static const String signalUpdated = 'signal.updated';
  static const String signalRejected = 'signal.rejected';
  static const String signalNeedsReview = 'signal.needs_review';
  static const String positionOpened = 'position.opened';
  static const String positionUpdated = 'position.updated';
  static const String positionClosed = 'position.closed';
  static const String orderPlaced = 'order.placed';
  static const String orderCancelled = 'order.cancelled';
  static const String accountUpdated = 'account.updated';
  static const String pnlUpdated = 'pnl.updated';
  static const String mt5Status = 'mt5.status';
  static const String telegramStatus = 'telegram.status';
  static const String openrouterStatus = 'openrouter.status';
  static const String tunnelStatus = 'tunnel.status';
  static const String tradingState = 'trading.state';
  static const String channelUpdated = 'channel.updated';
  static const String channelAnalysis = 'channel.analysis';
  // --- Intelligence de marche (CDC2 section 99) ---
  static const String localAiStatus = 'local_ai.status';
  static const String aiRouting = 'ai.routing';
  static const String aiConsensus = 'ai.consensus';
  static const String aiDisagreement = 'ai.disagreement';
  static const String marketUpdate = 'market.update';
  static const String opportunityCreated = 'opportunity.created';
  static const String decisionCreated = 'decision.created';
  static const String newsHighImpact = 'news.high_impact';
  static const String economicEvent = 'economic.event';
  static const String tradeExecuted = 'trade.executed';
  static const String tradeClosed = 'trade.closed';
  static const String riskBreaker = 'risk.breaker';
  static const String notificationCreated = 'notification.created';

  static const String journal = 'journal';
  static const String error = 'error';
  static const String notification = 'notification';
}

/// Connexion WebSocket avec reconnexion automatique a delai croissant.
class WsClient {
  WsClient();

  static const List<int> _backoffSeconds = <int>[1, 2, 5, 10, 20, 30, 60];

  WebSocketChannel? _channel;
  StreamSubscription<dynamic>? _subscription;
  Timer? _reconnectTimer;
  Timer? _watchdog;
  String? _baseUrl;
  String? _token;
  int _attempt = 0;
  bool _manuallyClosed = false;
  DateTime? _lastMessageAt;

  final StreamController<BridgeEvent> _events = StreamController<BridgeEvent>.broadcast();
  final ValueNotifier<WsStatus> status = ValueNotifier<WsStatus>(WsStatus.disconnected);

  Stream<BridgeEvent> get events => _events.stream;

  /// Injecte un evenement sans socket. Reserve aux tests : il permet de
  /// verifier le branchement des notifications sans Bridge ni reseau.
  @visibleForTesting
  void emitForTest(BridgeEvent event) => _events.add(event);

  DateTime? get lastMessageAt => _lastMessageAt;

  /// Flux filtre sur un ou plusieurs types d'evenements.
  Stream<BridgeEvent> on(Set<String> types) =>
      _events.stream.where((event) => types.contains(event.type));

  void connect({required String baseUrl, required String token}) {
    _baseUrl = baseUrl;
    _token = token;
    _manuallyClosed = false;
    _attempt = 0;
    _open();
  }

  void _open() {
    if (_manuallyClosed || _baseUrl == null || _token == null) return;
    _cleanupSocket();
    status.value = WsStatus.connecting;

    final Uri uri = _buildUri(_baseUrl!, _token!);
    try {
      final WebSocketChannel channel = WebSocketChannel.connect(uri);
      _channel = channel;
      _subscription = channel.stream.listen(
        _onData,
        onError: (Object error) => _scheduleReconnect(),
        onDone: _scheduleReconnect,
        cancelOnError: true,
      );
      _startWatchdog();
    } catch (_) {
      _scheduleReconnect();
    }
  }

  static Uri _buildUri(String baseUrl, String token) {
    final Uri http = Uri.parse(baseUrl);
    return http.replace(
      scheme: http.scheme == 'https' ? 'wss' : 'ws',
      path: Endpoints.websocket,
      queryParameters: <String, String>{'token': token},
    );
  }

  void _onData(dynamic raw) {
    _lastMessageAt = DateTime.now();
    if (status.value != WsStatus.connected) {
      status.value = WsStatus.connected;
      _attempt = 0;
    }
    if (raw is! String) return;
    try {
      final Object? decoded = jsonDecode(raw);
      if (decoded is Map<String, dynamic>) {
        final BridgeEvent event = BridgeEvent.fromJson(decoded);
        if (event.type != BridgeEvents.ping) {
          _events.add(event);
        }
      }
    } catch (_) {
      // Un message illisible ne doit jamais casser le flux.
    }
  }

  /// Detecte une connexion muette (reseau mobile qui bascule sans fermeture).
  void _startWatchdog() {
    _watchdog?.cancel();
    _watchdog = Timer.periodic(const Duration(seconds: 45), (_) {
      final DateTime? last = _lastMessageAt;
      if (last == null) return;
      if (DateTime.now().difference(last) > const Duration(seconds: 75)) {
        _scheduleReconnect();
      }
    });
  }

  void _scheduleReconnect() {
    if (_manuallyClosed) return;
    _cleanupSocket();
    status.value = WsStatus.disconnected;
    if (_reconnectTimer?.isActive ?? false) return;

    final int seconds = _backoffSeconds[min(_attempt, _backoffSeconds.length - 1)];
    _attempt++;
    _reconnectTimer = Timer(Duration(seconds: seconds), _open);
  }

  void _cleanupSocket() {
    _watchdog?.cancel();
    _watchdog = null;
    _subscription?.cancel();
    _subscription = null;
    _channel?.sink.close();
    _channel = null;
  }

  void disconnect() {
    _manuallyClosed = true;
    _reconnectTimer?.cancel();
    _reconnectTimer = null;
    _cleanupSocket();
    status.value = WsStatus.disconnected;
  }

  /// Force une tentative immediate (bouton "Reessayer").
  void retryNow() {
    _reconnectTimer?.cancel();
    _attempt = 0;
    _manuallyClosed = false;
    _open();
  }

  void dispose() {
    disconnect();
    _events.close();
    status.dispose();
  }
}
