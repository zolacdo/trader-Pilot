import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/api/api_exception.dart';
import '../../../core/api/endpoints.dart';
import '../../../core/connection/connection_controller.dart';
import '../../../core/providers/bridge_data.dart';
import '../../../core/routing/app_router.dart';
import '../../../core/theme/app_colors.dart';
import '../../../core/theme/app_theme.dart';
import '../../../core/utils/formatters.dart';
import '../../../core/widgets/app_widgets.dart';
import '../../bridge/models/bridge_json.dart';

/// Les deux commandes de l'accueil, volontairement séparées (CDC section 32).
///
/// « PAUSE AUTO TRADING » est un bouton secondaire qui suspend uniquement les
/// nouveaux trades. « URGENCE » est un bouton rouge, isolé par un espace net,
/// qui ouvre un écran dédié et ne déclenche rien par lui-même.
class DashboardActions extends ConsumerStatefulWidget {
  const DashboardActions({super.key, required this.payload});

  final Map<String, dynamic> payload;

  @override
  ConsumerState<DashboardActions> createState() => _DashboardActionsState();
}

class _DashboardActionsState extends ConsumerState<DashboardActions> {
  bool _busy = false;

  Future<void> _setPaused({required bool pause}) async {
    if (_busy) return;
    setState(() => _busy = true);
    try {
      if (pause) {
        await ref.read(apiClientProvider).postJson(
          Endpoints.tradingPause,
          body: <String, dynamic>{'reason': 'Pause demandée depuis l\'application'},
        );
      } else {
        await ref.read(apiClientProvider).postJson(Endpoints.tradingResume);
      }
      if (!mounted) return;
      showToast(
        context,
        pause
            ? 'Trading automatique en pause. Les positions ouvertes restent ouvertes.'
            : 'Trading automatique repris.',
      );
      refreshBridgeData(ref);
    } on ApiException catch (error) {
      if (!mounted) return;
      showToast(context, error.message, error: true);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    final Map<String, dynamic> trading = Json.map(widget.payload['trading']);
    final bool paused = Json.flag(trading['paused']);
    final String? reason = Json.text(trading['pauseReason']);
    final String? until = Json.text(trading['pausedUntil']);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        const SectionHeader(title: 'Pilotage'),
        AppCard(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: <Widget>[
              Row(
                children: <Widget>[
                  Expanded(
                    child: Text(
                      paused ? 'Automatisation en pause' : 'Automatisation active',
                      style: theme.textTheme.titleMedium,
                    ),
                  ),
                  StatusChip(
                    label: paused ? 'En pause' : 'En marche',
                    tone: paused ? StatusTone.warning : StatusTone.good,
                    dense: true,
                  ),
                ],
              ),
              const SizedBox(height: AppSpacing.sm),
              Text(
                'La pause arrête uniquement les NOUVEAUX trades automatiques. '
                'Aucune position ouverte n\'est fermée.',
                style: theme.textTheme.bodySmall,
              ),
              if (paused && reason != null) ...<Widget>[
                const SizedBox(height: AppSpacing.md),
                DetailRow(label: 'Motif', value: reason),
                if (until != null) DetailRow(label: 'Jusqu\'à', value: Fmt.full(until)),
              ],
              const SizedBox(height: AppSpacing.lg),
              SizedBox(
                width: double.infinity,
                child: OutlinedButton.icon(
                  onPressed: _busy ? null : () => _setPaused(pause: !paused),
                  icon: _busy
                      ? const SizedBox(
                          width: 16,
                          height: 16,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                      : Icon(paused ? Icons.play_arrow_outlined : Icons.pause_outlined, size: 18),
                  label: Text(paused ? 'REPRENDRE LE TRADING AUTO' : 'PAUSE AUTO TRADING'),
                ),
              ),
            ],
          ),
        ),

        // Espace net : le bouton d'urgence ne doit jamais être confondu
        // avec le bouton de pause.
        const SizedBox(height: AppSpacing.xxl),
        const Divider(),
        const SizedBox(height: AppSpacing.xl),

        Text('En cas de problème', style: theme.textTheme.titleMedium),
        const SizedBox(height: AppSpacing.xs),
        Text(
          'L\'écran d\'urgence permet d\'annuler les ordres en attente ou de '
          'fermer toutes les positions. Le bouton ci-dessous ouvre cet écran : '
          'il ne ferme rien par lui-même.',
          style: theme.textTheme.bodySmall,
        ),
        const SizedBox(height: AppSpacing.lg),
        SizedBox(
          width: double.infinity,
          child: FilledButton.icon(
            onPressed: () => context.push(Routes.emergency),
            style: FilledButton.styleFrom(backgroundColor: AppColors.loss),
            icon: const Icon(Icons.warning_amber_rounded, size: 20),
            label: const Text('URGENCE'),
          ),
        ),
      ],
    );
  }
}

/// Remplace les commandes lorsque les données viennent du cache : hors ligne,
/// aucun ordre ne peut partir et l'application ne prétend pas le contraire.
class DashboardOfflineActions extends StatelessWidget {
  const DashboardOfflineActions({super.key, this.updatedAt});

  final DateTime? updatedAt;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Row(
            children: <Widget>[
              const Icon(Icons.cloud_off_outlined, size: 18, color: AppColors.warning),
              const SizedBox(width: AppSpacing.sm),
              Text('Commandes indisponibles', style: theme.textTheme.titleMedium),
            ],
          ),
          const SizedBox(height: AppSpacing.sm),
          Text(
            updatedAt == null
                ? 'Le Bridge ne répond pas : aucune commande ne peut lui être envoyée.'
                : 'Données du ${Fmt.time(updatedAt)} — Bridge hors ligne. '
                    'Aucune commande ne peut lui être envoyée.',
            style: theme.textTheme.bodySmall,
          ),
        ],
      ),
    );
  }
}
