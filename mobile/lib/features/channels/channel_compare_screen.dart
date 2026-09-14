import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/api/api_exception.dart';
import '../../core/routing/app_router.dart';
import '../../core/theme/app_colors.dart';
import '../../core/theme/app_theme.dart';
import '../../core/widgets/app_widgets.dart';
import 'models/discovery.dart';
import 'providers/channels_providers.dart';
import 'widgets/compare_table_view.dart';

/// Tableau de comparaison des canaux (CDC section 72).
class ChannelCompareScreen extends ConsumerWidget {
  const ChannelCompareScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final AsyncValue<CompareTable> table = ref.watch(channelCompareProvider);

    return Scaffold(
      appBar: AppBar(title: const Text('Comparer les canaux')),
      body: switch (table) {
        AsyncError(:final Object error) => ErrorView(
            message: error is ApiException ? error.message : 'Comparaison indisponible.',
            technical: error is ApiException ? error.technical : error.toString(),
            onRetry: () => ref.invalidate(channelCompareProvider),
          ),
        AsyncData(:final CompareTable value) => _CompareBody(table: value),
        _ => const LoadingView(label: 'Chargement de la comparaison…'),
      },
    );
  }
}

class _CompareBody extends ConsumerWidget {
  const _CompareBody({required this.table});

  final CompareTable table;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final ThemeData theme = Theme.of(context);

    if (table.rows.isEmpty) {
      return EmptyState(
        title: 'Rien à comparer',
        message: 'Ajoutez au moins un canal à votre surveillance, puis analysez-le '
            'pour obtenir des mesures comparables.',
        icon: Icons.table_chart_outlined,
        action: FilledButton(
          onPressed: () => context.push(Routes.discover),
          child: const Text('Découvrir des canaux'),
        ),
      );
    }

    return RefreshIndicator(
      onRefresh: () async {
        ref.invalidate(channelCompareProvider);
        await ref.read(channelCompareProvider.future);
      },
      child: ListView(
        physics: const AlwaysScrollableScrollPhysics(),
        padding: const EdgeInsets.symmetric(vertical: AppSpacing.lg),
        children: <Widget>[
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: AppSpacing.lg),
            child: AppCard(
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: <Widget>[
                  const Icon(Icons.info_outline, size: 16, color: AppColors.warning),
                  const SizedBox(width: AppSpacing.sm),
                  Expanded(
                    child: Text(
                      table.disclaimer ??
                          'Données observées uniquement. L\'application ne désigne pas de '
                              'meilleur canal : les résultats passés ne prédisent pas les '
                              'résultats futurs.',
                      style: theme.textTheme.bodySmall?.copyWith(
                        color: AppColors.warning,
                        fontWeight: FontWeight.w500,
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ),
          const SizedBox(height: AppSpacing.md),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: AppSpacing.lg),
            child: Text(
              'Touchez un en-tête pour trier, faites défiler le tableau vers la droite '
              'pour voir toutes les colonnes. Une mesure absente s\'affiche « -- ».',
              style: theme.textTheme.bodySmall,
            ),
          ),
          const SizedBox(height: AppSpacing.md),
          CompareTableView(rows: table.rows),
          const SizedBox(height: AppSpacing.xl),
        ],
      ),
    );
  }
}
