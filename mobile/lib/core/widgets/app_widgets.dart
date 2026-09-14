import 'package:flutter/material.dart';

import '../theme/app_colors.dart';
import '../theme/app_theme.dart';

/// Carte standard : fond blanc, bordure discrete, coins legerement arrondis.
class AppCard extends StatelessWidget {
  const AppCard({super.key, required this.child, this.padding, this.onTap, this.accent = false});

  final Widget child;
  final EdgeInsetsGeometry? padding;
  final VoidCallback? onTap;

  /// Souligne la carte avec l'accent principal (element actif).
  final bool accent;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    final Widget content = Padding(padding: padding ?? AppSpacing.card, child: child);
    return Material(
      color: theme.cardTheme.color,
      borderRadius: BorderRadius.circular(AppSpacing.radius),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(AppSpacing.radius),
        child: Container(
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(AppSpacing.radius),
            border: Border.all(
              color: accent ? AppColors.primary : theme.colorScheme.outline,
              width: accent ? 1.4 : 1,
            ),
          ),
          child: content,
        ),
      ),
    );
  }
}

/// Titre de section, avec action facultative a droite.
class SectionHeader extends StatelessWidget {
  const SectionHeader({super.key, required this.title, this.subtitle, this.action});

  final String title;
  final String? subtitle;
  final Widget? action;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.only(bottom: AppSpacing.md),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: <Widget>[
                Text(title, style: theme.textTheme.titleMedium),
                if (subtitle != null) ...<Widget>[
                  const SizedBox(height: 2),
                  Text(subtitle!, style: theme.textTheme.bodySmall),
                ],
              ],
            ),
          ),
          if (action != null) action!,
        ],
      ),
    );
  }
}

enum StatusTone { neutral, good, bad, warning, accent }

/// Pastille d'etat : connecte / hors ligne / en pause, direction BUY / SELL.
class StatusChip extends StatelessWidget {
  const StatusChip({super.key, required this.label, this.tone = StatusTone.neutral, this.icon, this.dense = false});

  final String label;
  final StatusTone tone;
  final IconData? icon;
  final bool dense;

  factory StatusChip.connection({required bool connected, String? labelOverride}) {
    return StatusChip(
      label: labelOverride ?? (connected ? 'Connecté' : 'Non connecté'),
      tone: connected ? StatusTone.good : StatusTone.bad,
      icon: connected ? Icons.check_circle_outline : Icons.error_outline,
      dense: true,
    );
  }

  factory StatusChip.direction(String? direction) {
    final bool isBuy = direction?.toUpperCase() == 'BUY';
    return StatusChip(
      label: isBuy ? 'BUY' : 'SELL',
      tone: isBuy ? StatusTone.good : StatusTone.bad,
      dense: true,
    );
  }

  ({Color background, Color foreground}) _colors(BuildContext context) {
    final bool dark = Theme.of(context).brightness == Brightness.dark;
    return switch (tone) {
      StatusTone.good => (
          background: dark ? AppColors.profit.withValues(alpha: 0.16) : AppColors.profitSurface,
          foreground: dark ? const Color(0xFF4ADE80) : AppColors.profit,
        ),
      StatusTone.bad => (
          background: dark ? AppColors.loss.withValues(alpha: 0.16) : AppColors.lossSurface,
          foreground: dark ? const Color(0xFFF87171) : AppColors.loss,
        ),
      StatusTone.warning => (
          background: dark ? AppColors.warning.withValues(alpha: 0.16) : AppColors.warningSurface,
          foreground: dark ? const Color(0xFFFBBF24) : AppColors.warning,
        ),
      StatusTone.accent => (
          background: dark ? AppColors.primary.withValues(alpha: 0.18) : AppColors.primarySurface,
          foreground: dark ? const Color(0xFF93B4FF) : AppColors.primaryDark,
        ),
      StatusTone.neutral => (
          background: dark ? AppColors.surfaceMutedDark : AppColors.neutralSurface,
          foreground: dark ? AppColors.textSecondaryDark : AppColors.neutral,
        ),
    };
  }

  @override
  Widget build(BuildContext context) {
    final ({Color background, Color foreground}) palette = _colors(context);
    return Container(
      padding: EdgeInsets.symmetric(horizontal: dense ? 8 : 10, vertical: dense ? 3 : 5),
      decoration: BoxDecoration(
        color: palette.background,
        borderRadius: BorderRadius.circular(6),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: <Widget>[
          if (icon != null) ...<Widget>[
            Icon(icon, size: dense ? 13 : 15, color: palette.foreground),
            const SizedBox(width: 5),
          ],
          Text(
            label,
            style: TextStyle(
              fontSize: dense ? 11.5 : 12.5,
              fontWeight: FontWeight.w600,
              color: palette.foreground,
            ),
          ),
        ],
      ),
    );
  }
}

