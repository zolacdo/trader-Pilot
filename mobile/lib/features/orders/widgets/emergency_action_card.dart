import 'package:flutter/material.dart';

import '../../../core/theme/app_colors.dart';
import '../../../core/theme/app_theme.dart';
import '../../../core/widgets/app_widgets.dart';

/// Une action d'urgence, expliquée avant d'être proposée.
///
/// Le bouton n'est jamais mis en avant tout seul : l'utilisateur lit d'abord
/// ce que l'action fait, ce qu'elle ne fait pas, et sur quoi elle porte.
class EmergencyActionCard extends StatelessWidget {
  const EmergencyActionCard({
    super.key,
    required this.title,
    required this.description,
    required this.scope,
    required this.buttonLabel,
    required this.icon,
    required this.onPressed,
    this.busy = false,
    this.destructive = false,
    this.footnote,
  });

  final String title;
  final String description;

  /// Ce qui est réellement concerné : « 3 ordre(s) en attente ».
  final String scope;
  final String buttonLabel;
  final IconData icon;
  final VoidCallback? onPressed;
  final bool busy;

  /// Vrai pour les actions irréversibles : bouton rouge et confirmation forte.
  final bool destructive;
  final String? footnote;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    final Widget label = Text(buttonLabel);
    final Widget leading = busy
        ? SizedBox(
            width: 16,
            height: 16,
            child: CircularProgressIndicator(
              strokeWidth: 2,
              color: destructive ? Colors.white : null,
            ),
          )
        : Icon(icon, size: 18);

    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Text(
            title,
            style: theme.textTheme.titleMedium?.copyWith(
              color: destructive ? AppColors.loss : null,
            ),
          ),
          const SizedBox(height: AppSpacing.sm),
          Text(description, style: theme.textTheme.bodyMedium),
          const SizedBox(height: AppSpacing.md),
          StatusChip(
            label: scope,
            tone: destructive ? StatusTone.warning : StatusTone.neutral,
            dense: true,
          ),
          if (footnote != null) ...<Widget>[
            const SizedBox(height: AppSpacing.sm),
            Text(footnote!, style: theme.textTheme.bodySmall),
          ],
          const SizedBox(height: AppSpacing.lg),
          SizedBox(
            width: double.infinity,
            child: destructive
                ? FilledButton.icon(
                    onPressed: busy ? null : onPressed,
                    style: FilledButton.styleFrom(backgroundColor: AppColors.loss),
                    icon: leading,
                    label: label,
                  )
                : OutlinedButton.icon(
                    onPressed: busy ? null : onPressed,
                    icon: leading,
                    label: label,
                  ),
          ),
        ],
      ),
    );
  }
}
