import 'package:flutter/material.dart';

import '../../../core/theme/app_colors.dart';
import '../../../core/theme/app_theme.dart';
import '../../../core/utils/formatters.dart';
import '../../../core/widgets/app_widgets.dart';

/// Libellé français d'une tendance observée sur le graphique.
String trendLabel(String? code) {
  return switch (code?.toUpperCase()) {
    'UP' => 'Haussière',
    'DOWN' => 'Baissière',
    'RANGE' => 'Latérale (range)',
    'UNCLEAR' => 'Indéterminée',
    _ => '--',
  };
}

List<num> _numbers(Object? raw) {
  if (raw is! List) return const <num>[];
  return raw.whereType<num>().toList(growable: false);
}

List<String> _strings(Object? raw) {
  if (raw is! List) return const <String>[];
  return raw
      .whereType<String>()
      .map((String value) => value.trim())
      .where((String value) => value.isNotEmpty)
      .toList(growable: false);
}

String? _text(Object? raw) {
  if (raw == null) return null;
  final String value = raw.toString().trim();
  return value.isEmpty ? null : value;
}

/// Résultat d'une analyse de graphique.
///
/// Cet affichage est purement descriptif : il ne propose aucune action de
/// trading, ni directement ni indirectement (CDC section 22).
class AiResultCard extends StatelessWidget {
  const AiResultCard({super.key, required this.result});

  final Map<String, dynamic> result;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    final bool readable = result['readable'] == true;
    final List<num> supports = _numbers(result['supports']);
    final List<num> resistances = _numbers(result['resistances']);
    final List<String> scenarios = _strings(result['scenarios']);
    final String? structure = _text(result['structure']);
    final String? invalidation = _text(result['invalidation']);
    final String? summary = _text(result['summary']);
    final String? disclaimer = _text(result['disclaimer']);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        if (!readable) ...<Widget>[
          const _UnreadableBanner(),
          const SizedBox(height: AppSpacing.lg),
        ],
        AppCard(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: <Widget>[
              const SectionHeader(
                title: 'Lecture du graphique',
                subtitle: 'Ce que le modèle dit voir sur l\'image.',
              ),
              Align(
                alignment: Alignment.centerLeft,
                child: StatusChip(
                  label: readable ? 'Image lisible' : 'Image peu lisible',
                  tone: readable ? StatusTone.neutral : StatusTone.warning,
                  icon: readable ? Icons.image_outlined : Icons.image_not_supported_outlined,
                ),
              ),
              const SizedBox(height: AppSpacing.sm),
              DetailRow(
                label: 'Instrument détecté',
                value: _text(result['instrument']) ?? '--',
              ),
              DetailRow(
                label: 'Unité de temps',
                value: _text(result['timeframe']) ?? '--',
              ),
              DetailRow(
                label: 'Tendance observée',
                value: trendLabel(_text(result['trend'])),
              ),
              if (summary != null) ...<Widget>[
                const SizedBox(height: AppSpacing.lg),
                Text(summary, style: theme.textTheme.bodyLarge),
              ],
            ],
          ),
        ),
        const SizedBox(height: AppSpacing.lg),
        AppCard(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: <Widget>[
              const SectionHeader(title: 'Niveaux visibles'),
              _LevelsRow(label: 'Supports', values: supports),
              const SizedBox(height: AppSpacing.md),
              _LevelsRow(label: 'Résistances', values: resistances),
              if (structure != null) ...<Widget>[
                const SizedBox(height: AppSpacing.lg),
                Text('STRUCTURE', style: theme.textTheme.labelSmall),
                const SizedBox(height: AppSpacing.xs),
                Text(structure, style: theme.textTheme.bodyMedium),
              ],
            ],
          ),
        ),
        const SizedBox(height: AppSpacing.lg),
        AppCard(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: <Widget>[
              const SectionHeader(
                title: 'Scénarios évoqués',
                subtitle: 'Hypothèses décrites par le modèle, sans aucune recommandation.',
              ),
              if (scenarios.isEmpty)
                Text('Aucun scénario décrit.', style: theme.textTheme.bodySmall)
              else
                for (final String scenario in scenarios)
                  Padding(
                    padding: const EdgeInsets.only(bottom: AppSpacing.sm),
                    child: Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: <Widget>[
                        Text('• ', style: theme.textTheme.bodyMedium),
                        Expanded(child: Text(scenario, style: theme.textTheme.bodyMedium)),
                      ],
                    ),
                  ),
              const SizedBox(height: AppSpacing.sm),
              DetailRow(label: 'Invalidation décrite', value: invalidation ?? '--'),
              DetailRow(label: 'Modèle utilisé', value: _text(result['model']) ?? '--'),
            ],
          ),
        ),
        const SizedBox(height: AppSpacing.lg),
        AiDisclaimerCard(disclaimer: disclaimer),
      ],
    );
  }
}

class _UnreadableBanner extends StatelessWidget {
  const _UnreadableBanner();

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(AppSpacing.lg),
      decoration: BoxDecoration(
        color: AppColors.warningSurface,
        borderRadius: BorderRadius.circular(AppSpacing.radius),
        border: Border.all(color: AppColors.warning.withValues(alpha: 0.4)),
      ),
      child: const Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Icon(Icons.warning_amber_rounded, size: 20, color: AppColors.warning),
          SizedBox(width: AppSpacing.sm),
          Expanded(
            child: Text(
              'Le modèle indique que l\'image n\'est pas lisible comme un graphique de prix. '
              'Les éléments ci-dessous sont donc à considérer comme non fiables.',
              style: TextStyle(fontSize: 13, height: 1.4, color: AppColors.warning),
            ),
          ),
        ],
      ),
    );
  }
}

class _LevelsRow extends StatelessWidget {
  const _LevelsRow({required this.label, required this.values});

  final String label;
  final List<num> values;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        Text(label.toUpperCase(), style: theme.textTheme.labelSmall),
        const SizedBox(height: AppSpacing.xs),
        if (values.isEmpty)
          Text('Aucun niveau lisible sur l\'image.', style: theme.textTheme.bodySmall)
        else
          Wrap(
            spacing: AppSpacing.sm,
            runSpacing: AppSpacing.xs,
            children: <Widget>[
              for (final num value in values) StatusChip(label: Fmt.price(value), dense: true),
            ],
          ),
      ],
    );
  }
}

/// Avertissement renvoyé par l'API, toujours affiché avec l'analyse.
class AiDisclaimerCard extends StatelessWidget {
  const AiDisclaimerCard({super.key, this.disclaimer});

  final String? disclaimer;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Row(
            children: <Widget>[
              const Icon(Icons.info_outline, size: 18, color: AppColors.textSecondary),
              const SizedBox(width: AppSpacing.sm),
              Text('Analyse informative', style: theme.textTheme.titleMedium),
            ],
          ),
          const SizedBox(height: AppSpacing.sm),
          if (disclaimer != null) ...<Widget>[
            Text(disclaimer!, style: theme.textTheme.bodyMedium),
            const SizedBox(height: AppSpacing.sm),
          ],
          Text(
            'Cette lecture est produite par un modèle de langage à partir d\'une image. '
            'Elle ne constitue pas un conseil, ne déclenche aucun ordre et ne peut pas être '
            'exécutée depuis cet écran.',
            style: theme.textTheme.bodySmall,
          ),
        ],
      ),
    );
  }
}