/// Valeur mise en avant : solde, equity, P&L du jour.
class MetricTile extends StatelessWidget {
  const MetricTile({
    super.key,
    required this.label,
    required this.value,
    this.valueColor,
    this.caption,
    this.compact = false,
  });

  final String label;
  final String value;
  final Color? valueColor;
  final String? caption;
  final bool compact;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: <Widget>[
        Text(label.toUpperCase(), style: theme.textTheme.labelSmall),
        const SizedBox(height: 6),
        Text(
          value,
          maxLines: 1,
          overflow: TextOverflow.ellipsis,
          style: (compact ? theme.textTheme.titleMedium : theme.textTheme.headlineSmall)?.copyWith(
            color: valueColor,
            fontFeatures: const <FontFeature>[FontFeature.tabularFigures()],
          ),
        ),
        if (caption != null) ...<Widget>[
          const SizedBox(height: 2),
          Text(caption!, style: theme.textTheme.bodySmall),
        ],
      ],
    );
  }
}

/// Ligne cle/valeur utilisee dans les details de signal et de position.
class DetailRow extends StatelessWidget {
  const DetailRow({super.key, required this.label, required this.value, this.valueColor, this.monospace = false});

  final String label;
  final String value;
  final Color? valueColor;
  final bool monospace;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Expanded(flex: 4, child: Text(label, style: theme.textTheme.bodySmall)),
          Expanded(
            flex: 5,
            child: Text(
              value,
              textAlign: TextAlign.right,
              style: theme.textTheme.bodyMedium?.copyWith(
                fontWeight: FontWeight.w500,
                color: valueColor,
                fontFeatures: monospace ? const <FontFeature>[FontFeature.tabularFigures()] : null,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

/// Etat vide explicite plutot qu'un ecran blanc.
class EmptyState extends StatelessWidget {
  const EmptyState({
    super.key,
    required this.title,
    this.message,
    this.icon = Icons.inbox_outlined,
    this.action,
  });

  final String title;
  final String? message;
  final IconData icon;
  final Widget? action;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(AppSpacing.xl),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: <Widget>[
            Icon(icon, size: 40, color: AppColors.textTertiary),
            const SizedBox(height: AppSpacing.lg),
            Text(title, textAlign: TextAlign.center, style: theme.textTheme.titleMedium),
            if (message != null) ...<Widget>[
              const SizedBox(height: AppSpacing.sm),
              Text(message!, textAlign: TextAlign.center, style: theme.textTheme.bodySmall),
            ],
            if (action != null) ...<Widget>[const SizedBox(height: AppSpacing.lg), action!],
          ],
        ),
      ),
    );
  }
}

/// Affichage d'erreur : message clair, detail technique repliable.
class ErrorView extends StatelessWidget {
  const ErrorView({super.key, required this.message, this.technical, this.onRetry});

  final String message;
  final String? technical;
  final VoidCallback? onRetry;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(AppSpacing.xl),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: <Widget>[
            const Icon(Icons.warning_amber_rounded, size: 40, color: AppColors.warning),
            const SizedBox(height: AppSpacing.lg),
            Text(message, textAlign: TextAlign.center, style: theme.textTheme.titleMedium),
            if (technical != null && technical!.isNotEmpty) ...<Widget>[
              const SizedBox(height: AppSpacing.sm),
              Theme(
                data: theme.copyWith(dividerColor: Colors.transparent),
                child: ExpansionTile(
                  tilePadding: EdgeInsets.zero,
                  title: Text('Détails techniques', style: theme.textTheme.bodySmall),
                  children: <Widget>[
                    Text(
                      technical!,
                      style: theme.textTheme.bodySmall?.copyWith(fontFamily: 'monospace'),
                    ),
                  ],
                ),
              ),
            ],
            if (onRetry != null) ...<Widget>[
              const SizedBox(height: AppSpacing.lg),
              OutlinedButton.icon(
                onPressed: onRetry,
                icon: const Icon(Icons.refresh, size: 18),
                label: const Text('Réessayer'),
              ),
            ],
          ],
        ),
      ),
    );
  }
}

/// Bandeau permanent affiche quand le Bridge ne repond plus.
class OfflineBanner extends StatelessWidget {
  const OfflineBanner({super.key, this.onRetry});

