import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api/api_exception.dart';
import '../../core/theme/app_colors.dart';
import '../../core/theme/app_theme.dart';
import '../../core/utils/formatters.dart';
import '../../core/widgets/app_widgets.dart';
import 'statistics_providers.dart';
import 'widgets/statistics_blocks.dart';
import 'widgets/statistics_charts.dart';

/// Statistiques de trading (CDC section 36).
///
/// Toutes les mesures viennent du Bridge. Aucune n'est recalculée ici : une
/// valeur absente reste absente et s'affiche `--`.
class StatisticsScreen extends ConsumerWidget {
  const StatisticsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final AsyncValue<Map<String, dynamic>> statistics = ref.watch(statisticsProvider);

    return DefaultTabController(
      length: 5,
      child: Scaffold(
        appBar: AppBar(
          title: const Text('Statistiques'),
          actions: <Widget>[
            IconButton(
              tooltip: 'Actualiser',
              onPressed: () {
                ref.invalidate(statisticsProvider);
                ref.invalidate(statisticsTodayProvider);
              },
              icon: const Icon(Icons.refresh),
            ),
          ],
          bottom: const TabBar(
            isScrollable: true,
            tabAlignment: TabAlignment.start,
            tabs: <Widget>[
              Tab(text: 'Global'),
              Tab(text: 'Par instrument'),
              Tab(text: 'Par jour'),
              Tab(text: 'Par heure'),
              Tab(text: 'Par canal'),
            ],
          ),
        ),
        body: Column(
          children: <Widget>[
            const _FiltersBar(),
            const TodaySummaryStrip(),
            const Divider(height: 1),
            Expanded(
              child: statistics.when(
                loading: () => const LoadingView(label: 'Calcul des statistiques…'),
                error: (Object error, StackTrace stack) => ErrorView(
                  message: error is ApiException ? error.message : 'Statistiques indisponibles.',
                  technical: error is ApiException ? error.technical : error.toString(),
                  onRetry: () => ref.invalidate(statisticsProvider),
                ),
                data: (Map<String, dynamic> data) => _StatisticsTabs(data: data),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// Sélecteurs de période et de mode d'exécution.
class _FiltersBar extends ConsumerWidget {
  const _FiltersBar();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final StatisticsFilter filter = ref.watch(statisticsFilterProvider);
    final bool dark = Theme.of(context).brightness == Brightness.dark;
    final ButtonStyle style = SegmentedButton.styleFrom(
      selectedBackgroundColor:
          dark ? AppColors.primary.withValues(alpha: 0.20) : AppColors.primarySurface,
      selectedForegroundColor: dark ? AppColors.textPrimaryDark : AppColors.primaryDark,
      textStyle: const TextStyle(fontSize: 13, fontWeight: FontWeight.w600),
      visualDensity: VisualDensity.compact,
    );

    return Padding(
      padding: const EdgeInsets.fromLTRB(AppSpacing.lg, AppSpacing.md, AppSpacing.lg, AppSpacing.md),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            child: SegmentedButton<int>(
              style: style,
              showSelectedIcon: false,
              segments: <ButtonSegment<int>>[
                for (final int days in statisticsPeriods)
                  ButtonSegment<int>(value: days, label: Text('$days jours')),
              ],
              selected: <int>{filter.days},
              onSelectionChanged: (Set<int> selection) {
                ref.read(statisticsFilterProvider.notifier).state =
                    filter.copyWith(days: selection.first);
              },
            ),
          ),
          const SizedBox(height: AppSpacing.sm),
          SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            child: SegmentedButton<String>(
              style: style,
              showSelectedIcon: false,
              segments: <ButtonSegment<String>>[
                for (final String mode in statisticsExecutionModes)
                  ButtonSegment<String>(value: mode, label: Text(executionModeLabel(mode))),
              ],
              selected: <String>{filter.executionMode},
              onSelectionChanged: (Set<String> selection) {
                ref.read(statisticsFilterProvider.notifier).state =
                    filter.copyWith(executionMode: selection.first);
              },
            ),
          ),
        ],
      ),
    );
  }
}

/// Les cinq vues demandées par le CDC : global, instrument, jour, heure, canal.
class _StatisticsTabs extends ConsumerWidget {
  const _StatisticsTabs({required this.data});

  final Map<String, dynamic> data;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final Map<String, dynamic> global = statMap(data, 'global');
    final List<Map<String, dynamic>> bySymbol = statRows(data, 'bySymbol');
    final List<Map<String, dynamic>> byDay = statRows(data, 'byDay');
    final List<Map<String, dynamic>> byHour = statRows(data, 'byHour');
    final List<Map<String, dynamic>> byChannel = statRows(data, 'byChannel');
    final Map<int, String> channelNames =
        ref.watch(channelNamesProvider).valueOrNull ?? const <int, String>{};

    return TabBarView(
      children: <Widget>[
        ListView(
          padding: AppSpacing.page,
          children: <Widget>[
            GlobalMetricsCard(global: global),
            const SizedBox(height: AppSpacing.xl),
            AppCard(child: EquityCurveChart(byDay: byDay)),
            const SizedBox(height: AppSpacing.lg),
            AppCard(child: DailyPnlChart(byDay: byDay)),
          ],
        ),
        _BreakdownView(
          rows: bySymbol,
          emptyTitle: 'Aucun instrument',
          emptyMessage: 'Aucun trade fermé sur cette période et ce mode d\'exécution.',
          header: AppCard(child: SymbolBreakdownChart(bySymbol: bySymbol)),
          titleOf: (Map<String, dynamic> row) => (row['symbol'] ?? '--').toString(),
        ),
        _BreakdownView(
          rows: byDay.reversed.toList(growable: false),
          emptyTitle: 'Aucune journée',
          emptyMessage: 'Aucun trade fermé sur cette période et ce mode d\'exécution.',
          titleOf: (Map<String, dynamic> row) => Fmt.day(row['day']),
        ),
        _BreakdownView(
          rows: byHour,
          emptyTitle: 'Aucune heure',
          emptyMessage: 'Aucun trade fermé sur cette période et ce mode d\'exécution.',
          titleOf: (Map<String, dynamic> row) {
            final num? hour = statNum(row, 'hour');
            return hour == null ? '--' : '${hour.round().toString().padLeft(2, '0')} h';
          },
          subtitleOf: (Map<String, dynamic> row) => 'Heure d\'ouverture (UTC)',
        ),
        _BreakdownView(
          rows: byChannel,
          emptyTitle: 'Aucun canal',
          emptyMessage: 'Aucun trade fermé sur cette période et ce mode d\'exécution.',
          titleOf: (Map<String, dynamic> row) {
            final num? id = statNum(row, 'channelId');
            if (id == null) return 'Sans canal d\'origine';
            return channelNames[id.toInt()] ?? 'Canal ${id.toInt()}';
          },
          subtitleOf: (Map<String, dynamic> row) {
            final num? id = statNum(row, 'channelId');
            return id == null ? null : 'Canal ${id.toInt()}';
          },
        ),
      ],
    );
  }
}

/// Liste générique de ventilation avec en-tête facultatif et état vide.
class _BreakdownView extends StatelessWidget {
  const _BreakdownView({
    required this.rows,
    required this.titleOf,
    required this.emptyTitle,
    required this.emptyMessage,
    this.subtitleOf,
    this.header,
  });

  final List<Map<String, dynamic>> rows;
  final String Function(Map<String, dynamic> row) titleOf;
  final String? Function(Map<String, dynamic> row)? subtitleOf;
  final String emptyTitle;
  final String emptyMessage;
  final Widget? header;

  @override
  Widget build(BuildContext context) {
    if (rows.isEmpty) {
      return EmptyState(
        title: emptyTitle,
        message: emptyMessage,
        icon: Icons.bar_chart_outlined,
      );
    }
    return ListView.separated(
      padding: AppSpacing.page,
      itemCount: rows.length + (header == null ? 0 : 1),
      separatorBuilder: (BuildContext context, int index) => const SizedBox(height: AppSpacing.sm),
      itemBuilder: (BuildContext context, int index) {
        if (header != null) {
          if (index == 0) {
            return Padding(
              padding: const EdgeInsets.only(bottom: AppSpacing.md),
              child: header,
            );
          }
          index -= 1;
        }
        final Map<String, dynamic> row = rows[index];
        return BreakdownTile(
          title: titleOf(row),
          subtitle: subtitleOf?.call(row),
          row: row,
        );
      },
    );
  }
}
