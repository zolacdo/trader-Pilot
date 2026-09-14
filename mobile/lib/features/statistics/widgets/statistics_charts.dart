import 'dart:math' as math;

import 'package:fl_chart/fl_chart.dart';
import 'package:flutter/material.dart';

import '../../../core/theme/app_colors.dart';
import '../../../core/theme/app_theme.dart';
import '../statistics_providers.dart';

/// Hauteur commune aux trois graphiques : assez grande pour être lisible,
/// assez petite pour rester discrète.
const double _chartHeight = 170;

/// Aucune animation : un graphique de résultats n'a rien à mettre en scène.
const Duration _noAnimation = Duration.zero;

/// Cartouche commun : un titre, une phrase d'explication, le graphique.
class ChartFrame extends StatelessWidget {
  const ChartFrame({super.key, required this.title, required this.caption, required this.child});

  final String title;
  final String caption;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        Text(title, style: theme.textTheme.titleMedium),
        const SizedBox(height: 2),
        Text(caption, style: theme.textTheme.bodySmall),
        const SizedBox(height: AppSpacing.lg),
        SizedBox(height: _chartHeight, child: child),
      ],
    );
  }
}

/// Message affiché à la place d'un graphique quand il n'y a rien à tracer.
class _NoChartData extends StatelessWidget {
  const _NoChartData();

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Text(
        'Aucun trade fermé sur la période.',
        style: Theme.of(context).textTheme.bodySmall,
      ),
    );
  }
}

TextStyle _axisStyle(BuildContext context) {
  return Theme.of(context).textTheme.bodySmall?.copyWith(fontSize: 10.5) ??
      const TextStyle(fontSize: 10.5);
}

FlGridData _grid(BuildContext context) {
  final Color line = Theme.of(context).colorScheme.outline;
  return FlGridData(
    drawVerticalLine: false,
    getDrawingHorizontalLine: (double value) => FlLine(color: line, strokeWidth: 1),
  );
}

/// Abrège un montant pour un axe : 1 250 devient « 1.3 k ».
String _shortAmount(double value) {
  final double abs = value.abs();
  if (abs >= 1000) return '${(value / 1000).toStringAsFixed(1)} k';
  if (abs >= 10) return value.toStringAsFixed(0);
  return value.toStringAsFixed(1);
}

/// Étiquette « JJ/MM » à partir d'une date ISO `AAAA-MM-JJ`.
String _shortDay(String iso) {
  if (iso.length < 10) return iso;
  return '${iso.substring(8, 10)}/${iso.substring(5, 7)}';
}

/// Intervalle d'étiquettes pour ne jamais dépasser cinq libellés sur un axe.
double _labelInterval(int count) => math.max(1, (count / 5).ceilToDouble());

/// Amplitude minimale d'un axe, pour qu'une série plate reste lisible.
double _atLeastOne(double value) => value < 1 ? 1 : value;

/// Axe vertical commun aux trois graphiques : des montants abrégés.
AxisTitles _amountAxis(BuildContext context) {
  final TextStyle style = _axisStyle(context);
  return AxisTitles(
    sideTitles: SideTitles(
      showTitles: true,
      reservedSize: 44,
      getTitlesWidget: (double value, TitleMeta meta) => SideTitleWidget(
        axisSide: meta.axisSide,
        space: 6,
        child: Text(_shortAmount(value), style: style),
      ),
    ),
  );
}

// ---------------------------------------------------------------------------
// Courbe d'équité cumulée
// ---------------------------------------------------------------------------

/// Somme cumulée des P&L journaliers, dans l'ordre chronologique de `byDay`.
class EquityCurveChart extends StatelessWidget {
  const EquityCurveChart({super.key, required this.byDay});

  final List<Map<String, dynamic>> byDay;

