import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/endpoints.dart';
import '../../../core/connection/connection_controller.dart';
import '../../../core/theme/app_theme.dart';
import '../../../core/widgets/app_widgets.dart';
import '../../bridge/models/bridge_action.dart';
import '../../bridge/models/bridge_json.dart';
import '../../bridge/models/bridge_labels.dart';
import '../providers/onboarding_providers.dart';
import 'onboarding_step.dart';

/// Étape 1 : ce que fait TradePilot, et ce qu'il ne fait pas.
class IntroStep extends StatelessWidget {
  const IntroStep({super.key});

  @override
  Widget build(BuildContext context) {
    return const OnboardingStep(
      title: 'Bienvenue dans TradePilot',
      intro: 'Cette configuration guidée prépare la copie de signaux de '
          'trading. Elle prend quelques minutes et peut être reprise plus tard.',
      children: <Widget>[
        OnboardingBullet(
          icon: Icons.podcasts_outlined,
          text: 'TradePilot lit les canaux Telegram que vous choisissez et '
              'interprète les signaux qui s\'y trouvent.',
        ),
        OnboardingBullet(
          icon: Icons.shield_outlined,
          text: 'Chaque signal passe par un moteur de risque avant toute '
              'exécution : taille de position, limites journalières, horaires.',
        ),
        OnboardingBullet(
          icon: Icons.science_outlined,
          text: 'Au départ, tout fonctionne en mode PAPER : les ordres sont '
              'simulés et aucun argent n\'est engagé.',
        ),
        OnboardingBullet(
          icon: Icons.computer_outlined,
          text: 'Le Bridge, installé sur votre ordinateur, fait le lien avec '
              'MetaTrader 5. Le téléphone ne fait que piloter et afficher.',
        ),
        SizedBox(height: AppSpacing.md),
        OnboardingWarning(
          title: 'Le trading comporte un risque de perte',
          message: 'Aucun réglage, aucune analyse et aucune automatisation ne '
              'rend le trading sans risque. Restez en mode PAPER puis en compte '
              'démo aussi longtemps que nécessaire.',
        ),
      ],
    );
  }
}

/// Étape 2 : état du Bridge et adresse publique éventuelle.
class BridgeStep extends ConsumerWidget {
  const BridgeStep({super.key, required this.payload});

  final Map<String, dynamic> payload;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final BridgeConnectionState connection = ref.watch(connectionProvider);
    final Map<String, dynamic> step = OnboardingStep.stepByKey(payload, 'bridge');
    final Map<String, dynamic> summary = Json.map(payload['summary']);
    final String? detail = Json.text(step['detail']);
    final bool hasPublicUrl = detail != null && detail.startsWith('http');

    return OnboardingStep(
      title: 'Configuration du Bridge',
      intro: 'Le Bridge est le programme installé sur votre ordinateur. Il '
          'parle à MetaTrader 5 et à Telegram ; ce téléphone s\'y connecte.',
      done: Json.flag(step['done']),
      children: <Widget>[
        AppCard(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: <Widget>[
              Row(
                children: <Widget>[
                  Expanded(
                    child: Text('Liaison actuelle', style: Theme.of(context).textTheme.titleMedium),
                  ),
                  StatusChip.connection(
                    connected: connection.online,
                    labelOverride: connection.online
                        ? BridgeLabels.connection(Json.text(summary['bridge']))
                        : 'Injoignable',
                  ),
                ],
              ),
              const SizedBox(height: AppSpacing.sm),
              DetailRow(label: 'Adresse utilisée', value: connection.baseUrl ?? '--'),
              DetailRow(
                label: 'Adresse publique',
                value: hasPublicUrl ? detail : 'Aucune (réseau local uniquement)',
              ),
              if (connection.fallbackUrl != null)
                DetailRow(label: 'Adresse de repli', value: connection.fallbackUrl!),
            ],
          ),
        ),
        const SizedBox(height: AppSpacing.lg),
        const OnboardingBullet(
          icon: Icons.wifi,
          text: 'Sans adresse publique, le téléphone doit rester sur le même '
              'réseau Wi-Fi que l\'ordinateur.',
        ),
        const OnboardingBullet(
          icon: Icons.public,
          text: 'Avec une adresse publique (ngrok), l\'application reste '
              'joignable depuis l\'extérieur du domicile.',
        ),
        const OnboardingBullet(
          icon: Icons.settings_outlined,
          text: 'L\'adresse se change à tout moment depuis Plus → Connexions.',
        ),
      ],
    );
  }
}

/// Étape 3 : vérification du terminal MetaTrader 5.
class MetaTraderStep extends ConsumerStatefulWidget {
  const MetaTraderStep({super.key, required this.payload});

  final Map<String, dynamic> payload;

  @override
  ConsumerState<MetaTraderStep> createState() => _MetaTraderStepState();
}

class _MetaTraderStepState extends ConsumerState<MetaTraderStep> {
  bool _busy = false;

  Future<void> _reconnect() async {
    if (_busy) return;
    setState(() => _busy = true);
    await runBridgeAction(
      context,
      action: () => ref.read(apiClientProvider).postJson(Endpoints.mt5Reconnect),
      successMessage: 'Reconnexion MetaTrader 5 demandée.',
    );
    if (!mounted) return;
    setState(() => _busy = false);
    ref.invalidate(onboardingStateProvider);
  }

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    final Map<String, dynamic> step = OnboardingStep.stepByKey(widget.payload, 'metatrader');
    final Map<String, dynamic> summary = Json.map(widget.payload['summary']);
    final String? state = Json.text(summary['mt5']);
    final bool connected = BridgeLabels.isConnected(state);
    final String? detail = Json.text(step['detail']);

    return OnboardingStep(
      title: 'Vérification de MetaTrader 5',
      intro: 'MetaTrader 5 doit tourner sur le même ordinateur que le Bridge, '
          'connecté à un compte de démonstration.',
      done: Json.flag(step['done']),
      children: <Widget>[
        AppCard(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: <Widget>[
              Row(
                children: <Widget>[
                  Expanded(child: Text('Terminal', style: theme.textTheme.titleMedium)),
                  StatusChip.connection(
                    connected: connected,
                    labelOverride: BridgeLabels.connection(state),
                  ),
                ],
              ),
              const SizedBox(height: AppSpacing.sm),
              DetailRow(
                label: 'Type de compte',
                value: BridgeLabels.accountKind(Json.text(summary['account'])),
              ),
              if (detail != null && detail.isNotEmpty)
                DetailRow(label: 'Détail', value: detail),
              const SizedBox(height: AppSpacing.lg),
              SizedBox(
                width: double.infinity,
                child: OutlinedButton.icon(
                  onPressed: _busy ? null : _reconnect,
                  icon: _busy
                      ? const SizedBox(
                          width: 16,
                          height: 16,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                      : const Icon(Icons.refresh, size: 18),
                  label: Text(_busy ? 'Tentative en cours…' : 'Reconnecter MetaTrader 5'),
                ),
              ),
            ],
          ),
        ),
        const SizedBox(height: AppSpacing.lg),
        if (!connected)
          const OnboardingWarning(
            title: 'MetaTrader 5 n\'est pas connecté',
            message: 'Sans terminal connecté, TradePilot ne peut pas envoyer '
                'd\'ordre. Le mode PAPER reste utilisable, mais avec des prix '
                'simulés et non des prix de marché.',
          )
        else
          const OnboardingBullet(
            icon: Icons.check_circle_outline,
            text: 'Le terminal répond : les prix et le compte sont lus '
                'directement depuis MetaTrader 5.',
          ),
      ],
    );
  }
}
