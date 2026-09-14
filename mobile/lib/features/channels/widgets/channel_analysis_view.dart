import 'package:flutter/material.dart';

import '../../../core/theme/app_colors.dart';
import '../../../core/theme/app_theme.dart';
import '../../../core/utils/formatters.dart';
import '../../../core/widgets/app_widgets.dart';
import '../models/channel.dart';

/// Rapport d'analyse d'un canal (CDC section 13).
///
/// Uniquement des mesures observées sur les messages relus. L'application
/// n'affirme jamais qu'un canal fera gagner de l'argent.
class ChannelAnalysisView extends StatelessWidget {
  const ChannelAnalysisView({super.key, required this.analysis});

  final ChannelAnalysis analysis;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        AppCard(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: <Widget>[
              SectionHeader(
                title: 'Rapport d\'analyse',
                subtitle: '${formatCount(analysis.messagesScanned)} messages relus · '
                    '${Fmt.dayTime(analysis.createdAt)}',
              ),
              Wrap(
                spacing: AppSpacing.xl,
                runSpacing: AppSpacing.lg,
                children: <Widget>[
                  MetricTile(
                    label: 'Qualité de structure',
                    value: formatRate(analysis.structureQuality),
                    compact: true,
                  ),
                  MetricTile(
                    label: 'Signaux avec SL',
                    value: formatRate(analysis.withStopLossRate),
                    compact: true,
                  ),
                  MetricTile(
                    label: 'Signaux avec TP',
                    value: formatRate(analysis.withTakeProfitRate),
                    compact: true,
                  ),
                  MetricTile(
                    label: 'Interprétables',
                    value: formatRate(analysis.parseableRate),
                    compact: true,
                  ),
                  MetricTile(
                    label: 'Fréquence',
                    value: analysis.signalsPerDay == null
                        ? '--'
                        : '${formatDecimal(analysis.signalsPerDay)} / jour',
                    compact: true,
                  ),
                  MetricTile(
                    label: 'TP par signal',
                    value: formatDecimal(analysis.averageTakeProfits),
                    compact: true,
                  ),
                ],
              ),
              const Divider(height: AppSpacing.xl),
              DetailRow(
                label: 'Messages ressemblant à un signal',
                value: formatCount(analysis.signalLikeMessages),
              ),
              DetailRow(
                label: 'Signaux correctement interprétés',
                value: formatCount(analysis.parsedMessages),
              ),
              DetailRow(label: 'Messages de suivi', value: formatCount(analysis.followUpMessages)),
              DetailRow(label: 'Messages de fermeture', value: formatCount(analysis.closeMessages)),
              DetailRow(
                label: 'Messages de modification',
                value: formatCount(analysis.modifyMessages),
              ),
              DetailRow(label: 'Doublons détectés', value: formatCount(analysis.duplicateSignals)),
              DetailRow(
                label: 'Période observée',
                value: analysis.firstMessageAt == null
                    ? '--'
                    : '${Fmt.day(analysis.firstMessageAt)} → ${Fmt.day(analysis.lastMessageAt)}',
              ),
              if (analysis.symbols.isNotEmpty) ...<Widget>[
                const SizedBox(height: AppSpacing.md),
                Text('Instruments observés', style: theme.textTheme.labelSmall),
                const SizedBox(height: AppSpacing.sm),
                _CountChips(counts: analysis.symbols),
              ],
              if (analysis.directions.isNotEmpty) ...<Widget>[
                const SizedBox(height: AppSpacing.md),
                Text('Répartition BUY / SELL', style: theme.textTheme.labelSmall),
                const SizedBox(height: AppSpacing.sm),
                _CountChips(counts: analysis.directions, directional: true),
              ],
              if (analysis.notes != null) ...<Widget>[
                const Divider(height: AppSpacing.xl),
                Text(analysis.notes!, style: theme.textTheme.bodySmall),
              ],
              if (analysis.disclaimer != null) ...<Widget>[
                const SizedBox(height: AppSpacing.md),
                _Disclaimer(text: analysis.disclaimer!),
              ],
            ],
          ),
        ),
        if (analysis.backtest != null) ...<Widget>[
          const SizedBox(height: AppSpacing.md),
          BacktestView(backtest: analysis.backtest!),
        ],
      ],
    );
  }
}

/// Résultats de la simulation historique (CDC section 14).
class BacktestView extends StatelessWidget {
  const BacktestView({super.key, required this.backtest});

