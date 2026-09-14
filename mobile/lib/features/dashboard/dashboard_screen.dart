import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/connection/connection_controller.dart';
import '../../core/providers/bridge_data.dart';
import '../../core/theme/app_colors.dart';
import '../../core/theme/app_theme.dart';
import '../../core/utils/formatters.dart';
import '../../core/widgets/app_widgets.dart';
import '../bridge/models/bridge_json.dart';
import '../bridge/widgets/bridge_error_view.dart';
import 'widgets/dashboard_actions.dart';
import 'widgets/dashboard_header.dart';
import 'widgets/dashboard_lists.dart';
import 'widgets/dashboard_metrics.dart';
import 'widgets/dashboard_status_bar.dart';

/// Accueil de l'application (CDC section 31).
///
/// Rassemble le mode d'exécution, les chiffres du compte, l'état des quatre
/// liaisons, les listes récentes et les deux commandes de pilotage.
class DashboardScreen extends ConsumerWidget {
  const DashboardScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final AsyncValue<BridgeData<Map<String, dynamic>>> dashboard = ref.watch(dashboardProvider);

    return Scaffold(
      appBar: AppBar(
        title: const Text('Accueil'),
        actions: <Widget>[
          IconButton(
            tooltip: 'Actualiser',
            onPressed: () => refreshBridgeData(ref),
            icon: const Icon(Icons.refresh),
          ),
        ],
      ),
      body: dashboard.when(
        loading: () => const LoadingView(label: 'Chargement du tableau de bord…'),
        error: (Object error, StackTrace _) => BridgeErrorView(
          error: error,
          onRetry: () => refreshBridgeData(ref),
        ),
        data: (BridgeData<Map<String, dynamic>> data) => RefreshIndicator(
          color: AppColors.primary,
          onRefresh: () async => refreshBridgeData(ref),
          child: _DashboardBody(data: data),
        ),
      ),
    );
  }
}

class _DashboardBody extends ConsumerWidget {
  const _DashboardBody({required this.data});

  final BridgeData<Map<String, dynamic>> data;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final Map<String, dynamic> payload = data.value;
    final BridgeConnectionState connection = ref.watch(connectionProvider);
    final bool bridgeOnline = connection.online && !data.stale;
    final String currency = Json.text(Json.map(payload['metrics'])['currency']) ?? 'USD';

    return ListView(
      physics: const AlwaysScrollableScrollPhysics(),
      padding: AppSpacing.page,
      children: <Widget>[
        if (data.stale) ...<Widget>[
          _StaleNotice(updatedAt: data.updatedAt),
          const SizedBox(height: AppSpacing.lg),
        ],
        DashboardHeader(payload: payload),
        const SizedBox(height: AppSpacing.lg),
        DashboardStatusBar(payload: payload, bridgeOnline: bridgeOnline),
        const SizedBox(height: AppSpacing.xl),
        DashboardMetrics(payload: payload),
        const SizedBox(height: AppSpacing.xl),
        OpenPositionsSection(
          positions: Json.objects(payload['openPositions']),
          currency: currency,
        ),
        const SizedBox(height: AppSpacing.xl),
        RecentSignalsSection(signals: Json.objects(payload['recentSignals'])),
        const SizedBox(height: AppSpacing.xl),
        RecentEventsSection(events: Json.objects(payload['recentEvents'])),
        const SizedBox(height: AppSpacing.xxl),

        // Hors ligne, aucun bouton susceptible d'envoyer un ordre n'est
        // affiché : l'application ne prétend jamais avoir agi (CDC section 40).
        if (data.stale)
          DashboardOfflineActions(updatedAt: data.updatedAt)
        else
          DashboardActions(payload: payload),
        const SizedBox(height: AppSpacing.xxl),
      ],
    );
  }
}

/// Rappel discret que les chiffres affichés viennent du dernier instantané.
class _StaleNotice extends StatelessWidget {
  const _StaleNotice({this.updatedAt});

  final DateTime? updatedAt;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    return Row(
      children: <Widget>[
        const Icon(Icons.history_toggle_off, size: 16, color: AppColors.warning),
        const SizedBox(width: AppSpacing.sm),
        Expanded(
          child: Text(
            updatedAt == null
                ? 'Données en cache — Bridge hors ligne'
                : 'Données du ${Fmt.time(updatedAt)} — Bridge hors ligne',
            style: theme.textTheme.bodySmall?.copyWith(color: AppColors.warning),
          ),
        ),
      ],
    );
  }
}
