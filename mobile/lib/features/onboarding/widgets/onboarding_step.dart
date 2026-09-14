import 'package:flutter/material.dart';

import '../../../core/theme/app_colors.dart';
import '../../../core/theme/app_theme.dart';
import '../../../core/widgets/app_widgets.dart';
import '../../bridge/models/bridge_json.dart';

/// Mise en page commune à toutes les étapes de la configuration guidée.
class OnboardingStep extends StatelessWidget {
  const OnboardingStep({
    super.key,
    required this.title,
    required this.intro,
    required this.children,
    this.done,
  });

  final String title;
  final String intro;
  final List<Widget> children;

  /// État de l'étape tel que le Bridge le calcule, quand il le connaît.
  final bool? done;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    return ListView(
      padding: AppSpacing.page,
      children: <Widget>[
        Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: <Widget>[
            Expanded(child: Text(title, style: theme.textTheme.headlineSmall)),
            if (done != null) ...<Widget>[
              const SizedBox(width: AppSpacing.sm),
              StatusChip(
                label: done! ? 'Terminée' : 'À faire',
                tone: done! ? StatusTone.good : StatusTone.neutral,
                dense: true,
              ),
            ],
          ],
        ),
        const SizedBox(height: AppSpacing.sm),
        Text(intro, style: theme.textTheme.bodyMedium),
        const SizedBox(height: AppSpacing.xl),
        ...children,
        const SizedBox(height: AppSpacing.xxl),
      ],
    );
  }

  /// Lit l'étape `key` dans la liste renvoyée par `GET /onboarding/state`.
  static Map<String, dynamic> stepByKey(Map<String, dynamic> payload, String key) {
    for (final Map<String, dynamic> step in Json.objects(payload['steps'])) {
      if (Json.text(step['key']) == key) return step;
    }
    return const <String, dynamic>{};
  }
}

/// Point d'explication court, aligné sur une puce discrète.
class OnboardingBullet extends StatelessWidget {
  const OnboardingBullet({super.key, required this.text, this.icon = Icons.check});

  final String text;
  final IconData icon;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.only(bottom: AppSpacing.md),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Icon(icon, size: 18, color: AppColors.primary),
          const SizedBox(width: AppSpacing.md),
          Expanded(child: Text(text, style: theme.textTheme.bodyMedium)),
        ],
      ),
    );
  }
}

/// Encadré d'avertissement, réservé aux points qui engagent de l'argent.
class OnboardingWarning extends StatelessWidget {
  const OnboardingWarning({super.key, required this.title, required this.message});

  final String title;
  final String message;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Row(
            children: <Widget>[
              const Icon(Icons.warning_amber_rounded, size: 18, color: AppColors.warning),
              const SizedBox(width: AppSpacing.sm),
              Expanded(child: Text(title, style: theme.textTheme.titleMedium)),
            ],
          ),
          const SizedBox(height: AppSpacing.sm),
          Text(message, style: theme.textTheme.bodySmall),
        ],
      ),
    );
  }
}
