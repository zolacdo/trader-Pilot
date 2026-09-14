import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Un type d'événement pouvant déclencher une notification locale.
class NotificationKind {
  const NotificationKind(this.key, this.label, this.description);

  final String key;
  final String label;
  final String description;
}

/// Liste des notifications proposées (CDC section 45).
const List<NotificationKind> notificationKinds = <NotificationKind>[
  NotificationKind('signal_received', 'Signal reçu',
      'Un canal suivi vient de publier un signal exploitable.'),
  NotificationKind('signal_rejected', 'Signal refusé',
      'Un signal a été écarté par le moteur de risque, avec son motif.'),
  NotificationKind('trade_opened', 'Trade ouvert', 'Une position vient d\'être ouverte.'),
  NotificationKind('tp_hit', 'Take profit atteint', 'Un objectif de gain a été touché.'),
  NotificationKind('sl_hit', 'Stop loss atteint', 'Une position a été coupée en perte.'),
  NotificationKind('trade_closed', 'Trade fermé', 'Une position a été clôturée, quelle qu\'en soit la raison.'),
  NotificationKind('loss_limit', 'Limite de perte atteinte',
      'La perte journalière maximale est atteinte : plus aucun trade n\'est ouvert.'),
  NotificationKind('auto_paused', 'Auto trading suspendu',
      'L\'automatisation s\'est mise en pause toute seule.'),
  NotificationKind('bridge_offline', 'Bridge hors ligne',
      'Le téléphone ne joint plus le Bridge : plus aucune donnée temps réel.'),
  NotificationKind('mt5_offline', 'MetaTrader hors ligne',
      'Le terminal MetaTrader 5 ne répond plus : aucun ordre ne peut partir.'),
];

/// Préférences stockées sur le téléphone, jamais sur le Bridge.
class AppPreferences {
  const AppPreferences({
    this.theme = 'system',
    this.notifications = const <String, bool>{},
    this.loaded = false,
  });

  /// `light`, `dark` ou `system`.
  final String theme;
  final Map<String, bool> notifications;
  final bool loaded;

  bool notificationEnabled(String key) => notifications[key] ?? true;

  AppPreferences copyWith({String? theme, Map<String, bool>? notifications, bool? loaded}) {
    return AppPreferences(
      theme: theme ?? this.theme,
      notifications: notifications ?? this.notifications,
      loaded: loaded ?? this.loaded,
    );
  }
}

class PreferencesController extends StateNotifier<AppPreferences> {
  PreferencesController() : super(const AppPreferences()) {
    _restore();
  }

  static const String themeKey = 'ui.theme';
  static const String notificationPrefix = 'notify.';

  Future<void> _restore() async {
    final SharedPreferences prefs = await SharedPreferences.getInstance();
    final Map<String, bool> notifications = <String, bool>{};
    for (final NotificationKind kind in notificationKinds) {
      notifications[kind.key] = prefs.getBool('$notificationPrefix${kind.key}') ?? true;
    }
    if (!mounted) return;
    state = AppPreferences(
      theme: prefs.getString(themeKey) ?? 'system',
      notifications: notifications,
      loaded: true,
    );
  }

  Future<void> setTheme(String theme) async {
    state = state.copyWith(theme: theme);
    final SharedPreferences prefs = await SharedPreferences.getInstance();
    await prefs.setString(themeKey, theme);
  }

  Future<void> setNotification(String key, bool enabled) async {
    final Map<String, bool> updated = Map<String, bool>.from(state.notifications)..[key] = enabled;
    state = state.copyWith(notifications: updated);
    final SharedPreferences prefs = await SharedPreferences.getInstance();
    await prefs.setBool('$notificationPrefix$key', enabled);
  }
}

final StateNotifierProvider<PreferencesController, AppPreferences> preferencesProvider =
    StateNotifierProvider<PreferencesController, AppPreferences>(
  (Ref<Object?> ref) => PreferencesController(),
);
