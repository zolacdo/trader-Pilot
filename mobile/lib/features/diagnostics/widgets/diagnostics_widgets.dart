import 'package:flutter/material.dart';

import '../../../core/theme/app_colors.dart';
import '../../../core/theme/app_theme.dart';
import '../diagnostics_providers.dart';

/// Ligne de contrôle : ✅ ou ❌, intitulé, détail technique court.
class CheckTile extends StatelessWidget {
  const CheckTile({super.key, required this.label, required this.ok, this.detail});

  final String label;
  final bool ok;
  final String? detail;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: AppSpacing.sm),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Icon(
            ok ? Icons.check_circle : Icons.cancel,
            size: 20,
            color: ok ? AppColors.profit : AppColors.loss,
          ),
          const SizedBox(width: AppSpacing.md),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: <Widget>[
                Text(label, style: theme.textTheme.bodyLarge),
                if (detail != null && detail!.trim().isNotEmpty) ...<Widget>[
                  const SizedBox(height: 2),
                  Text(detail!.trim(), style: theme.textTheme.bodySmall),
                ],
              ],
            ),
          ),
        ],
      ),
    );
  }
}

/// Bloc d'avertissements de sécurité : volontairement très visible.
///
/// « MT5 REAL NOT TESTED ON THIS MACHINE » ou l'impossibilité de déterminer si
/// le compte est démo ou réel ne sont pas des détails (CDC section 60).
class SecurityWarningsCard extends StatelessWidget {
  const SecurityWarningsCard({super.key, required this.warnings});

  final List<String> warnings;

  @override
  Widget build(BuildContext context) {
    if (warnings.isEmpty) return const SizedBox.shrink();
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(AppSpacing.lg),
      decoration: BoxDecoration(
        color: AppColors.warningSurface,
        borderRadius: BorderRadius.circular(AppSpacing.radius),
        border: Border.all(color: AppColors.warning, width: 1.4),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          const Row(
            children: <Widget>[
              Icon(Icons.warning_amber_rounded, size: 22, color: AppColors.warning),
              SizedBox(width: AppSpacing.sm),
              Expanded(
                child: Text(
                  'AVERTISSEMENTS DE SÉCURITÉ',
                  style: TextStyle(
                    fontSize: 13,
                    fontWeight: FontWeight.w700,
                    letterSpacing: 0.4,
                    color: AppColors.warning,
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: AppSpacing.md),
          for (final String warning in warnings)
            Padding(
              padding: const EdgeInsets.only(bottom: AppSpacing.sm),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: <Widget>[
                  const Text('• ', style: TextStyle(color: AppColors.warning, height: 1.4)),
                  Expanded(
                    child: Text(
                      warning,
                      style: const TextStyle(
                        fontSize: 13.5,
                        height: 1.45,
                        fontWeight: FontWeight.w500,
                        color: AppColors.warning,
                      ),
                    ),
                  ),
                ],
              ),
            ),
        ],
      ),
    );
  }
}

/// Bouton de test avec son dernier résultat affiché juste à côté.
class DiagnosticTestRow extends StatelessWidget {
  const DiagnosticTestRow({
    super.key,
    required this.label,
    required this.hint,
    required this.result,
    required this.onRun,
  });

  final String label;
  final String hint;
  final DiagnosticTestResult? result;
  final VoidCallback onRun;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    final bool running = result?.running ?? false;

    return Padding(
      padding: const EdgeInsets.symmetric(vertical: AppSpacing.sm),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          SizedBox(
            width: 168,
            child: OutlinedButton(
              onPressed: running ? null : onRun,
              style: OutlinedButton.styleFrom(minimumSize: const Size(0, 42)),
              child: Text(label, textAlign: TextAlign.center),
            ),
          ),
          const SizedBox(width: AppSpacing.md),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: <Widget>[
                if (running)
                  Text('Test en cours…', style: theme.textTheme.bodySmall)
                else if (result?.ok == null)
                  Text(hint, style: theme.textTheme.bodySmall)
                else
                  Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: <Widget>[
                      Icon(
                        result!.ok! ? Icons.check_circle : Icons.cancel,
                        size: 16,
                        color: result!.ok! ? AppColors.profit : AppColors.loss,
                      ),
                      const SizedBox(width: 6),
                      Expanded(
                        child: Text(
                          result!.detail ?? (result!.ok! ? 'Test réussi.' : 'Test en échec.'),
                          style: theme.textTheme.bodySmall,
                        ),
                      ),
                    ],
                  ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
