import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api/api_exception.dart';
import '../../core/theme/app_theme.dart';
import '../../core/widgets/app_widgets.dart';
import 'ai_config_providers.dart';
import 'models/ai_status.dart';
import 'widgets/ai_diagnostic_sections.dart';
import 'widgets/ai_metrics_table.dart';

/// Diagnostic IA (CDC2 section 96).
///
/// Écran de lecture seule : il montre ce que le Bridge mesure, sans rien
/// déclencher ni rien reformuler.
class AiDiagnosticScreen extends ConsumerWidget {
  const AiDiagnosticScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final AsyncValue<AiStatus> status = ref.watch(aiStatusProvider);

    return Scaffold(
      appBar: AppBar(
        title: const Text('Diagnostic IA'),
        actions: <Widget>[
          IconButton(
            tooltip: 'Actualiser',
            onPressed: () {
              ref.invalidate(aiStatusProvider);
              ref.invalidate(aiMetricsProvider);
            },
            icon: const Icon(Icons.refresh),
          ),
        ],
      ),
      body: RefreshIndicator(
        onRefresh: () async {
          ref.invalidate(aiStatusProvider);
          ref.invalidate(aiMetricsProvider);
          await ref.read(aiStatusProvider.future);
        },
        child: status.when(
          loading: () => const LoadingView(label: 'Interrogation des moteurs…'),
          error: (Object error, StackTrace stack) => ErrorView(
            message: error is ApiException ? error.message : 'Diagnostic IA indisponible.',
            technical: error is ApiException ? error.technical : error.toString(),
            onRetry: () => ref.invalidate(aiStatusProvider),
          ),
          data: (AiStatus data) => _DiagnosticBody(status: data),
        ),
      ),
    );
  }
}

class _DiagnosticBody extends ConsumerWidget {
  const _DiagnosticBody({required this.status});

  final AiStatus status;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final AsyncValue<List<AiMetricRow>> metrics = ref.watch(aiMetricsProvider);

    return ListView(
      padding: AppSpacing.page,
      physics: const AlwaysScrollableScrollPhysics(),
      children: <Widget>[
        AiProviderCard(state: status.openRouter, title: 'OpenRouter'),
        AiRouterCard(status: status),
        AiConsensusCard(status: status),
        metrics.when(
          loading: () => const SizedBox(height: 120, child: LoadingView()),
          error: (Object error, StackTrace stack) => ErrorView(
            message: error is ApiException ? error.message : 'Mesures indisponibles.',
            technical: error is ApiException ? error.technical : error.toString(),
            onRetry: () => ref.invalidate(aiMetricsProvider),
          ),
          data: (List<AiMetricRow> rows) => AiMetricsTable(rows: rows),
        ),
        const SizedBox(height: AppSpacing.xl),
      ],
    );
  }
}
