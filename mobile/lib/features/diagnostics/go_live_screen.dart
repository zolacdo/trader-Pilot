import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/api/api_exception.dart';
import '../../core/routing/app_router.dart';
import '../../core/theme/app_colors.dart';
import '../../core/theme/app_theme.dart';
import '../../core/widgets/app_widgets.dart';
import 'diagnostics_providers.dart';

/// Checklist avant d'envisager le mode réel (CDC section 68).
///
/// Cet écran ne peut pas activer le mode réel : il informe et renvoie vers les
/// Paramètres, où le déverrouillage reste une action délibérée.
class GoLiveScreen extends ConsumerWidget {
  const GoLiveScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final AsyncValue<Map<String, dynamic>> checklist = ref.watch(goLiveChecklistProvider);

    return Scaffold(
      appBar: AppBar(
        title: const Text('Avant le mode réel'),
        actions: <Widget>[
          IconButton(
            tooltip: 'Actualiser',
            onPressed: () => ref.invalidate(goLiveChecklistProvider),
            icon: const Icon(Icons.refresh),
          ),
        ],
      ),
      body: checklist.when(
        loading: () => const LoadingView(label: 'Vérification des critères…'),
        error: (Object error, StackTrace stack) => ErrorView(
          message: error is ApiException ? error.message : 'Checklist indisponible.',
          technical: error is ApiException ? error.technical : error.toString(),
          onRetry: () => ref.invalidate(goLiveChecklistProvider),
        ),
        data: (Map<String, dynamic> data) {
          final List<Map<String, dynamic>> items = diagnosticRows(data, 'items');
          if (items.isEmpty) {
            return const EmptyState(
              title: 'Aucun critère',
              message: 'Le Bridge n\'a renvoyé aucun critère à vérifier.',
              icon: Icons.checklist_outlined,
            );
          }
          return RefreshIndicator(
            onRefresh: () async => ref.invalidate(goLiveChecklistProvider),
            child: ListView(
              padding: AppSpacing.page,
              children: <Widget>[
                _ProgressCard(data: data),
                const SizedBox(height: AppSpacing.lg),
                AppCard(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: <Widget>[
                      const SectionHeader(title: 'Critères à vérifier'),
                      for (final Map<String, dynamic> item in items)
                        _ChecklistTile(item: item),
                    ],
                  ),
                ),
                const SizedBox(height: AppSpacing.lg),
                _NextStepCard(ready: data['ready'] == true),
                const SizedBox(height: AppSpacing.lg),
                _DisclaimerCard(disclaimer: data['disclaimer']?.toString()),
                const SizedBox(height: AppSpacing.xl),
              ],
            ),
          );
        },
      ),
    );
  }
}

/// Progression `completed / total`.
class _ProgressCard extends StatelessWidget {
  const _ProgressCard({required this.data});

  final Map<String, dynamic> data;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    final Object? rawCompleted = data['completed'];
    final Object? rawTotal = data['total'];
    final int? completed = rawCompleted is num ? rawCompleted.round() : null;
    final int? total = rawTotal is num ? rawTotal.round() : null;
    final double? ratio =
        (completed != null && total != null && total > 0) ? completed / total : null;

    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: <Widget>[
              Expanded(
                child: MetricTile(
                  label: 'Critères validés',
                  value: '${completed ?? '--'} / ${total ?? '--'}',
                ),
              ),
              StatusChip(
                label: data['ready'] == true ? 'Tous validés' : 'Incomplet',
                tone: data['ready'] == true ? StatusTone.good : StatusTone.neutral,
              ),
            ],
          ),
          const SizedBox(height: AppSpacing.lg),
          ClipRRect(
            borderRadius: BorderRadius.circular(4),
            child: LinearProgressIndicator(
              value: ratio,
              minHeight: 6,
              backgroundColor: theme.colorScheme.outline,
              color: AppColors.primary,
            ),
          ),
        ],
      ),
    );
  }
}

/// Une ligne de la checklist : cochée ou non, avec son détail éventuel.
class _ChecklistTile extends StatelessWidget {
  const _ChecklistTile({required this.item});

  final Map<String, dynamic> item;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    final bool done = item['done'] == true;
    final String? detail = item['detail']?.toString().trim();