  final BacktestSummary backtest;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    final bool dark = theme.brightness == Brightness.dark;
    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          const SectionHeader(
            title: 'Simulation historique',
            subtitle: 'Signaux passés rejoués sur les cours disponibles dans MetaTrader.',
          ),
          Wrap(
            spacing: AppSpacing.xl,
            runSpacing: AppSpacing.lg,
            children: <Widget>[
              MetricTile(
                label: 'Signaux testables',
                value: formatCount(backtest.testable),
                compact: true,
              ),
              MetricTile(
                label: 'Gagnants',
                value: formatCount(backtest.wins),
                valueColor: AppColors.profit,
                compact: true,
              ),
              MetricTile(
                label: 'Perdants',
                value: formatCount(backtest.losses),
                valueColor: AppColors.loss,
                compact: true,
              ),
              MetricTile(
                label: 'Ambigus',
                value: formatCount(backtest.ambiguous),
                compact: true,
              ),
              MetricTile(
                label: 'Non déterminables',
                value: formatCount(backtest.undetermined),
                compact: true,
              ),
              MetricTile(
                label: 'Encore ouverts',
                value: formatCount(backtest.stillOpen),
                compact: true,
              ),
            ],
          ),
          const Divider(height: AppSpacing.xl),
          DetailRow(
            label: 'R moyen',
            value: backtest.averageR == null
                ? '--'
                : '${formatDecimal(backtest.averageR, digits: 2)} R',
            monospace: true,
          ),
          DetailRow(
            label: 'Total théorique',
            value: backtest.totalR == null
                ? '--'
                : '${formatDecimal(backtest.totalR, digits: 2)} R',
            monospace: true,
          ),
          DetailRow(
            label: 'Drawdown théorique',
            value: backtest.theoreticalDrawdownR == null
                ? '--'
                : '${formatDecimal(backtest.theoreticalDrawdownR, digits: 2)} R',
            monospace: true,
          ),
          DetailRow(label: 'TP1 touchés', value: formatCount(backtest.tp1Hits)),
          DetailRow(label: 'SL touchés', value: formatCount(backtest.slHits)),
          const SizedBox(height: AppSpacing.md),
          Container(
            width: double.infinity,
            padding: const EdgeInsets.all(AppSpacing.md),
            decoration: BoxDecoration(
              color: dark ? AppColors.surfaceMutedDark : AppColors.surfaceMuted,
              borderRadius: BorderRadius.circular(AppSpacing.radiusSmall),
            ),
            child: Text(
              'Un trade est marqué « ambigu » lorsque le stop loss et le take profit '
              'pouvaient être atteints dans la même bougie : impossible de savoir '
              'lequel est arrivé en premier. Il n\'est jamais compté comme gagné.',
              style: theme.textTheme.bodySmall,
            ),
          ),
          const SizedBox(height: AppSpacing.md),
          _Disclaimer(
            text: backtest.disclaimer ??
                'Simulation historique indicative — elle ne garantit aucune performance future.',
          ),
        ],
      ),
    );
  }
}

/// Avertissement renvoyé par l'API, affiché tel quel.
class _Disclaimer extends StatelessWidget {
  const _Disclaimer({required this.text});

  final String text;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        const Icon(Icons.info_outline, size: 16, color: AppColors.warning),
        const SizedBox(width: AppSpacing.sm),
        Expanded(
          child: Text(
            text,
            style: theme.textTheme.bodySmall?.copyWith(
              color: AppColors.warning,
              fontWeight: FontWeight.w500,
            ),
          ),
        ),
      ],
    );
  }
}

class _CountChips extends StatelessWidget {
  const _CountChips({required this.counts, this.directional = false});

  final Map<String, int> counts;
  final bool directional;

  @override
  Widget build(BuildContext context) {
    final List<MapEntry<String, int>> entries = counts.entries.toList()
      ..sort((MapEntry<String, int> a, MapEntry<String, int> b) => b.value.compareTo(a.value));
    return Wrap(
      spacing: AppSpacing.sm,
      runSpacing: AppSpacing.sm,
      children: <Widget>[
        for (final MapEntry<String, int> entry in entries)
          StatusChip(
            label: '${entry.key} · ${entry.value}',
            tone: directional
                ? (entry.key.toUpperCase() == 'BUY' ? StatusTone.good : StatusTone.bad)
                : StatusTone.neutral,
            dense: true,
          ),
      ],
    );
  }
}
