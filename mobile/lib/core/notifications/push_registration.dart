import 'dart:async';

import 'package:firebase_core/firebase_core.dart';
import 'package:firebase_messaging/firebase_messaging.dart';

import '../api/api_client.dart';
import '../api/endpoints.dart';

/// Enregistrement du téléphone auprès de Firebase, puis du Bridge.
///
/// Sans cette pièce, le Bridge créait bien ses notifications mais les marquait
/// toutes `PUSH_TRANSPORT_UNAVAILABLE` : elles n'arrivaient que par WebSocket,
/// donc uniquement quand l'application était ouverte. Une alerte produite la
/// nuit n'atteignait jamais personne.
///
/// Le jeton FCM identifie CE téléphone. Il change tout seul — réinstallation,
/// restauration, nettoyage des données de l'application — d'où l'écoute de
/// `onTokenRefresh` : un jeton périmé fait échouer l'envoi en silence.
class PushRegistration {
  PushRegistration(this._api);

  final ApiClient _api;

  StreamSubscription<String>? _refreshSubscription;
  String? _dernierJetonEnvoye;

  /// Ce que l'utilisateur a répondu à la demande d'autorisation.
  AuthorizationStatus? autorisation;

  /// Raison d'un échec, affichable telle quelle. `null` si tout va bien.
  String? erreur;

  bool get pret => erreur == null && _dernierJetonEnvoye != null;

  /// Initialise Firebase, demande l'autorisation, transmet le jeton.
  ///
  /// Ne lève jamais : une panne de push ne doit pas empêcher l'application de
  /// démarrer. L'échec est conservé dans [erreur] pour être montré à l'écran
  /// de diagnostic plutôt que perdu dans les journaux.
  Future<void> initialiser() async {
    try {
      await Firebase.initializeApp();
    } catch (exception) {
      erreur = 'Firebase indisponible : $exception';
      return;
    }

    final FirebaseMessaging messagerie = FirebaseMessaging.instance;

    try {
      final NotificationSettings reglages = await messagerie.requestPermission(
        alert: true,
        badge: true,
        sound: true,
      );
      autorisation = reglages.authorizationStatus;
      if (reglages.authorizationStatus == AuthorizationStatus.denied) {
        erreur = 'Notifications refusées sur ce téléphone.';
        return;
      }
    } catch (exception) {
      erreur = 'Autorisation impossible : $exception';
      return;
    }

    try {
      final String? jeton = await messagerie.getToken();
      if (jeton == null || jeton.isEmpty) {
        erreur = 'Firebase n’a pas délivré de jeton pour cet appareil.';
        return;
      }
      await _transmettre(jeton);
    } catch (exception) {
      erreur = 'Jeton indisponible : $exception';
      return;
    }

    // Un jeton peut être remplacé sans prévenir : on suit les changements
    // plutôt que de laisser le Bridge pousser vers une adresse morte.
    _refreshSubscription?.cancel();
    _refreshSubscription = messagerie.onTokenRefresh.listen(
      _transmettre,
      onError: (Object exception) => erreur = 'Rafraîchissement du jeton : $exception',
    );
  }

  Future<void> _transmettre(String jeton) async {
    if (jeton == _dernierJetonEnvoye) return;
    try {
      // Le Bridge attend exactement `token` (PushTokenRequest) : envoyer un
      // autre nom fait répondre 422 sans que rien ne soit enregistré.
      await _api.postJson(
        Endpoints.pushToken,
        body: <String, dynamic>{'token': jeton},
      );
      _dernierJetonEnvoye = jeton;
      erreur = null;
    } catch (exception) {
      // Le jeton reste valide côté Firebase : c'est le Bridge qui n'a pas
      // répondu. On ne le mémorise donc pas, pour réessayer au prochain tour.
      erreur = 'Bridge injoignable pour l’enregistrement du jeton : $exception';
    }
  }

  void dispose() {
    _refreshSubscription?.cancel();
    _refreshSubscription = null;
  }
}
