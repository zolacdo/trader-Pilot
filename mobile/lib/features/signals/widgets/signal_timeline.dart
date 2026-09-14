import 'package:flutter/material.dart';

import '../../../core/theme/app_colors.dart';
import '../../../core/theme/app_theme.dart';
import '../../../core/utils/formatters.dart';
import '../models/signal.dart';

/// Chronologie verticale du traitement d'un signal (CDC section 34).
///
/// Chaque étape provient du tableau `timeline` renvoyé par le Bridge : rien
/// n'est inventé, une étape absente n'est simplement pas affichée.
class SignalTimeline extends StatelessWidget {
  const SignalTimeline({super.key, required this.steps});

  final List<SignalStep> steps;

  @override
  Widget build(BuildContext context) {
    if (steps.isEmpty) {
      return Text(
        'Aucune étape enregistrée pour ce signal.',
        style: Theme.of(context).textTheme.bodySmall,
      );
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        for (int index = 0; index < steps.length; index++)
          _TimelineTile(step: steps[index], last: index == steps.length - 1),
      ],
    );
  }
}

class _TimelineTile extends StatelessWidget {
  const _TimelineTile({required this.step, required this.last});

  final SignalStep step;
  final bool last;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    final bool dark = theme.brightness == Brightness.dark;
    final Color markerColor = step.success
        ? AppColors.primary
        : (dark ? const Color(0xFFF87171) : AppColors.loss);

    return IntrinsicHeight(
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: <Widget>[
          SizedBox(
            width: 22,
            child: Column(
              children: <Widget>[
                const SizedBox(height: 4),
                Icon(
                  step.success ? Icons.circle : Icons.error_outline,
                  size: step.success ? 11 : 15,
                  color: markerColor,
                ),
                if (!last)
                  Expanded(
                    child: Container(width: 1.4, color: theme.colorScheme.outline),
                  ),
              ],
            ),
          ),
          const SizedBox(width: AppSpacing.md),
          Expanded(
            child: Padding(
              padding: EdgeInsets.only(bottom: last ? 0 : AppSpacing.lg),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: <Widget>[
                  Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: <Widget>[
                      Expanded(
                        child: Text(
                          SignalStep.label(step.stage),
                          style: theme.textTheme.bodyMedium?.copyWith(
                            fontWeight: FontWeight.w600,
                            color: step.success ? null : markerColor,
                          ),
                        ),
                      ),
                      const SizedBox(width: AppSpacing.sm),
                      Text(Fmt.dayTime(step.createdAt), style: theme.textTheme.bodySmall),
                    ],
                  ),
                  if (step.message != null) ...<Widget>[
                    const SizedBox(height: 2),
                    Text(
                      step.message!,
                      style: theme.textTheme.bodySmall?.copyWith(
                        color: step.success ? null : markerColor,
                      ),
                    ),
                  ],
                  if (step.status != null) ...<Widget>[
                    const SizedBox(height: 2),
                    Text(
                      'État : ${Fmt.signalStatus(step.status)}',
                      style: theme.textTheme.bodySmall,
                    ),
                  ],
                  if (step.data.isNotEmpty) _StepData(data: step.data),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}

/// Données brutes d'une étape : repliées, réservées au diagnostic.
class _StepData extends StatelessWidget {
  const _StepData({required this.data});

  final Map<String, dynamic> data;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    return Theme(
      data: theme.copyWith(dividerColor: Colors.transparent),
      child: ExpansionTile(
        tilePadding: EdgeInsets.zero,
        childrenPadding: const EdgeInsets.only(bottom: AppSpacing.sm),
        expandedCrossAxisAlignment: CrossAxisAlignment.start,
        title: Text('Détail technique', style: theme.textTheme.bodySmall),
        children: <Widget>[
          for (final MapEntry<String, dynamic> entry in data.entries)
            Padding(
              padding: const EdgeInsets.only(bottom: 2),
              child: Text(
                '${entry.key} : ${entry.value}',
                style: theme.textTheme.bodySmall?.copyWith(fontFamily: 'monospace'),
              ),
            ),
        ],
      ),
    );
  }
}
