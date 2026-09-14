import '../../../core/widgets/app_widgets.dart';

/// Libellés français des états renvoyés par le Bridge.
///
/// Les valeurs techniques (`CONNECTED`, `MT5_LIVE`, `DEMO`) ne sont jamais
/// affichées telles quelles : l'utilisateur lit toujours une phrase claire.
abstract final class BridgeLabels {
  /// État d'une liaison (`ConnectionState` côté Bridge).
  static String connection(String? state) {
    return switch (state) {
      'CONNECTED' => 'Connecté',
      'CONNECTING' => 'Connexion en cours',
      'DISCONNECTED' => 'Déconnecté',
      'ERROR' => 'En erreur',
      'NOT_CONFIGURED' => 'Non configuré',
      _ => 'Inconnu',
    };
  }

  static bool isConnected(String? state) => state == 'CONNECTED';

  /// Ton de la pastille associée à un état de liaison.
  static StatusTone connectionTone(String? state) {
    return switch (state) {
      'CONNECTED' => StatusTone.good,
      'CONNECTING' => StatusTone.warning,
      'ERROR' || 'DISCONNECTED' => StatusTone.bad,
      _ => StatusTone.neutral,
    };
  }

  /// Mode d'exécution, avec l'accentuation française attendue.
  static String executionMode(String? mode) {
    return switch (mode) {
      'PAPER' => 'PAPER',
      'MT5_DEMO' => 'MT5 Démo',
      'MT5_LIVE' => 'MT5 Réel',
      _ => '--',
    };
  }

  /// Phrase explicative du mode d'exécution.
  static String executionModeDetail(String? mode) {
    return switch (mode) {
      'PAPER' => 'Simulation locale : aucun ordre n\'est envoyé au broker.',
      'MT5_DEMO' => 'Ordres envoyés sur un compte de démonstration MetaTrader 5.',
      'MT5_LIVE' => 'Ordres envoyés sur un compte réel : de l\'argent est engagé.',
      _ => 'Mode d\'exécution inconnu.',
    };
  }

  /// Type de compte réellement utilisé (`AccountKind`).
  static String accountKind(String? kind) {
    return switch (kind) {
      'DEMO' => 'Compte démo',
      'REAL' => 'Compte réel',
      _ => 'Type de compte inconnu',
    };
  }

  static StatusTone accountTone(String? kind) {
    return switch (kind) {
      'DEMO' => StatusTone.neutral,
      'REAL' => StatusTone.bad,
      _ => StatusTone.warning,
    };
  }

  /// Masque un identifiant de compte : seuls les 4 derniers chiffres restent.
  static String maskedLogin(Object? login) {
    final String value = login?.toString().trim() ?? '';
    if (value.isEmpty) return '--';
    if (value.length <= 4) return '*' * value.length;
    return '***${value.substring(value.length - 4)}';
  }

  /// Niveau d'un événement du journal.
  static String eventLevel(String? level) {
    return switch (level) {
      'DEBUG' => 'Détail',
      'INFO' => 'Information',
      'WARNING' => 'Avertissement',
      'ERROR' => 'Erreur',
      'CRITICAL' => 'Critique',
      _ => '--',
    };
  }

  static StatusTone eventTone(String? level) {
    return switch (level) {
      'WARNING' => StatusTone.warning,
      'ERROR' || 'CRITICAL' => StatusTone.bad,
      _ => StatusTone.neutral,
    };
  }
}
