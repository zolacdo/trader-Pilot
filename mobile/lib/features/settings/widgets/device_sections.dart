import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/build_info.dart';
import '../../../core/theme/app_theme.dart';
import '../../../core/widgets/app_widgets.dart';
import '../settings_preferences.dart';
import '../settings_providers.dart';
import 'settings_shell.dart';

/// Section Apparence : thème clair, sombre ou celui du téléphone.
class AppearanceSection extends ConsumerWidget {
  const AppearanceSection({super.key});

  static const List<SettingsOption<String>> _themes = <SettingsOption<String>>[
    SettingsOption<String>(
      value: 'system',
      label: 'Comme le téléphone',
      description: 'Suit le réglage clair ou sombre du système Android.',
    ),
    SettingsOption<String>(
      value: 'light',
      label: 'Clair',
      description: 'Fond blanc, lisible en plein jour.',
    ),
    SettingsOption<String>(
      value: 'dark',
      label: 'Sombre',
      description: 'Fond sombre, plus confortable le soir.',
    ),
  ];

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final AppPreferences preferences = ref.watch(preferencesProvider);

    return SettingsSection(
      title: 'Apparence',
      subtitle: 'Le thème de l\'application, enregistré sur ce téléphone.',
      children: <Widget>[
        SettingsChoice<String>(
          options: _themes,
          selected: preferences.theme,
          onChanged: (String value) {
            ref.read(preferencesProvider.notifier).setTheme(value);
            showToast(context, 'Thème enregistré, appliqué au prochain lancement.');
          },
        ),
        const SettingsNote(
          text: 'Ce choix est enregistré immédiatement mais s\'applique au prochain démarrage de '
              'l\'application : l\'écran actuel ne change pas de couleur tout de suite.',
        ),
      ],
    );
  }
}

/// Section Notifications : quels événements méritent d'interrompre l'utilisateur.
class NotificationsSection extends ConsumerWidget {
  const NotificationsSection({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final AppPreferences preferences = ref.watch(preferencesProvider);

    return SettingsSection(
      title: 'Notifications',
      subtitle: 'Ce dont le téléphone doit vous avertir.',
      children: <Widget>[
        for (final NotificationKind kind in notificationKinds)
          SwitchListTile(
            contentPadding: EdgeInsets.zero,
            value: preferences.notificationEnabled(kind.key),
            onChanged: (bool value) =>
                ref.read(preferencesProvider.notifier).setNotification(kind.key, value),
            title: Text(kind.label, style: Theme.of(context).textTheme.titleMedium),
            subtitle: Text(kind.description, style: Theme.of(context).textTheme.bodySmall),
          ),
        const SettingsNote(
          text: 'Ces choix sont enregistrés sur le téléphone. Android peut malgré tout limiter '
              'les notifications si l\'application est mise en veille par l\'économiseur de '
              'batterie.',
        ),
      ],
    );
  }
}

/// Section À propos : versions réellement en place.
class AboutSection extends StatelessWidget {
  const AboutSection({super.key, required this.status});

  final Map<String, dynamic> status;

  @override
  Widget build(BuildContext context) {
    final Object? bridge = status['bridge'];
    final Map<String, dynamic> info =
        bridge is Map ? Map<String, dynamic>.from(bridge) : <String, dynamic>{};

    return SettingsSection(
      title: 'À propos',
      subtitle: 'Les versions installées de chaque partie.',
      children: <Widget>[
        const DetailRow(label: 'Application mobile', value: mobileAppVersion),
        // Sans ces deux lignes, deux binaires différents affichaient la même
        // version : il fallait un câble et un md5sum pour les distinguer.
        DetailRow(label: 'Compilée le', value: BuildInfo.label),
        DetailRow(label: 'Empreinte', value: BuildInfo.shortFingerprint),
        DetailRow(label: 'Bridge', value: info['version']?.toString() ?? '--'),
        DetailRow(label: 'API du Bridge', value: info['apiVersion']?.toString() ?? '--'),
        DetailRow(label: 'Python du Bridge', value: info['python']?.toString() ?? '--'),
        const SizedBox(height: AppSpacing.sm),
        Text(
          'TradePilot copie des signaux de trading. Il ne garantit aucun résultat et ne remplace '
          'pas votre jugement.',
          style: Theme.of(context).textTheme.bodySmall,
        ),
      ],
    );
  }
}