  final VoidCallback? onRetry;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      color: AppColors.warningSurface,
      padding: const EdgeInsets.symmetric(horizontal: AppSpacing.lg, vertical: 10),
      child: Row(
        children: <Widget>[
          const Icon(Icons.cloud_off_outlined, size: 18, color: AppColors.warning),
          const SizedBox(width: AppSpacing.sm),
          const Expanded(
            child: Text(
              'BRIDGE HORS LIGNE — aucune donnée temps réel, aucun ordre envoyé',
              style: TextStyle(fontSize: 12.5, fontWeight: FontWeight.w600, color: AppColors.warning),
            ),
          ),
          if (onRetry != null)
            TextButton(
              onPressed: onRetry,
              style: TextButton.styleFrom(
                foregroundColor: AppColors.warning,
                padding: const EdgeInsets.symmetric(horizontal: 8),
                minimumSize: const Size(0, 32),
              ),
              child: const Text('Reessayer'),
            ),
        ],
      ),
    );
  }
}

/// Indicateur de chargement discret, centre.
class LoadingView extends StatelessWidget {
  const LoadingView({super.key, this.label});

  final String? label;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: <Widget>[
          const SizedBox(
            width: 26,
            height: 26,
            child: CircularProgressIndicator(strokeWidth: 2.4),
          ),
          if (label != null) ...<Widget>[
            const SizedBox(height: AppSpacing.md),
            Text(label!, style: Theme.of(context).textTheme.bodySmall),
          ],
        ],
      ),
    );
  }
}

/// Confirmation d'une action sensible. Retourne true si l'utilisateur valide.
Future<bool> confirmAction(
  BuildContext context, {
  required String title,
  required String message,
  String confirmLabel = 'Confirmer',
  String cancelLabel = 'Annuler',
  bool destructive = false,
}) async {
  final bool? result = await showDialog<bool>(
    context: context,
    builder: (BuildContext context) => AlertDialog(
      title: Text(title),
      content: Text(message),
      actions: <Widget>[
        TextButton(
          onPressed: () => Navigator.of(context).pop(false),
          style: TextButton.styleFrom(foregroundColor: AppColors.textSecondary),
          child: Text(cancelLabel),
        ),
        FilledButton(
          onPressed: () => Navigator.of(context).pop(true),
          style: destructive ? FilledButton.styleFrom(backgroundColor: AppColors.loss) : null,
          child: Text(confirmLabel),
        ),
      ],
    ),
  );
  return result ?? false;
}

/// Confirmation renforcee : l'utilisateur doit saisir une phrase exacte.
Future<bool> confirmWithPhrase(
  BuildContext context, {
  required String title,
  required String message,
  required String phrase,
  String confirmLabel = 'Confirmer',
}) async {
  final TextEditingController controller = TextEditingController();
  final bool? result = await showDialog<bool>(
    context: context,
    builder: (BuildContext context) => StatefulBuilder(
      builder: (BuildContext context, StateSetter setState) {
        final bool matches = controller.text.trim().toUpperCase() == phrase.toUpperCase();
        return AlertDialog(
          title: Text(title),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: <Widget>[
              Text(message),
              const SizedBox(height: AppSpacing.lg),
              Text(
                'Saisissez exactement : $phrase',
                style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w600),
              ),
              const SizedBox(height: AppSpacing.sm),
              TextField(
                controller: controller,
                autocorrect: false,
                textCapitalization: TextCapitalization.characters,
                onChanged: (_) => setState(() {}),
                decoration: const InputDecoration(hintText: 'Phrase de confirmation'),
              ),
            ],
          ),
          actions: <Widget>[
            TextButton(
              onPressed: () => Navigator.of(context).pop(false),
              style: TextButton.styleFrom(foregroundColor: AppColors.textSecondary),
              child: const Text('Annuler'),
            ),
            FilledButton(
              onPressed: matches ? () => Navigator.of(context).pop(true) : null,
              style: FilledButton.styleFrom(backgroundColor: AppColors.loss),
              child: Text(confirmLabel),
            ),
          ],
        );
      },
    ),
  );
  controller.dispose();
  return result ?? false;
}

/// Message court en bas d'ecran.
void showToast(BuildContext context, String message, {bool error = false}) {
  ScaffoldMessenger.of(context)
    ..hideCurrentSnackBar()
    ..showSnackBar(
      SnackBar(
        content: Text(message),
        backgroundColor: error ? AppColors.loss : null,
        duration: const Duration(seconds: 3),
      ),
    );
}
