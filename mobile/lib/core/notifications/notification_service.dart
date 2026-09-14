import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../api/ws_client.dart';
import '../connection/connection_controller.dart';

/// Types de notifications proposes a l'utilisateur (CDC section 45).
enum NotificationKind {
  signalReceived('signal_received', 'Signal reçu'),
  signalRejected('signal_rejected', 'Signal refusé'),
  tradeOpened('trade_opened', 'Trade ouvert'),
  takeProfitHit('take_profit_hit', 'Take profit atteint'),
  stopLossHit('stop_loss_hit', 'Stop loss atteint'),
  tradeClosed('trade_closed', 'Trade fermé'),
  lossLimit('loss_limit', 'Limite de perte atteinte'),
  automationPaused('automation_paused', 'Automatisation suspendue'),
  bridgeOffline('bridge_offline', 'Bridge hors ligne'),
  mt5Offline('mt5_offline', 'MetaTrader hors ligne'),

  /// Alertes produites par l'intelligence du Bridge : opportunités détectées,
  /// actualités à fort impact, événements économiques, rapports.
  ///
  /// Sans ce type dédié, ces alertes empruntaient celui des signaux Telegram :
  /// couper « Signal reçu » les faisait toutes disparaître.
  bridgeAlert('bridge_alert', 'Alertes du Bridge');

  const NotificationKind(this.key, this.label);

  final String key;
  final String label;

  String get prefKey => 'notifications.$key';
}

/// Notifications locales declenchees par les evenements du Bridge.
class NotificationService {
  NotificationService({FlutterLocalNotificationsPlugin? plugin})
      : _plugin = plugin ?? FlutterLocalNotificationsPlugin();

  static const AndroidNotificationDetails _androidDetails = AndroidNotificationDetails(
    'tradepilot_events',
    'Événements TradePilot',
    channelDescription: 'Signaux, trades et alertes de risque',
    importance: Importance.high,
    priority: Priority.high,
    playSound: true,
  );

  final FlutterLocalNotificationsPlugin _plugin;
  bool _ready = false;
  int _counter = 0;

  /// Identifiant de la notification ouverte par l'utilisateur.
  ///
  /// Un `ValueNotifier` plutot qu'un `Stream` : quand l'application est lancee
  /// depuis une notification alors qu'elle etait fermee, le routeur n'est pas
  /// encore pret. La valeur reste donc disponible jusqu'a ce qu'il la lise.
  final ValueNotifier<int?> opened = ValueNotifier<int?>(null);

  /// Preferences d'activation, chargees une fois puis mises en cache.
  final Map<String, bool> _enabled = <String, bool>{};

  Future<void> initialize() async {
    if (_ready) return;
    const InitializationSettings settings = InitializationSettings(
      android: AndroidInitializationSettings('@mipmap/ic_launcher'),
    );
    try {
      await _plugin.initialize(
        settings,
        onDidReceiveNotificationResponse: _onTap,
      );
      await _plugin
          .resolvePlatformSpecificImplementation<AndroidFlutterLocalNotificationsPlugin>()
          ?.requestNotificationsPermission();

      // Application lancee par un appui sur la notification alors qu'elle
      // etait fermee : le clic n'est jamais transmis a `onDidReceive`.
      final NotificationAppLaunchDetails? launch =
          await _plugin.getNotificationAppLaunchDetails();
      if (launch?.didNotificationLaunchApp ?? false) {
        _onTap(launch!.notificationResponse ?? const NotificationResponse(
          notificationResponseType: NotificationResponseType.selectedNotification,
        ));
      }
      _ready = true;
    } catch (error) {
      // L'absence de notifications ne doit jamais empecher l'application de
      // fonctionner : on continue silencieusement.
      debugPrint('Notifications indisponibles : $error');
    }
    await _loadPreferences();
  }

  Future<void> _loadPreferences() async {
    try {
      final SharedPreferences prefs = await SharedPreferences.getInstance();
      for (final NotificationKind kind in NotificationKind.values) {
        _enabled[kind.key] = prefs.getBool(kind.prefKey) ?? true;
      }
    } catch (_) {
      for (final NotificationKind kind in NotificationKind.values) {
        _enabled[kind.key] = true;
      }
    }
  }

  bool isEnabled(NotificationKind kind) => _enabled[kind.key] ?? true;

