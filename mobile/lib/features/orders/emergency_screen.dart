import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api/api_exception.dart';
import '../../core/api/endpoints.dart';
import '../../core/connection/connection_controller.dart';
import '../../core/providers/bridge_data.dart';
import '../../core/theme/app_colors.dart';
import '../../core/theme/app_theme.dart';
import '../../core/widgets/app_widgets.dart';
import '../bridge/models/bridge_json.dart';
import '../bridge/models/bridge_labels.dart';
import '../bridge/widgets/bridge_error_view.dart';
import 'providers/emergency_providers.dart';
import 'widgets/emergency_action_card.dart';

/// Action d'urgence en cours, pour n'autoriser qu'un envoi à la fois.
enum _Running { none, cancelPending, closeAll, closeAndSuspend }

/// Écran d'arrêt d'urgence (CDC section 32).
///
/// Écran distinct et jamais un simple bouton : chaque action est expliquée,
/// chiffrée, et l'action irréversible se trouve tout en bas, protégée par une
/// phrase de confirmation exacte.
class EmergencyScreen extends ConsumerStatefulWidget {
  const EmergencyScreen({super.key});

  @override
  ConsumerState<EmergencyScreen> createState() => _EmergencyScreenState();
}

class _EmergencyScreenState extends ConsumerState<EmergencyScreen> {
  _Running _running = _Running.none;

  Future<void> _cancelPending(EmergencyOverview overview) async {
    final bool confirmed = await confirmAction(
      context,
      title: 'Annuler les ordres en attente',
      message: 'Les ${overview.orderCount ?? 0} ordre(s) en attente seront retirés '
          'du carnet. Les positions déjà ouvertes ne sont pas touchées.',
      confirmLabel: 'Annuler les ordres',
      cancelLabel: 'Revenir',
    );
    if (!confirmed) return;

    await _run(_Running.cancelPending, () async {
      final Map<String, dynamic> result =
          await ref.read(apiClientProvider).postJson(Endpoints.emergencyCancelPending);
      return '${Json.integer(result['cancelled']) ?? 0} ordre(s) annulé(s)';
    });
  }

  Future<void> _closeAll(EmergencyOverview overview, {required bool suspend}) async {
    final bool confirmed = await confirmWithPhrase(
      context,
      title: suspend ? 'Tout fermer et suspendre' : 'Fermer toutes les positions',
      message: suspend
          ? 'Toutes les positions ouvertes seront fermées au prix du marché et '
              'l\'automatisation sera suspendue. Les pertes ou gains en cours '
              'sont réalisés immédiatement. Action irréversible.'
          : 'Toutes les positions ouvertes seront fermées au prix du marché. '
              'Les pertes ou gains en cours sont réalisés immédiatement. '
              'Action irréversible.',
      phrase: overview.closeAllPhrase,
      confirmLabel: suspend ? 'Tout fermer et suspendre' : 'Fermer tout',
    );
    if (!confirmed) return;

    await _run(suspend ? _Running.closeAndSuspend : _Running.closeAll, () async {
      final Map<String, dynamic> result = await ref.read(apiClientProvider).postJson(
        Endpoints.emergencyCloseAll,
        body: <String, dynamic>{
          'confirmation': overview.closeAllPhrase,
          'suspendAutomation': suspend,
        },
      );
      final int closed = Json.integer(result['closed']) ?? 0;
      return suspend
          ? '$closed position(s) fermée(s), automatisation suspendue'
          : '$closed position(s) fermée(s)';
    });
  }

  /// Exécute une action d'urgence en gérant l'état occupé et les erreurs.
  Future<void> _run(_Running action, Future<String> Function() task) async {
    if (_running != _Running.none) return;
    setState(() => _running = action);
    try {
      final String summary = await task();
      if (!mounted) return;
      showToast(context, summary);
      ref.invalidate(emergencyOverviewProvider);
      refreshBridgeData(ref);
    } on ApiException catch (error) {
      if (!mounted) return;
      showToast(context, error.message, error: true);
    } finally {
      if (mounted) setState(() => _running = _Running.none);
    }
  }

  @override
  Widget build(BuildContext context) {
    final AsyncValue<EmergencyOverview> overview = ref.watch(emergencyOverviewProvider);

    return Scaffold(
      appBar: AppBar(title: const Text('Urgence')),
      body: overview.when(
        loading: () => const LoadingView(label: 'Lecture de la situation en cours…'),
        error: (Object error, StackTrace _) => BridgeErrorView(
          error: error,
          onRetry: () => ref.invalidate(emergencyOverviewProvider),
        ),
        data: (EmergencyOverview data) => _EmergencyBody(
          overview: data,
          running: _running,
          onCancelPending: () => _cancelPending(data),
          onCloseAll: () => _closeAll(data, suspend: false),
          onCloseAndSuspend: () => _closeAll(data, suspend: true),
        ),
      ),
    );
  }
}

