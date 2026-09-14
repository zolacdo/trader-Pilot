import 'package:flutter/material.dart';

import '../../../core/theme/app_colors.dart';
import '../../../core/theme/app_theme.dart';
import '../../../core/widgets/app_widgets.dart';

/// Bloc décrivant une des quatre liaisons pilotées par l'application.
///
/// Toujours la même structure : nom de la liaison, pastille d'état, détails
/// factuels puis actions. Une valeur inconnue reste « -- ».
class ConnectionBlock extends StatelessWidget {
  const ConnectionBlock({
    super.key,
    required this.title,
    required this.icon,
    required this.connected,
    required this.stateLabel,
    required this.rows,
    this.subtitle,
    this.errorMessage,
    this.actions = const <Widget>[],
  });

  final String title;
  final IconData icon;
  final bool connected;

  /// État traduit en français : « Connecté », « Non configuré »…
  final String stateLabel;
  final String? subtitle;
  final List<Widget> rows;

  /// Dernière erreur remontée par le Bridge pour cette liaison.
  final String? errorMessage;
  final List<Widget> actions;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Row(
            children: <Widget>[
              Icon(icon, size: 20, color: AppColors.primary),
              const SizedBox(width: AppSpacing.sm),
              Expanded(child: Text(title, style: theme.textTheme.titleMedium)),
              StatusChip.connection(connected: connected, labelOverride: stateLabel),
            ],
          ),
          if (subtitle != null) ...<Widget>[
            const SizedBox(height: AppSpacing.xs),
            Text(subtitle!, style: theme.textTheme.bodySmall),
          ],
          if (rows.isNotEmpty) ...<Widget>[
            const Divider(height: AppSpacing.xl),
            ...rows,
          ],
          if (errorMessage != null) ...<Widget>[
            const SizedBox(height: AppSpacing.sm),
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: <Widget>[
                const Icon(Icons.error_outline, size: 16, color: AppColors.warning),
                const SizedBox(width: AppSpacing.sm),
                Expanded(
                  child: Text(
                    errorMessage!,
                    style: theme.textTheme.bodySmall?.copyWith(color: AppColors.warning),
                  ),
                ),
              ],
            ),
          ],
          if (actions.isNotEmpty) ...<Widget>[
            const SizedBox(height: AppSpacing.lg),
            Wrap(spacing: AppSpacing.sm, runSpacing: AppSpacing.sm, children: actions),
          ],
        ],
      ),
    );
  }
}

/// Bouton d'action compact d'un bloc de connexion.
class ConnectionAction extends StatelessWidget {
  const ConnectionAction({
    super.key,
    required this.label,
    required this.icon,
    required this.onPressed,
    this.busy = false,
    this.destructive = false,
  });

  final String label;
  final IconData icon;
  final VoidCallback? onPressed;
  final bool busy;

  /// Vrai pour « Dissocier » ou « Se déconnecter définitivement ».
  final bool destructive;

  @override
  Widget build(BuildContext context) {
    return OutlinedButton.icon(
      onPressed: busy ? null : onPressed,
      style: OutlinedButton.styleFrom(
        minimumSize: const Size(0, 40),
        padding: const EdgeInsets.symmetric(horizontal: AppSpacing.md),
        foregroundColor: destructive ? AppColors.loss : null,
        textStyle: const TextStyle(fontSize: 13.5, fontWeight: FontWeight.w600),
      ),
      icon: busy
          ? const SizedBox(
              width: 14,
              height: 14,
              child: CircularProgressIndicator(strokeWidth: 2),
            )
          : Icon(icon, size: 16),
      label: Text(label),
    );
  }
}
