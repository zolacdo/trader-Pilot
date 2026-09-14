import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/theme/app_colors.dart';
import '../../../core/theme/app_theme.dart';
import '../../../core/utils/formatters.dart';
import '../../../core/widgets/app_widgets.dart';
import '../statistics_providers.dart';

/// Effectif entier. `null` signifie « non communiqué » et s'affiche `--`.
String statCount(num? value) => value == null ? '--' : value.round().toString();

/// Mesure sans unité (profit factor, R moyen). `null` signifie « non
/// calculable » : par exemple un profit factor sans la moindre perte.
String statFactor(num? value, {String suffix = ''}) =>
    value == null ? '--' : '${value.toStringAsFixed(2)}$suffix';

/// Résumé de la journée en cours (`GET /api/v1/statistics/today`).
class TodaySummaryStrip extends ConsumerWidget {
  const TodaySummaryStrip({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final ThemeData theme = Theme.of(context);
    final AsyncValue<Map<String, dynamic>> today = ref.watch(statisticsTodayProvider);

    return Container(
      width: double.infinity,
      padding: const EdgeInsets.symmetric(horizontal: AppSpacing.lg, vertical: AppSpacing.md),
      color: theme.brightness == Brightness.dark
          ? AppColors.surfaceMutedDark
          : AppColors.surfaceMuted,
      child: today.when(
        loading: () => Text('Résumé du jour en cours de chargement…', style: theme.textTheme.bodySmall),
        error: (Object error, StackTrace stack) => Row(
          children: <Widget>[
            Expanded(
              child: Text('Résumé du jour indisponible.', style: theme.textTheme.bodySmall),
            ),
            TextButton(
              onPressed: () => ref.invalidate(statisticsTodayProvider),
              child: const Text('Réessayer'),
            ),
          ],
        ),
        data: (Map<String, dynamic> data) {
          final num? netPnl = statNum(data, 'netPnl');
          return Row(
            children: <Widget>[
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: <Widget>[
                    Text(
                      'AUJOURD\'HUI · ${Fmt.day(data['day'])}',
                      style: theme.textTheme.labelSmall,
                    ),
                    const SizedBox(height: 4),
                    Text(
                      Fmt.signedMoney(netPnl),
                      style: theme.textTheme.titleMedium?.copyWith(
                        color: netPnl == null ? null : AppColors.forAmount(netPnl),
                      ),
                    ),
                  ],
                ),
              ),
              // Le repli sur FittedBox évite tout débordement sur petit écran
              // ou avec une taille de police système agrandie.
              Flexible(
                child: FittedBox(
                  fit: BoxFit.scaleDown,
                  alignment: Alignment.centerRight,
                  child: Row(
                    children: <Widget>[
                      _TodayFigure(label: 'Trades', value: statCount(statNum(data, 'trades'))),
                      _TodayFigure(label: 'Gagnants', value: statCount(statNum(data, 'wins'))),
                      _TodayFigure(
                        label: 'Réussite',
                        value: Fmt.percent(statNum(data, 'winRate')),
                      ),
                    ],
                  ),
                ),
              ),
            ],
          );
        },
      ),
    );
  }
}

class _TodayFigure extends StatelessWidget {
  const _TodayFigure({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.only(left: AppSpacing.lg),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.end,
        children: <Widget>[
          Text(label.toUpperCase(), style: theme.textTheme.labelSmall),
          const SizedBox(height: 4),
          Text(value, style: theme.textTheme.bodyMedium?.copyWith(fontWeight: FontWeight.w600)),
        ],
      ),
    );
  }
}

/// Bloc principal : toutes les mesures demandées par le CDC section 36.
class GlobalMetricsCard extends StatelessWidget {
  const GlobalMetricsCard({super.key, required this.global});

  final Map<String, dynamic> global;

