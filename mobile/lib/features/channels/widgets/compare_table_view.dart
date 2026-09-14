import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/routing/app_router.dart';
import '../../../core/theme/app_colors.dart';
import '../../../core/theme/app_theme.dart';
import '../../../core/utils/formatters.dart';
import '../models/channel.dart';
import '../models/discovery.dart';

/// Colonne triable du tableau de comparaison.
@immutable
class _Column {
  const _Column({required this.label, required this.numeric, required this.value});

  final String label;
  final bool numeric;

  /// Valeur comparable de la ligne, `null` quand la mesure n'existe pas.
  final Comparable<Object>? Function(CompareRow row) value;
}

/// Ordre de tri courant : index de colonne et sens.
@immutable
class CompareSort {
  const CompareSort({this.columnIndex = 0, this.ascending = true});

  final int columnIndex;
  final bool ascending;
}

final AutoDisposeStateProvider<CompareSort> compareSortProvider =
    StateProvider.autoDispose<CompareSort>((Ref ref) => const CompareSort());

const List<_Column> _columns = <_Column>[
  _Column(label: 'Canal', numeric: false, value: _titleOf),
  _Column(label: 'Signaux détectés', numeric: true, value: _signalsOf),
  _Column(label: 'Taux de parsing', numeric: true, value: _parseOf),
  _Column(label: 'Taux SL', numeric: true, value: _slOf),
  _Column(label: 'Taux TP', numeric: true, value: _tpOf),
  _Column(label: 'Fréquence / jour', numeric: true, value: _frequencyOf),
  _Column(label: 'Trades paper', numeric: true, value: _paperTradesOf),
  _Column(label: 'P&L paper', numeric: true, value: _paperPnlOf),
  _Column(label: 'Réussite paper', numeric: true, value: _paperWinOf),
  _Column(label: 'Drawdown paper', numeric: true, value: _paperDdOf),
  _Column(label: 'R moyen', numeric: true, value: _averageROf),
  _Column(label: 'Historique', numeric: false, value: _historyOf),
];

Comparable<Object>? _titleOf(CompareRow row) => row.title.toLowerCase();
Comparable<Object>? _signalsOf(CompareRow row) => row.signalsDetected;
Comparable<Object>? _parseOf(CompareRow row) => row.parseRate;
Comparable<Object>? _slOf(CompareRow row) => row.slRate;
Comparable<Object>? _tpOf(CompareRow row) => row.tpRate;
Comparable<Object>? _frequencyOf(CompareRow row) => row.signalsPerDay;
Comparable<Object>? _paperTradesOf(CompareRow row) => row.paperTrades;
Comparable<Object>? _paperPnlOf(CompareRow row) => row.paperPnl;
Comparable<Object>? _paperWinOf(CompareRow row) => row.paperWinRate;
Comparable<Object>? _paperDdOf(CompareRow row) => row.paperDrawdown;
Comparable<Object>? _averageROf(CompareRow row) => row.averageR;
Comparable<Object>? _historyOf(CompareRow row) => row.historyAvailable ? 1 : 0;

/// Tableau comparatif défilable horizontalement (CDC section 72).
///
/// Aucun canal n'est désigné comme meilleur : les colonnes sont des mesures
/// observées, l'utilisateur juge lui-même.
class CompareTableView extends ConsumerWidget {
  const CompareTableView({super.key, required this.rows});

  final List<CompareRow> rows;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final CompareSort sort = ref.watch(compareSortProvider);
    final List<CompareRow> sorted = _sorted(rows, sort);

    return SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      child: DataTable(
        sortColumnIndex: sort.columnIndex,
        sortAscending: sort.ascending,
        headingRowHeight: 48,
        dataRowMinHeight: 44,
        dataRowMaxHeight: 56,
        columnSpacing: AppSpacing.xl,
        border: TableBorder(
          horizontalInside: BorderSide(color: Theme.of(context).colorScheme.outline),
        ),
        columns: <DataColumn>[
          for (int index = 0; index < _columns.length; index++)
            DataColumn(
              label: Text(_columns[index].label),
              numeric: _columns[index].numeric,
              onSort: (int columnIndex, bool ascending) =>
                  ref.read(compareSortProvider.notifier).state =
                      CompareSort(columnIndex: columnIndex, ascending: ascending),
            ),
        ],
        rows: <DataRow>[
          for (final CompareRow row in sorted) _dataRow(context, row),
        ],
      ),
    );
  }

  static List<CompareRow> _sorted(List<CompareRow> rows, CompareSort sort) {
    final _Column column = _columns[sort.columnIndex.clamp(0, _columns.length - 1)];
    final List<CompareRow> copy = List<CompareRow>.of(rows);
    copy.sort((CompareRow a, CompareRow b) {
      final Comparable<Object>? left = column.value(a);
      final Comparable<Object>? right = column.value(b);
      // Une mesure absente reste en fin de tableau, dans les deux sens.
      if (left == null && right == null) return 0;
      if (left == null) return 1;
      if (right == null) return -1;
      final int result = left.compareTo(right as Object);
      return sort.ascending ? result : -result;
    });
    return copy;
  }

  static DataRow _dataRow(BuildContext context, CompareRow row) {
    final bool dark = Theme.of(context).brightness == Brightness.dark;
    return DataRow(
      onSelectChanged: row.channelId == 0
          ? null
          : (_) => context.push(Routes.channelDetail(row.channelId)),
      cells: <DataCell>[
        DataCell(
          ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 180),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisAlignment: MainAxisAlignment.center,
              children: <Widget>[
                Text(row.title, maxLines: 1, overflow: TextOverflow.ellipsis),
                Text(
                  row.username == null ? '--' : '@${row.username}',
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: Theme.of(context).textTheme.bodySmall,
                ),
              ],
            ),
          ),
        ),
        DataCell(Text(formatCount(row.signalsDetected))),
        DataCell(Text(formatRate(row.parseRate))),
        DataCell(Text(formatRate(row.slRate))),
        DataCell(Text(formatRate(row.tpRate))),
        DataCell(Text(formatDecimal(row.signalsPerDay))),
        DataCell(Text(formatCount(row.paperTrades))),
        DataCell(
          Text(
            Fmt.signedMoney(row.paperPnl),
            style: TextStyle(
              fontWeight: FontWeight.w600,
              color: row.paperPnl == null ? null : AppColors.forAmount(row.paperPnl!, dark: dark),
            ),
          ),
        ),
        DataCell(Text(formatRate(row.paperWinRate))),
        DataCell(Text(row.paperDrawdown == null ? '--' : Fmt.money(row.paperDrawdown))),
        DataCell(
          Text(row.averageR == null ? '--' : '${formatDecimal(row.averageR, digits: 2)} R'),
        ),
        DataCell(Text(row.historyAvailable ? 'Disponible' : 'Indisponible')),
      ],
    );
  }
}