    return Padding(
      padding: const EdgeInsets.symmetric(vertical: AppSpacing.sm),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Icon(
            done ? Icons.check_box_outlined : Icons.check_box_outline_blank,
            size: 20,
            color: done ? AppColors.profit : AppColors.textTertiary,
          ),
          const SizedBox(width: AppSpacing.md),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: <Widget>[
                Text(
                  (item['label'] ?? item['key'] ?? '--').toString(),
                  style: theme.textTheme.bodyLarge,
                ),
                if (detail != null && detail.isNotEmpty) ...<Widget>[
                  const SizedBox(height: 2),
                  Text(detail, style: theme.textTheme.bodySmall),
                ],
              ],
            ),
          ),
        ],
      ),
    );
  }
}

/// Marche à suivre, sans jamais activer le mode réel depuis cet écran.
class _NextStepCard extends StatelessWidget {
  const _NextStepCard({required this.ready});

  final bool ready;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    return AppCard(
      accent: ready,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          SectionHeader(
            title: ready ? 'Marche à suivre pour passer en réel' : 'Le mode réel reste hors de portée',
          ),
          if (ready) ...<Widget>[
            Text(
              'Tous les critères sont validés. Le passage en mode réel se fait uniquement '
              'depuis les Paramètres, et en plusieurs gestes délibérés :',
              style: theme.textTheme.bodyMedium,
            ),
            const SizedBox(height: AppSpacing.md),
            const _Step(number: 1, text: 'Ouvrez les Paramètres, section mode d\'exécution.'),
            const _Step(
              number: 2,
              text: 'Déverrouillez le mode réel : le Bridge exige une confirmation explicite.',
            ),
            const _Step(
              number: 3,
              text: 'Vérifiez que MetaTrader 5 est bien connecté au compte voulu et que le '
                  'type de compte est correctement détecté.',
            ),
            const _Step(
              number: 4,
              text: 'Repassez vos limites de risque en revue avant le premier signal copié.',
            ),
            const SizedBox(height: AppSpacing.lg),
            OutlinedButton.icon(
              onPressed: () => context.push(Routes.settings),
              icon: const Icon(Icons.settings_outlined, size: 18),
              label: const Text('Ouvrir les Paramètres'),
            ),
            const SizedBox(height: AppSpacing.sm),
            Text(
              'Cet écran ne peut pas activer le mode réel : il ne fait que constater l\'état '
              'des vérifications.',
              style: theme.textTheme.bodySmall,
            ),
          ] else
            Text(
              'Des critères ne sont pas encore validés. Continuez en Paper Trading ou sur un '
              'compte démo : chaque critère non coché correspond à une vérification que rien '
              'ne remplace.',
              style: theme.textTheme.bodyMedium,
            ),
        ],
      ),
    );
  }
}

class _Step extends StatelessWidget {
  const _Step({required this.number, required this.text});

  final int number;
  final String text;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.only(bottom: AppSpacing.sm),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Text('$number. ', style: theme.textTheme.bodyMedium),
          Expanded(child: Text(text, style: theme.textTheme.bodyMedium)),
        ],
      ),
    );
  }
}

/// Avertissement renvoyé par l'API, toujours affiché.
class _DisclaimerCard extends StatelessWidget {
  const _DisclaimerCard({required this.disclaimer});

  final String? disclaimer;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(AppSpacing.lg),
      decoration: BoxDecoration(
        color: AppColors.warningSurface,
        borderRadius: BorderRadius.circular(AppSpacing.radius),
        border: Border.all(color: AppColors.warning, width: 1.2),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          const Row(
            children: <Widget>[
              Icon(Icons.warning_amber_rounded, size: 20, color: AppColors.warning),
              SizedBox(width: AppSpacing.sm),
              Expanded(
                child: Text(
                  'À LIRE AVANT TOUTE DÉCISION',
                  style: TextStyle(
                    fontSize: 12.5,
                    fontWeight: FontWeight.w700,
                    letterSpacing: 0.4,
                    color: AppColors.warning,
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: AppSpacing.sm),
          if (disclaimer != null && disclaimer!.trim().isNotEmpty)
            Text(
              disclaimer!.trim(),
              style: theme.textTheme.bodyMedium?.copyWith(color: AppColors.warning),
            ),
          const SizedBox(height: AppSpacing.sm),
          Text(
            'Une checklist complète ne rend pas le trading sans risque. Le capital engagé en '
            'mode réel peut être perdu.',
            style: theme.textTheme.bodySmall?.copyWith(color: AppColors.warning),
          ),
        ],
      ),
    );
  }
}
