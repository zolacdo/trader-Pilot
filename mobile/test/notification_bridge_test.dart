import 'package:flutter_local_notifications/flutter_local_notifications.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:tradepilot/core/api/ws_client.dart';
import 'package:tradepilot/core/connection/connection_controller.dart';
import 'package:tradepilot/core/notifications/notification_service.dart';

/// Service de notification observable : il note ce qu'on lui demande
/// d'afficher, sans toucher au système Android.
class _RecordingService extends NotificationService {
  _RecordingService() : super(plugin: FlutterLocalNotificationsPlugin());

  final List<({NotificationKind kind, String title, String body, int? id})> shown =
      <({NotificationKind kind, String title, String body, int? id})>[];

  @override
  bool isEnabled(NotificationKind kind) => true;

  @override
  Future<void> show(
    NotificationKind kind,
    String title,
    String body, {
    int? notificationId,
  }) async {
    shown.add((kind: kind, title: title, body: body, id: notificationId));
  }
}

void main() {
  test('le nom d’événement suit exactement celui publié par le Bridge', () {
    // `app/services/events.py` : NOTIFICATION_CREATED = "notification.created".
    // C'est ce décalage — l'application écoutait « notification » — qui
    // faisait qu'aucune alerte n'arrivait jamais sur le téléphone.
    expect(BridgeEvents.notificationCreated, 'notification.created');
  });

  test('une notification du Bridge déclenche une alerte locale', () async {
    final WsClient ws = WsClient();
    final _RecordingService service = _RecordingService();
    final ProviderContainer container = ProviderContainer(
      overrides: <Override>[
        wsClientProvider.overrideWithValue(ws),
        notificationServiceProvider.overrideWithValue(service),
      ],
    );
    addTearDown(container.dispose);
    addTearDown(ws.dispose);

    container.read(notificationBridgeProvider);

    ws.emitForTest(
      BridgeEvent(
        type: 'notification.created',
        data: const <String, dynamic>{
          'id': 42,
          'title': '🤖 OPPORTUNITÉ DÉTECTÉE — XAUUSD',
          'body': 'XAUUSD · ACHAT',
          'category': 'OPPORTUNITY',
        },
        receivedAt: DateTime.now(),
      ),
    );
    await Future<void>.delayed(Duration.zero);

    expect(service.shown, hasLength(1));
    expect(service.shown.single.title, contains('OPPORTUNITÉ'));
    // Le type dédié évite qu'éteindre « Signal reçu » fasse taire aussi les
    // opportunités, les actualités et le calendrier.
    expect(service.shown.single.kind, NotificationKind.bridgeAlert);
    // L'identifiant voyage jusqu'à l'alerte Android : sans lui, l'appui
    // ouvrirait l'accueil au lieu du détail de la notification.
    expect(service.shown.single.id, 42);
  });

  test('les alertes du Bridge ont leur propre interrupteur', () {
    expect(NotificationKind.bridgeAlert.key, 'bridge_alert');
    expect(NotificationKind.bridgeAlert.prefKey, 'notifications.bridge_alert');
  });
}