  Future<void> setEnabled(NotificationKind kind, bool value) async {
    _enabled[kind.key] = value;
    final SharedPreferences prefs = await SharedPreferences.getInstance();
    await prefs.setBool(kind.prefKey, value);
  }

  /// Affiche une alerte locale.
  ///
  /// ``notificationId`` est l'identifiant cote Bridge : il voyage dans le
  /// `payload` pour que l'appui ouvre le detail exact, et non l'accueil.
  Future<void> show(
    NotificationKind kind,
    String title,
    String body, {
    int? notificationId,
  }) async {
    if (!_ready || !isEnabled(kind)) return;
    _counter = (_counter + 1) % 100000;
    try {
      await _plugin.show(
        _counter,
        title,
        body,
        const NotificationDetails(android: _androidDetails),
        payload: notificationId?.toString(),
      );
    } catch (error) {
      debugPrint('Notification non affichee : $error');
    }
  }

  void _onTap(NotificationResponse response) {
    final int? id = int.tryParse(response.payload ?? '');
    // Sans identifiant exploitable, on ouvre quand meme l'inbox : mieux vaut
    // la liste que rien du tout.
    opened.value = id ?? -1;
  }

  /// Marque l'ouverture comme traitee, pour qu'elle ne rejoue pas.
  void clearOpened() => opened.value = null;

  Future<void> cancelAll() async {
    if (!_ready) return;
    await _plugin.cancelAll();
  }
}

final Provider<NotificationService> notificationServiceProvider = Provider<NotificationService>((ref) {
  return NotificationService();
});

/// Convertit les evenements temps reel du Bridge en notifications.
///
/// Uniquement des evenements deja survenus cote Bridge : l'application ne
/// declenche jamais d'action de trading depuis une notification.
final Provider<void> notificationBridgeProvider = Provider<void>((ref) {
  final WsClient ws = ref.watch(wsClientProvider);
  final NotificationService service = ref.watch(notificationServiceProvider);

  final StreamSubscription<BridgeEvent> subscription = ws.events.listen((BridgeEvent event) {
    switch (event.type) {
      case BridgeEvents.signalNew:
        final String symbol = (event.data['symbol'] ?? 'Signal').toString();
        final String direction = (event.data['direction'] ?? '').toString();
        service.show(
          NotificationKind.signalReceived,
          'Nouveau signal',
          '$symbol $direction'.trim(),
        );
      case BridgeEvents.signalRejected:
        service.show(
          NotificationKind.signalRejected,
          'Signal refusé',
          (event.data['detail'] ?? event.data['reason'] ?? 'Refusé par le moteur de risque').toString(),
        );
      case BridgeEvents.positionOpened:
        service.show(
          NotificationKind.tradeOpened,
          'Position ouverte',
          'Ticket ${event.data['ticket'] ?? '--'} - ${event.data['volume'] ?? ''} lot(s)',
        );
      case BridgeEvents.positionClosed:
        final Object? profit = event.data['profit'];
        service.show(
          NotificationKind.tradeClosed,
          'Position fermée',
          '${event.data['symbol'] ?? ''} ${profit == null ? '' : 'résultat $profit'}'.trim(),
        );
      case BridgeEvents.tradingState:
        if (event.data['paused'] == true) {
          service.show(
            NotificationKind.automationPaused,
            'Automatisation suspendue',
            (event.data['reason'] ?? 'Le trading automatique est en pause').toString(),
          );
        }
      case BridgeEvents.mt5Status:
        if (event.data['state'] == 'DISCONNECTED') {
          service.show(
            NotificationKind.mt5Offline,
            'MetaTrader hors ligne',
            'Le terminal ne répond plus : aucun ordre ne peut être envoyé.',
          );
        }
      // Le Bridge publie « notification.created ». L'ancien nom est
      // conservé par compatibilité : une version antérieure du Bridge peut
      // encore l'émettre.
      case BridgeEvents.notificationCreated:
      case BridgeEvents.notification:
        final Object? id = event.data['id'];
        service.show(
          NotificationKind.bridgeAlert,
          (event.data['title'] ?? 'TradePilot').toString(),
          (event.data['body'] ?? '').toString(),
          notificationId: id is int ? id : int.tryParse('$id'),
        );
    }
  });

  ref.onDispose(subscription.cancel);
});