  @override
  Widget build(BuildContext context) {
    final num? pnl = statNum(global, 'pnl');
    final num? best = statNum(global, 'bestTrade');
    final num? worst = statNum(global, 'worstTrade');
    final num? drawdown = statNum(global, 'maxDrawdown');
    final num? averageWin = statNum(global, 'averageWin');
    final num? averageLoss = statNum(global, 'averageLoss');
    final num? expectancy = statNum(global, 'expectancy');

    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: <Widget>[
              Expanded(
                child: MetricTile(
                  label: 'P&L de la période',
                  value: Fmt.signedMoney(pnl),
                  valueColor: pnl == null ? null : AppColors.forAmount(pnl),
                ),
              ),
              Expanded(
                child: MetricTile(
                  label: 'Trades fermés',
                  value: statCount(statNum(global, 'trades')),
                  compact: true,
                ),
              ),
            ],
          ),
          const SizedBox(height: AppSpacing.lg),
          const Divider(),
          const SizedBox(height: AppSpacing.sm),
          DetailRow(
            label: 'Taux de réussite',
            value: Fmt.percent(statNum(global, 'winRate')),
            monospace: true,
          ),
          DetailRow(
            label: 'Taux de perte',
            value: Fmt.percent(statNum(global, 'lossRate')),
            monospace: true,
          ),
          DetailRow(
            label: 'Break even',
            value: statCount(statNum(global, 'breakEven')),
            monospace: true,
          ),
          DetailRow(
            label: 'Profit factor',
            value: statFactor(statNum(global, 'profitFactor')),
            monospace: true,
          ),
          DetailRow(
            label: 'Gain moyen',
            value: Fmt.signedMoney(averageWin),
            valueColor: averageWin == null ? null : AppColors.forAmount(averageWin),
            monospace: true,
          ),
          DetailRow(
            label: 'Perte moyenne',
            value: Fmt.signedMoney(averageLoss),
            valueColor: averageLoss == null ? null : AppColors.forAmount(averageLoss),
            monospace: true,
          ),
          DetailRow(
            label: 'R moyen',
            value: statFactor(statNum(global, 'averageR'), suffix: ' R'),
            monospace: true,
          ),
          DetailRow(
            label: 'Meilleur trade',
            value: Fmt.signedMoney(best),
            valueColor: best == null ? null : AppColors.forAmount(best),
            monospace: true,
          ),
          DetailRow(
            label: 'Pire trade',
            value: Fmt.signedMoney(worst),
            valueColor: worst == null ? null : AppColors.forAmount(worst),
            monospace: true,
          ),
          DetailRow(
            label: 'Drawdown maximum',
            value: Fmt.money(drawdown),
            valueColor: (drawdown != null && drawdown > 0) ? AppColors.loss : null,
            monospace: true,
          ),
          DetailRow(
            label: 'Pertes consécutives',
            value: statCount(statNum(global, 'consecutiveLosses')),
            monospace: true,
          ),
          DetailRow(
            label: 'Gains consécutifs',
            value: statCount(statNum(global, 'consecutiveWins')),
            monospace: true,
          ),
          DetailRow(
            label: 'Espérance par trade',
            value: Fmt.signedMoney(expectancy),
            valueColor: expectancy == null ? null : AppColors.forAmount(expectancy),
            monospace: true,
          ),
          const SizedBox(height: AppSpacing.sm),
          Text(
            'Une mesure affichée « -- » n\'est pas calculable sur cette période : '
            'l\'application ne la remplace jamais par zéro.',
            style: Theme.of(context).textTheme.bodySmall,
          ),
        ],
      ),
    );
  }
}

/// Une ligne de ventilation : intitulé, P&L, trades, taux de réussite.
class BreakdownTile extends StatelessWidget {
  const BreakdownTile({super.key, required this.title, this.subtitle, required this.row});

  final String title;
  final String? subtitle;
  final Map<String, dynamic> row;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    final num? pnl = statNum(row, 'pnl');
    return AppCard(
      padding: const EdgeInsets.symmetric(horizontal: AppSpacing.lg, vertical: AppSpacing.md),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.center,
        children: <Widget>[
          Expanded(
            flex: 5,
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
          Expanded(
            flex: 4,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.end,
              children: <Widget>[
                Text(
                  Fmt.signedMoney(pnl),
                  style: theme.textTheme.bodyMedium?.copyWith(
                    fontWeight: FontWeight.w600,
                    color: pnl == null ? null : AppColors.forAmount(pnl),
                  ),
                ),
                const SizedBox(height: 2),
                Text(
                  '${statCount(statNum(row, 'trades'))} trades · '
                  '${Fmt.percent(statNum(row, 'winRate'))}',
                  style: theme.textTheme.bodySmall,
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
