import 'package:flutter/material.dart';

import '../../../core/theme/app_theme.dart';
import '../../../core/widgets/app_widgets.dart';
import '../ai_labels.dart';
import '../models/ai_status.dart';
import 'ai_shell.dart';

/// Fiabilité mesurée de chaque moteur, par type de tâche (CDC2 section 14).
///
/// Le tableau ne tient pas dans 360 points : il défile horizontalement plutôt
/// que d'écraser les colonnes ou de tronquer les chiffres.
class AiMetricsTable extends StatelessWidget {
  const AiMetricsTable({super.key, required this.rows});

  final List<AiMetricRow> rows;

  static const List<String> _columns = <String>[
    'Moteur',
    'Tâche',
    'Appels',
    'Succès',
    'JSON valide',
    'Latence moy.',
    'Délais dépassés',
    'Désaccords',
    'Hallucinations bloquées',
  ];

  @override
  Widget build(BuildContext context) {
    if (rows.isEmpty) {
      return const AiSection(
        title: 'Fiabilité mesurée',
        subtitle: 'Par moteur et par type de tâche.',
        children: <Widget>[
          AiNote(
            text: 'Aucun appel mesuré pour l’instant. Le tableau se remplira dès que le '
                'Bridge aura interrogé un moteur.',
          ),
        ],
      );
    }

    final List<AiMetricRow> sorted = <AiMetricRow>[...rows]..sort((AiMetricRow a, AiMetricRow b) {
        final int byProvider = a.provider.compareTo(b.provider);
        return byProvider != 0 ? byProvider : a.task.compareTo(b.task);
      });

    return AiSection(
      title: 'Fiabilité mesurée',
      subtitle: '${sorted.length} ligne(s). Faites défiler le tableau vers la droite.',
      children: <Widget>[
        SingleChildScrollView(
          scrollDirection: Axis.horizontal,
          child: DataTable(
            headingRowHeight: 40,
            dataRowMinHeight: 40,
            dataRowMaxHeight: 56,
            columnSpacing: AppSpacing.lg,
            horizontalMargin: 0,
            columns: <DataColumn>[
              for (final String column in _columns)
                DataColumn(label: Text(column, style: Theme.of(context).textTheme.labelSmall)),
            ],
            rows: <DataRow>[
              for (final AiMetricRow row in sorted)
                DataRow(
                  cells: <DataCell>[
                    DataCell(Text(AiLabels.provider(row.provider))),
                    DataCell(Text(AiLabels.task(row.task))),
                    DataCell(Text('${row.calls}')),
                    DataCell(Text(AiLabels.rate(row.successRate))),
                    DataCell(Text(AiLabels.rate(row.validJsonRate))),
                    DataCell(Text(AiLabels.latency(row.averageLatencyMs))),
                    DataCell(Text('${row.timeouts}')),
                    DataCell(Text('${row.disagreements}')),
                    DataCell(Text('${row.hallucinationsBlocked}')),
                  ],
                ),
            ],
          ),
        ),
        const SizedBox(height: AppSpacing.md),
        for (final AiMetricRow row in sorted.where((AiMetricRow row) => row.lastError != null))
          DetailRow(
            label:
                'Dernière erreur — ${AiLabels.provider(row.provider)} · ${AiLabels.task(row.task)}',
            value: row.lastError!,
          ),
      ],
    );
  }
}
