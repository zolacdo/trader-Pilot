import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/endpoints.dart';
import '../../../core/connection/connection_controller.dart';
import '../../../core/providers/bridge_data.dart';
import '../../../core/theme/app_theme.dart';
import '../../../core/utils/formatters.dart';
import '../../../core/widgets/app_widgets.dart';
import '../../bridge/models/bridge_action.dart';
import '../../bridge/models/bridge_json.dart';
import '../../bridge/models/bridge_labels.dart';
import '../../bridge/widgets/bridge_error_view.dart';
import '../providers/onboarding_providers.dart';
import 'onboarding_step.dart';

/// Étape 6 : limites de risque actuellement appliquées par le Bridge.
class RiskStep extends ConsumerWidget {
  const RiskStep({super.key, required this.payload});

  final Map<String, dynamic> payload;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final AsyncValue<Map<String, dynamic>> settings = ref.watch(riskSettingsProvider);

    return OnboardingStep(
      title: 'Configuration du risque',
      intro: 'Ces limites s\'appliquent à chaque signal avant toute exécution. '
          'Un signal qui les dépasse est refusé, jamais arrondi.',
      done: Json.flag(OnboardingStep.stepByKey(payload, 'risk')['done']),
      children: <Widget>[
        settings.when(
          loading: () => const AppCard(child: LoadingView(label: 'Lecture des limites…')),
          error: (Object error, StackTrace _) => BridgeErrorView(
            error: error,
            onRetry: () => ref.invalidate(riskSettingsProvider),
          ),
          data: (Map<String, dynamic> risk) => AppCard(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: <Widget>[
                Text('Limites actives', style: Theme.of(context).textTheme.titleMedium),
                const SizedBox(height: AppSpacing.sm),
                DetailRow(
                  label: 'Risque par trade',
                  value: Fmt.percent(Json.number(risk['riskPercent'])),
                ),
                DetailRow(
                  label: 'Perte maximale par jour',
                  value: Fmt.percent(Json.number(risk['maxDailyLossPercent'])),
                ),
                DetailRow(
                  label: 'Risque engagé par jour',
                  value: Fmt.percent(Json.number(risk['maxDailyRiskPercent'])),
                ),
                DetailRow(
                  label: 'Drawdown maximal',
                  value: Fmt.percent(Json.number(risk['maxDrawdownPercent'])),
                ),
                DetailRow(
                  label: 'Positions simultanées',
                  value: Json.integer(risk['maxPositions'])?.toString() ?? '--',
                ),
                DetailRow(
                  label: 'Lot maximal',
                  value: Fmt.lots(Json.number(risk['maxLot'])),
                ),
                DetailRow(
                  label: 'Stop loss obligatoire',
                  value: Json.flag(risk['requireStopLoss']) ? 'Oui' : 'Non',
                ),
              ],
            ),
          ),
        ),
        const SizedBox(height: AppSpacing.lg),
        const OnboardingBullet(
          icon: Icons.tune,
          text: 'Ces valeurs se modifient à tout moment depuis '
              'Plus → Gestion du risque.',
        ),
        const OnboardingBullet(
          icon: Icons.block,
          text: 'Aucune martingale, aucune moyenne à la baisse : un trade '
              'perdant n\'est jamais compensé par une position plus grosse.',
        ),
      ],
    );
  }
}

/// Étape 7 : le mode PAPER est imposé au départ.
class ModeStep extends ConsumerStatefulWidget {
  const ModeStep({super.key, required this.payload});

  final Map<String, dynamic> payload;

  @override
  ConsumerState<ModeStep> createState() => _ModeStepState();
}

class _ModeStepState extends ConsumerState<ModeStep> {
  bool _busy = false;

  Future<void> _backToPaper() async {
    if (_busy) return;
    setState(() => _busy = true);
    await runBridgeAction(
      context,
      action: () => ref.read(apiClientProvider).postJson(
        Endpoints.tradingExecutionMode,
        body: <String, dynamic>{'mode': 'PAPER'},
      ),
      successMessage: 'Mode PAPER rétabli : aucun ordre réel ne sera envoyé.',
    );
    if (!mounted) return;
    setState(() => _busy = false);
    ref.invalidate(onboardingStateProvider);
    refreshBridgeData(ref);
  }

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    final Map<String, dynamic> summary = Json.map(widget.payload['summary']);
    final String? mode = Json.text(summary['executionMode']);
    final bool isPaper = mode == 'PAPER';

    return OnboardingStep(
      title: 'Choix du mode',
      intro: 'TradePilot démarre obligatoirement en mode PAPER. Le passage en '
          'compte démo puis en compte réel se fait plus tard, volontairement.',
      done: Json.flag(OnboardingStep.stepByKey(widget.payload, 'mode')['done']),
      children: <Widget>[
        AppCard(
          accent: isPaper,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: <Widget>[
              Text('MODE ACTUEL', style: theme.textTheme.labelSmall),
              const SizedBox(height: AppSpacing.xs),
              Text(BridgeLabels.executionMode(mode), style: theme.textTheme.headlineSmall),
              const SizedBox(height: AppSpacing.sm),
              Text(BridgeLabels.executionModeDetail(mode), style: theme.textTheme.bodySmall),
              if (!isPaper) ...<Widget>[
                const SizedBox(height: AppSpacing.lg),
                SizedBox(
                  width: double.infinity,
                  child: OutlinedButton.icon(
                    onPressed: _busy ? null : _backToPaper,
                    icon: _busy
                        ? const SizedBox(
                            width: 16,
                            height: 16,
                            child: CircularProgressIndicator(strokeWidth: 2),
                          )
                        : const Icon(Icons.science_outlined, size: 18),
                    label: Text(_busy ? 'Changement…' : 'Revenir en mode PAPER'),
                  ),
                ),
              ],
            ],
          ),
        ),
        const SizedBox(height: AppSpacing.lg),
        Text('Pourquoi PAPER au départ ?', style: theme.textTheme.titleMedium),
        const SizedBox(height: AppSpacing.md),
        const OnboardingBullet(
          icon: Icons.visibility_outlined,
          text: 'Vous voyez comment les signaux de vos canaux sont interprétés '
              'sans risquer un centime.',
        ),
        const OnboardingBullet(
          icon: Icons.rule,
          text: 'Vous vérifiez que les limites de risque produisent des tailles '
              'de position qui vous conviennent.',
        ),
        const OnboardingBullet(
          icon: Icons.query_stats,
          text: 'Vous accumulez assez d\'historique pour juger la qualité réelle '
              'd\'un canal avant de l\'exécuter.',
        ),
        const SizedBox(height: AppSpacing.md),
        const OnboardingWarning(
          title: 'Le mode réel reste verrouillé',
          message: 'Passer en compte réel demande un déverrouillage explicite '
              'et la saisie d\'une phrase de confirmation, depuis un écran dédié. '
              'Rien ne peut basculer en réel par accident.',
        ),
      ],
    );
  }
}
