import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/ws_client.dart';
import '../../../core/connection/connection_controller.dart';
import '../../../core/theme/app_colors.dart';
import '../../../core/theme/app_theme.dart';
import '../../../core/widgets/app_widgets.dart';
import '../../bridge/models/bridge_json.dart';
import '../../bridge/models/bridge_labels.dart';

/// En-tête de l'accueil : mode d'exécution, type de compte, temps réel.
///
/// Le mode d'exécution est l'information la plus importante de l'écran :
/// l'utilisateur doit savoir en un coup d'œil si des ordres réels partent
/// (CDC section 10).
class DashboardHeader extends StatelessWidget {
  const DashboardHeader({super.key, required this.payload});

  final Map<String, dynamic> payload;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    final Map<String, dynamic> trading = Json.map(payload['trading']);
    final Map<String, dynamic> account = Json.map(payload['account']);

    final String? mode = Json.text(trading['executionMode']);
    final String? kind = Json.text(account['kind']);
    final bool live = mode == 'MT5_LIVE';

    return AppCard(
      accent: live,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Text('MODE D\'EXÉCUTION', style: theme.textTheme.labelSmall),
          const SizedBox(height: AppSpacing.xs),
          Row(
            crossAxisAlignment: CrossAxisAlignment.center,
            children: <Widget>[
              Expanded(
                child: Text(
                  BridgeLabels.executionMode(mode),
                  style: theme.textTheme.headlineSmall?.copyWith(
                    color: live ? AppColors.loss : null,
                  ),
                ),
              ),
              StatusChip(
                label: BridgeLabels.accountKind(kind),
                tone: BridgeLabels.accountTone(kind),
                icon: kind == 'REAL' ? Icons.warning_amber_rounded : null,
              ),
            ],
          ),
          const SizedBox(height: AppSpacing.sm),
          Text(BridgeLabels.executionModeDetail(mode), style: theme.textTheme.bodySmall),
          const Divider(height: AppSpacing.xl),
          const LiveIndicator(),
        ],
      ),
    );
  }
}

/// Indicateur temps réel : état réel de la liaison WebSocket, jamais simulé.
class LiveIndicator extends ConsumerWidget {
  const LiveIndicator({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final ThemeData theme = Theme.of(context);
    final WsClient ws = ref.watch(wsClientProvider);

    return ValueListenableBuilder<WsStatus>(
      valueListenable: ws.status,
      builder: (BuildContext context, WsStatus status, Widget? _) {
        final ({String label, StatusTone tone, IconData icon}) view = switch (status) {
          WsStatus.connected => (
              label: 'Temps réel actif',
              tone: StatusTone.good,
              icon: Icons.bolt_outlined,
            ),
          WsStatus.connecting => (
              label: 'Reconnexion en cours…',
              tone: StatusTone.warning,
              icon: Icons.sync,
            ),
          WsStatus.disconnected => (
              label: 'Temps réel interrompu',
              tone: StatusTone.bad,
              icon: Icons.bolt_outlined,
            ),
        };

        return Row(
          children: <Widget>[
            StatusChip(label: view.label, tone: view.tone, icon: view.icon, dense: true),
            const SizedBox(width: AppSpacing.sm),
            Expanded(
              child: Text(
                status == WsStatus.connected
                    ? 'Les valeurs se mettent à jour dès que le Bridge envoie un événement.'
                    : 'Les valeurs affichées peuvent dater : tirez vers le bas pour actualiser.',
                style: theme.textTheme.bodySmall,
              ),
            ),
          ],
        );
      },
    );
  }
}
