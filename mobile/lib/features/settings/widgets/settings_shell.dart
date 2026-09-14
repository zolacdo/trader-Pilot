import 'package:flutter/material.dart';

import '../../../core/theme/app_colors.dart';
import '../../../core/theme/app_theme.dart';
import '../../../core/widgets/app_widgets.dart';

/// Bloc de réglages : un titre, une phrase d'explication, du contenu.
class SettingsSection extends StatelessWidget {
  const SettingsSection({
    super.key,
    required this.title,
    required this.subtitle,
    required this.children,
    this.accent = false,
  });

  final String title;
  final String subtitle;
  final List<Widget> children;
  final bool accent;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: AppSpacing.lg),
      child: AppCard(
        accent: accent,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: <Widget>[
            SectionHeader(title: title, subtitle: subtitle),
            ...children,
          ],
        ),
      ),
    );
  }
}

/// Encadré explicatif ou avertissement.
class SettingsNote extends StatelessWidget {
  const SettingsNote({super.key, required this.text, this.warning = false});

  final String text;
  final bool warning;

  @override
  Widget build(BuildContext context) {
    final bool dark = Theme.of(context).brightness == Brightness.dark;
    return Container(
      width: double.infinity,
      margin: const EdgeInsets.symmetric(vertical: AppSpacing.sm),
      padding: const EdgeInsets.all(AppSpacing.md),
      decoration: BoxDecoration(
        color: warning
            ? (dark ? AppColors.warning.withValues(alpha: 0.14) : AppColors.warningSurface)
            : (dark ? AppColors.surfaceMutedDark : AppColors.surfaceMuted),
        borderRadius: BorderRadius.circular(AppSpacing.radiusSmall),
      ),
      child: Text(
        text,
        style: Theme.of(context).textTheme.bodySmall?.copyWith(
              color: warning
                  ? (dark ? const Color(0xFFFBBF24) : AppColors.warning)
                  : (dark ? AppColors.textSecondaryDark : AppColors.textSecondary),
            ),
      ),
    );
  }
}

/// Option d'un choix exclusif expliqué.
class SettingsOption<T> {
  const SettingsOption({
    required this.value,
    required this.label,
    required this.description,
    this.warning = false,
  });

  final T value;
  final String label;
  final String description;
  final bool warning;
}

/// Choix exclusif : une option sélectionnée, chacune expliquée.
class SettingsChoice<T> extends StatelessWidget {
  const SettingsChoice({
    super.key,
    required this.options,
    required this.selected,
    required this.onChanged,
    this.enabled = true,
  });

  final List<SettingsOption<T>> options;
  final T? selected;
  final ValueChanged<T> onChanged;
  final bool enabled;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    return Column(
      children: <Widget>[
        for (final SettingsOption<T> option in options)
          Padding(
            padding: const EdgeInsets.only(bottom: AppSpacing.sm),
            child: InkWell(
              borderRadius: BorderRadius.circular(AppSpacing.radiusSmall),
              onTap: enabled ? () => onChanged(option.value) : null,
              child: Container(
                padding: const EdgeInsets.all(AppSpacing.md),
                decoration: BoxDecoration(
                  borderRadius: BorderRadius.circular(AppSpacing.radiusSmall),
                  border: Border.all(
                    color: option.value == selected
                        ? AppColors.primary
                        : theme.colorScheme.outline,
                    width: option.value == selected ? 1.4 : 1,
                  ),
                ),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: <Widget>[
                    Icon(
                      option.value == selected
                          ? Icons.radio_button_checked
                          : Icons.radio_button_unchecked,
                      size: 19,
                      color: option.value == selected ? AppColors.primary : AppColors.textTertiary,
                    ),
                    const SizedBox(width: AppSpacing.md),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: <Widget>[
                          Row(
                            children: <Widget>[
                              Expanded(
                                child: Text(
                                  option.label,
                                  style: theme.textTheme.bodyMedium
                                      ?.copyWith(fontWeight: FontWeight.w600),
                                ),
                              ),
                              if (option.warning)
                                const StatusChip(
                                  label: 'Argent réel',
                                  tone: StatusTone.warning,
                                  dense: true,
                                ),
                            ],
                          ),
                          const SizedBox(height: 2),
                          Text(option.description, style: theme.textTheme.bodySmall),
                        ],
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ),
      ],
    );
  }
}

/// Libellé français d'un mode d'exécution.
String executionModeLabel(String? mode) {
  return switch (mode) {
    'PAPER' => 'Paper trading',
    'MT5_DEMO' => 'MT5 démo',
    'MT5_LIVE' => 'MT5 réel',
    null => '--',
    _ => mode,
  };
}

/// Libellé français d'un état de connexion renvoyé par le Bridge.
String connectionStateLabel(String? state) {
  return switch (state) {
    'CONNECTED' => 'Connecté',
    'CONNECTING' => 'Connexion en cours',
    'DISCONNECTED' => 'Déconnecté',
    'ERROR' => 'En erreur',
    'NOT_CONFIGURED' => 'Non configuré',
    null => '--',
    _ => state,
  };
}
