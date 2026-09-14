import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_exception.dart';
import '../../../core/api/endpoints.dart';
import '../../../core/connection/connection_controller.dart';
import '../../../core/theme/app_colors.dart';
import '../../../core/theme/app_theme.dart';
import '../../../core/widgets/app_widgets.dart';
import '../../bridge/models/bridge_json.dart';
import '../../bridge/models/bridge_labels.dart';
import '../../bridge/widgets/bridge_error_view.dart';
import '../providers/onboarding_providers.dart';
import 'onboarding_step.dart';

/// Étape 5 : clé OpenRouter et vérification du modèle gratuit actif.
class OpenRouterStep extends ConsumerStatefulWidget {
  const OpenRouterStep({super.key, required this.payload});

  final Map<String, dynamic> payload;

  @override
  ConsumerState<OpenRouterStep> createState() => _OpenRouterStepState();
}

class _OpenRouterStepState extends ConsumerState<OpenRouterStep> {
  final TextEditingController _key = TextEditingController();

  bool _saving = false;
  bool _testing = false;
  String? _testMessage;
  bool _testOk = false;

  @override
  void dispose() {
    _key.dispose();
    super.dispose();
  }

  Future<void> _saveKey() async {
    if (_saving || _key.text.trim().isEmpty) return;
    FocusScope.of(context).unfocus();
    setState(() => _saving = true);
    try {
      await ref.read(apiClientProvider).putJson(
        Endpoints.openrouterKey,
        body: <String, dynamic>{'apiKey': _key.text.trim()},
      );
      if (!mounted) return;
      // La clé n'est jamais conservée dans l'application : le champ est vidé
      // dès qu'elle est enregistrée sur le Bridge.
      _key.clear();
      showToast(context, 'Clé enregistrée sur le Bridge.');
      ref.invalidate(openrouterStatusProvider);
      ref.invalidate(onboardingStateProvider);
    } on ApiException catch (error) {
      if (!mounted) return;
      showToast(context, error.message, error: true);
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  Future<void> _test() async {
    if (_testing) return;
    setState(() {
      _testing = true;
      _testMessage = null;
    });
    try {
      final Map<String, dynamic> result =
          await ref.read(apiClientProvider).postJson(Endpoints.openrouterTest);
      if (!mounted) return;
      final bool ok = Json.flag(result['ok']);
      final int? latency = Json.integer(result['latencyMs']);
      setState(() {
        _testOk = ok;
        _testMessage = ok
            ? 'Modèle ${Json.text(result['model']) ?? 'inconnu'} joignable'
                '${latency == null ? '' : ' en $latency ms'}.'
            : Json.text(result['error']) ?? 'Le test a échoué.';
      });
      ref.invalidate(openrouterStatusProvider);
      ref.invalidate(onboardingStateProvider);
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() {
        _testOk = false;
        _testMessage = error.message;
      });
    } finally {
      if (mounted) setState(() => _testing = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final AsyncValue<Map<String, dynamic>> status = ref.watch(openrouterStatusProvider);
    final Map<String, dynamic> step = OnboardingStep.stepByKey(widget.payload, 'openrouter');

    return OnboardingStep(
      title: 'Configuration OpenRouter',
      intro: 'OpenRouter permet à TradePilot d\'interpréter les signaux écrits '
          'en langage libre. Seuls des modèles gratuits sont utilisés.',
      done: Json.flag(step['done']),
      children: <Widget>[
        const _KeyHelpCard(),
        const SizedBox(height: AppSpacing.lg),
        _keyForm(),
        const SizedBox(height: AppSpacing.lg),
        status.when(
          loading: () => const AppCard(child: LoadingView(label: 'Lecture de l\'état…')),
          error: (Object error, StackTrace _) => BridgeErrorView(
            error: error,
            onRetry: () => ref.invalidate(openrouterStatusProvider),
          ),
          data: _statusCard,
        ),
      ],
    );
  }

  Widget _keyForm() {
    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          TextField(
            controller: _key,
            enabled: !_saving,
            obscureText: true,
            autocorrect: false,
            enableSuggestions: false,
            decoration: const InputDecoration(
              labelText: 'Clé OpenRouter',
              hintText: 'sk-or-…',
              prefixIcon: Icon(Icons.vpn_key_outlined),
            ),
          ),
          const SizedBox(height: AppSpacing.lg),
          SizedBox(
            width: double.infinity,
            child: FilledButton(
              onPressed: _saving ? null : _saveKey,
              child: Text(_saving ? 'Enregistrement…' : 'Enregistrer la clé'),
            ),
          ),
        ],
      ),
    );
  }

  Widget _statusCard(Map<String, dynamic> status) {
    final ThemeData theme = Theme.of(context);
    final bool configured = Json.flag(status['configured']);
    final String? state = Json.text(status['state']);

    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Row(
            children: <Widget>[
              Expanded(child: Text('État actuel', style: theme.textTheme.titleMedium)),
              StatusChip(
                label: BridgeLabels.connection(state),
                tone: BridgeLabels.connectionTone(state),
                dense: true,
              ),
            ],
          ),
          const SizedBox(height: AppSpacing.sm),
          DetailRow(
            label: 'Clé enregistrée',
            value: configured ? (Json.text(status['apiKeyHint']) ?? 'Oui') : 'Aucune',
            monospace: configured,
          ),
          DetailRow(label: 'Modèle texte actif', value: Json.text(status['textModel']) ?? '--'),
          DetailRow(label: 'Modèle vision actif', value: Json.text(status['visionModel']) ?? '--'),
          DetailRow(
            label: 'Sélection des modèles',
            value: Json.flag(status['autoMode']) ? 'Automatique' : 'Manuelle',
          ),
          const SizedBox(height: AppSpacing.lg),
          SizedBox(
            width: double.infinity,
            child: OutlinedButton.icon(
              onPressed: !configured || _testing ? null : _test,
              icon: _testing
                  ? const SizedBox(
                      width: 16,
                      height: 16,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  : const Icon(Icons.play_circle_outline, size: 18),
              label: Text(_testing ? 'Test en cours…' : 'Tester la connexion'),
            ),
          ),
          if (_testMessage != null) ...<Widget>[
            const SizedBox(height: AppSpacing.md),
            Text(
              _testMessage!,
              style: theme.textTheme.bodySmall?.copyWith(
                color: _testOk ? AppColors.profit : AppColors.loss,
              ),
            ),
          ],
        ],
      ),
    );
  }
}

/// Explique où obtenir une clé et rappelle la politique des modèles gratuits.
class _KeyHelpCard extends StatelessWidget {
  const _KeyHelpCard();

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Text('Obtenir une clé', style: theme.textTheme.titleMedium),
          const SizedBox(height: AppSpacing.md),
          const OnboardingBullet(
            icon: Icons.looks_one_outlined,
            text: 'Créez un compte sur https://openrouter.ai puis ouvrez la page « Keys ».',
          ),
          const OnboardingBullet(
            icon: Icons.looks_two_outlined,
            text: 'Générez une clé et recopiez-la ci-dessous.',
          ),
          const OnboardingBullet(
            icon: Icons.money_off,
            text: 'TradePilot n\'utilise que des modèles gratuits : aucune '
                'consommation payante n\'est déclenchée.',
          ),
          Text(
            'La clé est chiffrée sur le Bridge et n\'est jamais renvoyée en '
            'clair à l\'application.',
            style: theme.textTheme.bodySmall,
          ),
        ],
      ),
    );
  }
}
