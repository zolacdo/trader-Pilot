import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api/api_exception.dart';
import '../../core/api/endpoints.dart';
import '../../core/connection/connection_controller.dart';
import '../../core/theme/app_theme.dart';
import '../../core/widgets/app_widgets.dart';
import '../intelligence/labels.dart';

final FutureProviderFamily<Map<String, dynamic>, int> decisionDetailProvider =
    FutureProvider.family<Map<String, dynamic>, int>((Ref ref, int id) {
  return ref.watch(apiClientProvider).getJson(Endpoints.decisionDetail(id));
});

/// Détail d'une décision : d'où vient chaque point du score (CDC2 section 43).
class DecisionDetailScreen extends ConsumerWidget {
  const DecisionDetailScreen({super.key, required this.decisionId});

  final int decisionId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final AsyncValue<Map<String, dynamic>> detail = ref.watch(decisionDetailProvider(decisionId));

    return Scaffold(
      appBar: AppBar(title: const Text('Décision')),
      body: detail.when(
        loading: () => const LoadingView(label: 'Chargement…'),
        error: (Object error, StackTrace stack) => ErrorView(
          message: error is ApiException ? error.message : 'Décision introuvable.',
          technical: error is ApiException ? error.technical : error.toString(),
          onRetry: () => ref.invalidate(decisionDetailProvider(decisionId)),
        ),
        data: (Map<String, dynamic> payload) => _Body(decision: payload),
      ),
    );
  }
}

class _Body extends StatelessWidget {
  const _Body({required this.decision});

  final Map<String, dynamic> decision;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    final String action = '${decision['action'] ?? ''}';
    final List<Map<String, dynamic>> factors = <Map<String, dynamic>>[
      ...?(decision['factors'] as List<dynamic>?)
          ?.map((dynamic e) => Map<String, dynamic>.from(e as Map)),
    ];
    final List<String> positives = <String>[
      ...?(decision['positiveFactors'] as List<dynamic>?)?.map((dynamic e) => '$e'),
    ];
    final List<String> negatives = <String>[
      ...?(decision['negativeFactors'] as List<dynamic>?)?.map((dynamic e) => '$e'),
    ];

    return ListView(
      padding: AppSpacing.page,
      children: <Widget>[
        AppCard(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: <Widget>[
              Row(
                children: <Widget>[
                  Text('${decision['symbol'] ?? ''}', style: theme.textTheme.titleMedium),
                  const SizedBox(width: AppSpacing.sm),
                  if (decision['direction'] != null)
                    StatusChip.direction('${decision['direction']}'),
                  const Spacer(),
                  StatusChip(
                    label: labelFor(kActionLabels, action),
                    tone: actionTone(action),
                  ),
                ],
              ),
              const SizedBox(height: AppSpacing.sm),
              Text(
                '${labelFor(kSourceLabels, '${decision['source']}')} · '
                '${shortMoment('${decision['createdAt']}')}',
                style: theme.textTheme.labelSmall,
              ),
              const SizedBox(height: AppSpacing.md),
              Row(
                children: <Widget>[
                  Expanded(
                    child: MetricTile(
                      label: 'Score global',
                      value: '${number(decision['globalScore'], digits: 0)}/100',
                      compact: true,
                    ),
                  ),
                  Expanded(
                    child: MetricTile(
                      label: 'Régime',
                      value: labelFor(kRegimeLabels, '${decision['regime']}'),
                      compact: true,
                    ),
                  ),
                ],
              ),
              if (decision['reason'] != null) ...<Widget>[
                const SizedBox(height: AppSpacing.md),
                Text('${decision['reason']}', style: theme.textTheme.bodyMedium),
              ],
            ],
          ),
        ),
        const SizedBox(height: AppSpacing.md),
        AppCard(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: <Widget>[
              const SectionHeader(
                title: 'Décomposition du score',
                subtitle: 'Chaque composante, son poids et ce qu’elle a réellement apporté',
              ),
              if (factors.isEmpty)
                Text(
                  'Aucune décomposition enregistrée pour cette décision.',
                  style: theme.textTheme.bodySmall,
                )
              else
                for (final Map<String, dynamic> factor in factors)
                  _FactorRow(factor: factor),
            ],
          ),
        ),
        if (positives.isNotEmpty || negatives.isNotEmpty) ...<Widget>[
          const SizedBox(height: AppSpacing.md),
          AppCard(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: <Widget>[
                const SectionHeader(title: 'Ce qui a pesé'),
                for (final String item in positives)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 4),
                    child: Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: <Widget>[
                        const Icon(Icons.add, size: 14, color: Colors.green),
                        const SizedBox(width: 6),
                        Expanded(child: Text(item, style: theme.textTheme.bodySmall)),
                      ],
                    ),
                  ),
                for (final String item in negatives)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 4),
                    child: Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: <Widget>[
                        const Icon(Icons.remove, size: 14, color: Colors.redAccent),
                        const SizedBox(width: 6),
                        Expanded(child: Text(item, style: theme.textTheme.bodySmall)),
                      ],
                    ),
                  ),
              ],
            ),
          ),
        ],
        const SizedBox(height: AppSpacing.md),
        AppCard(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: <Widget>[
              const SectionHeader(title: 'Suivi'),
              DetailRow(
                label: 'Exécutée',
                value: decision['executed'] == true ? 'Oui' : 'Non',
              ),
              DetailRow(
                label: 'Mode observation',
                value: decision['shadow'] == true ? 'Oui (aucun ordre envoyé)' : 'Non',
              ),
              if (decision['opportunityId'] != null)
                DetailRow(label: 'Opportunité liée', value: '#${decision['opportunityId']}'),
              if (decision['signalId'] != null)
                DetailRow(label: 'Signal lié', value: '#${decision['signalId']}'),
              if (decision['tradeId'] != null)
                DetailRow(label: 'Trade lié', value: '#${decision['tradeId']}'),
            ],
          ),
        ),
      ],
    );
  }
}

/// Une composante : note, poids et contribution effective au score.
class _FactorRow extends StatelessWidget {
  const _FactorRow({required this.factor});

  final Map<String, dynamic> factor;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    final Object? score = factor['score'];
    final Object? weight = factor['weight'];
    // Un poids nul signale une composante absente : elle a été retirée du
    // calcul plutôt que remplacée par une note neutre.
    final bool available = weight is num && weight > 0;

    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Row(
            children: <Widget>[
              Expanded(
                child: Text(
                  '${factor['label'] ?? factor['name'] ?? ''}',
                  style: theme.textTheme.bodyMedium,
                ),
              ),
              Text(
                available
                    ? '${number(score, digits: 0)}/100  ×${percentFromRatio(weight)}'
                    : 'donnée absente',
                style: theme.textTheme.bodySmall?.copyWith(
                  color: available ? null : theme.disabledColor,
                ),
              ),
            ],
          ),
          const SizedBox(height: 4),
          ClipRRect(
            borderRadius: BorderRadius.circular(3),
            child: LinearProgressIndicator(
              value: available && score is num ? (score / 100).clamp(0.0, 1.0) : 0,
              minHeight: 5,
              backgroundColor: theme.colorScheme.surfaceContainerHighest,
            ),
          ),
          if (factor['detail'] != null) ...<Widget>[
            const SizedBox(height: 4),
            Text('${factor['detail']}', style: theme.textTheme.labelSmall),
          ],
        ],
      ),
    );
  }
}