  @override
  Widget build(BuildContext context) {
    final List<Map<String, dynamic>> days = byDay
        .where((Map<String, dynamic> row) => statNum(row, 'pnl') != null)
        .toList(growable: false);
    if (days.isEmpty) {
      return const ChartFrame(
        title: 'Courbe d\'équité cumulée',
        caption: 'Somme des résultats fermés, jour après jour.',
        child: _NoChartData(),
      );
    }

    double cumulative = 0;
    final List<FlSpot> spots = <FlSpot>[];
    for (int index = 0; index < days.length; index++) {
      cumulative += statNum(days[index], 'pnl')!.toDouble();
      spots.add(FlSpot(index.toDouble(), cumulative));
    }

    double minY = spots.first.y;
    double maxY = spots.first.y;
    for (final FlSpot spot in spots) {
      minY = math.min(minY, spot.y);
      maxY = math.max(maxY, spot.y);
    }
    final double padding = _atLeastOne((maxY - minY).abs() * 0.15);
    final TextStyle axisStyle = _axisStyle(context);

    return ChartFrame(
      title: 'Courbe d\'équité cumulée',
      caption: 'Somme des résultats fermés, jour après jour.',
      child: LineChart(
        LineChartData(
          minY: minY - padding,
          maxY: maxY + padding,
          gridData: _grid(context),
          borderData: FlBorderData(show: false),
          lineTouchData: const LineTouchData(enabled: false),
          titlesData: FlTitlesData(
            topTitles: const AxisTitles(),
            rightTitles: const AxisTitles(),
            leftTitles: _amountAxis(context),
            bottomTitles: AxisTitles(
              sideTitles: SideTitles(
                showTitles: true,
                reservedSize: 24,
                interval: _labelInterval(days.length),
                getTitlesWidget: (double value, TitleMeta meta) {
                  final int index = value.round();
                  if (index < 0 || index >= days.length) return const SizedBox.shrink();
                  return SideTitleWidget(
                    axisSide: meta.axisSide,
                    space: 6,
                    child: Text(_shortDay((days[index]['day'] ?? '').toString()), style: axisStyle),
                  );
                },
              ),
            ),
          ),
          lineBarsData: <LineChartBarData>[
            LineChartBarData(
              spots: spots,
              isCurved: false,
              color: AppColors.primary,
              barWidth: 2,
              dotData: const FlDotData(show: false),
            ),
          ],
        ),
        duration: _noAnimation,
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Histogramme du P&L par jour
// ---------------------------------------------------------------------------

/// Une barre par journée : verte au-dessus de zéro, rouge en dessous.
class DailyPnlChart extends StatelessWidget {
  const DailyPnlChart({super.key, required this.byDay});

  final List<Map<String, dynamic>> byDay;

  @override
  Widget build(BuildContext context) {
    final List<Map<String, dynamic>> days = byDay
        .where((Map<String, dynamic> row) => statNum(row, 'pnl') != null)
        .toList(growable: false);
    if (days.isEmpty) {
      return const ChartFrame(
        title: 'P&L par jour',
        caption: 'Résultat net de chaque journée de clôture.',
        child: _NoChartData(),
      );
    }

    final List<double> values = days
        .map((Map<String, dynamic> row) => statNum(row, 'pnl')!.toDouble())
        .toList(growable: false);
    final double span = _axisSpan(values);
    final TextStyle axisStyle = _axisStyle(context);

    return ChartFrame(
      title: 'P&L par jour',
      caption: 'Résultat net de chaque journée de clôture.',
      child: BarChart(
        BarChartData(
          minY: -span,
          maxY: span,
          alignment: BarChartAlignment.spaceBetween,
          gridData: _grid(context),
          borderData: FlBorderData(show: false),
          barTouchData: BarTouchData(enabled: false),
          titlesData: FlTitlesData(
            topTitles: const AxisTitles(),
            rightTitles: const AxisTitles(),
            leftTitles: _amountAxis(context),
            bottomTitles: AxisTitles(
              sideTitles: SideTitles(
                showTitles: true,
                reservedSize: 24,
                interval: _labelInterval(days.length),
                getTitlesWidget: (double value, TitleMeta meta) {
                  final int index = value.round();
                  if (index < 0 || index >= days.length) return const SizedBox.shrink();
                  return SideTitleWidget(
                    axisSide: meta.axisSide,
                    space: 6,
                    child: Text(_shortDay((days[index]['day'] ?? '').toString()), style: axisStyle),
                  );
                },
              ),
            ),
          ),
          barGroups: _bars(values, width: 6),
        ),
        duration: _noAnimation,
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Ventilation par instrument
// ---------------------------------------------------------------------------

/// P&L par instrument, limité aux dix instruments les plus significatifs.
class SymbolBreakdownChart extends StatelessWidget {
  const SymbolBreakdownChart({super.key, required this.bySymbol});

  final List<Map<String, dynamic>> bySymbol;

  @override
  Widget build(BuildContext context) {
    final List<Map<String, dynamic>> rows = bySymbol
        .where((Map<String, dynamic> row) => statNum(row, 'pnl') != null)
        .toList()
      ..sort((Map<String, dynamic> a, Map<String, dynamic> b) =>
          statNum(b, 'pnl')!.abs().compareTo(statNum(a, 'pnl')!.abs()));
    final List<Map<String, dynamic>> top = rows.take(10).toList(growable: false);

    if (top.isEmpty) {
      return const ChartFrame(
        title: 'P&L par instrument',
        caption: 'Instruments aux résultats les plus marqués.',
        child: _NoChartData(),
      );
    }

    final List<double> values = top
        .map((Map<String, dynamic> row) => statNum(row, 'pnl')!.toDouble())
        .toList(growable: false);
    final double span = _axisSpan(values);
    final TextStyle axisStyle = _axisStyle(context);

    return ChartFrame(
      title: 'P&L par instrument',
      caption: 'Instruments aux résultats les plus marqués.',
      child: BarChart(
        BarChartData(
          minY: -span,
          maxY: span,
          alignment: BarChartAlignment.spaceAround,
          gridData: _grid(context),
          borderData: FlBorderData(show: false),
          barTouchData: BarTouchData(enabled: false),
          titlesData: FlTitlesData(
            topTitles: const AxisTitles(),
            rightTitles: const AxisTitles(),
            leftTitles: _amountAxis(context),
            bottomTitles: AxisTitles(
              sideTitles: SideTitles(
                showTitles: true,
                reservedSize: 30,
                getTitlesWidget: (double value, TitleMeta meta) {
                  final int index = value.round();
                  if (index < 0 || index >= top.length) return const SizedBox.shrink();
                  return SideTitleWidget(
                    axisSide: meta.axisSide,
                    space: 6,
                    child: Text(
                      (top[index]['symbol'] ?? '--').toString(),
                      style: axisStyle,
                      overflow: TextOverflow.ellipsis,
                    ),
                  );
                },
              ),
            ),
          ),
          barGroups: _bars(values, width: 14),
        ),
        duration: _noAnimation,
      ),
    );
  }
}

/// Amplitude symétrique de l'axe vertical d'un histogramme.
double _axisSpan(List<double> values) {
  double largest = 0;
  for (final double value in values) {
    largest = math.max(largest, value.abs());
  }
  return _atLeastOne(largest * 1.15);
}

/// Barres verticales : vert au-dessus de zéro, rouge en dessous.
List<BarChartGroupData> _bars(List<double> values, {required double width}) {
  return <BarChartGroupData>[
    for (int index = 0; index < values.length; index++)
      BarChartGroupData(
        x: index,
        barRods: <BarChartRodData>[
          BarChartRodData(
            toY: values[index],
            width: width,
            color: values[index] < 0 ? AppColors.loss : AppColors.profit,
            borderRadius: BorderRadius.zero,
          ),
        ],
      ),
  ];
}