class _EmergencyBody extends StatelessWidget {
  const _EmergencyBody({
    required this.overview,
    required this.running,
    required this.onCancelPending,
    required this.onCloseAll,
    required this.onCloseAndSuspend,
  });

  final EmergencyOverview overview;
  final _Running running;
  final VoidCallback onCancelPending;
  final VoidCallback onCloseAll;
  final VoidCallback onCloseAndSuspend;

  String _count(int? value, String singular, String plural) {
    if (value == null) return 'Nombre de $plural inconnu';
    if (value == 0) return 'Aucun $singular concerné';
    return '$value $singular${value > 1 ? 's' : ''} concerné${value > 1 ? 's' : ''}';
  }

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    final bool busy = running != _Running.none;

    return ListView(
      padding: AppSpacing.page,
      children: <Widget>[
        _Inventory(overview: overview),
        const SizedBox(height: AppSpacing.xl),
        Text(
          'Trois actions distinctes sont possibles. Aucune n\'est déclenchée '
          'tant que vous ne l\'avez pas confirmée.',
          style: theme.textTheme.bodySmall,
        ),
        const SizedBox(height: AppSpacing.lg),

        EmergencyActionCard(
          title: '1. Annuler tous les ordres en attente',
          description: 'Retire du carnet les ordres qui n\'ont pas encore été '
              'déclenchés. Les positions déjà ouvertes restent ouvertes.',
          scope: _count(overview.orderCount, 'ordre en attente', 'ordres en attente'),
          buttonLabel: 'ANNULER LES ORDRES EN ATTENTE',
          icon: Icons.playlist_remove,
          busy: running == _Running.cancelPending,
          onPressed: busy || overview.orderCount == 0 ? null : onCancelPending,
        ),

        const SizedBox(height: AppSpacing.xxl),
        const Divider(),
        const SizedBox(height: AppSpacing.lg),
        Text(
          'Actions irréversibles',
          style: theme.textTheme.titleMedium?.copyWith(color: AppColors.loss),
        ),
        const SizedBox(height: AppSpacing.xs),
        Text(
          'Fermer une position réalise immédiatement la perte ou le gain en '
          'cours. Ces deux actions demandent la saisie exacte de la phrase '
          '« ${overview.closeAllPhrase} ».',
          style: theme.textTheme.bodySmall,
        ),
        const SizedBox(height: AppSpacing.lg),

        EmergencyActionCard(
          title: '2. Fermer toutes les positions',
          description: 'Ferme au prix du marché toutes les positions ouvertes. '
              'L\'automatisation reste active : de nouveaux signaux pourront '
              'encore être exécutés.',
          scope: _count(overview.positionCount, 'position ouverte', 'positions ouvertes'),
          buttonLabel: 'FERMER TOUTES LES POSITIONS',
          icon: Icons.close,
          destructive: true,
          busy: running == _Running.closeAll,
          onPressed: busy || overview.positionCount == 0 ? null : onCloseAll,
        ),

        const SizedBox(height: AppSpacing.xxl),

        EmergencyActionCard(
          title: '3. Tout fermer et suspendre l\'automatisation',
          description: 'Ferme toutes les positions puis met le trading '
              'automatique en pause. Plus aucun nouveau trade ne sera ouvert '
              'tant que vous n\'aurez pas repris manuellement.',
          scope: _count(overview.positionCount, 'position ouverte', 'positions ouvertes'),
          footnote: 'À utiliser lorsque quelque chose semble anormal et que '
              'vous voulez tout arrêter.',
          buttonLabel: 'TOUT FERMER ET SUSPENDRE',
          icon: Icons.block,
          destructive: true,
          busy: running == _Running.closeAndSuspend,
          onPressed: busy ? null : onCloseAndSuspend,
        ),

        const SizedBox(height: AppSpacing.xxl),
      ],
    );
  }
}

/// Rappelle ce qui est réellement ouvert avant toute action.
class _Inventory extends StatelessWidget {
  const _Inventory({required this.overview});

  final EmergencyOverview overview;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Row(
            children: <Widget>[
              Expanded(
                child: Text('Situation actuelle', style: theme.textTheme.titleMedium),
              ),
              if (overview.executionMode != null)
                StatusChip(
                  label: BridgeLabels.executionMode(overview.executionMode),
                  tone: overview.executionMode == 'MT5_LIVE'
                      ? StatusTone.bad
                      : StatusTone.neutral,
                  dense: true,
                ),
            ],
          ),
          const SizedBox(height: AppSpacing.sm),
          DetailRow(
            label: 'Positions ouvertes',
            value: overview.positionCount?.toString() ?? '--',
          ),
          DetailRow(
            label: 'Ordres en attente',
            value: overview.orderCount?.toString() ?? '--',
          ),
          if (overview.countsError != null) ...<Widget>[
            const SizedBox(height: AppSpacing.sm),
            Text(
              'Inventaire indisponible : ${overview.countsError}',
              style: theme.textTheme.bodySmall?.copyWith(color: AppColors.warning),
            ),
          ],
        ],
      ),
    );
  }
}
