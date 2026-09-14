import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_exception.dart';
import '../../../core/api/endpoints.dart';
import '../../../core/connection/connection_controller.dart';
import '../../../core/theme/app_theme.dart';
import '../../../core/widgets/app_widgets.dart';
import '../../bridge/models/bridge_json.dart';
import '../../bridge/models/bridge_labels.dart';
import '../providers/onboarding_providers.dart';
import 'onboarding_step.dart';

/// Résultat d'un test de connexion lancé depuis l'onboarding.
class _TestResult {
  const _TestResult({required this.ok, this.detail});

  final bool ok;
  final String? detail;
}

/// Étape 8 : test général des connexions puis récapitulatif final (CDC §7).
class FinalStep extends ConsumerStatefulWidget {
  const FinalStep({super.key, required this.payload});

  final Map<String, dynamic> payload;

  @override
  ConsumerState<FinalStep> createState() => _FinalStepState();
}

class _FinalStepState extends ConsumerState<FinalStep> {
  static const List<({String target, String label, IconData icon})> _tests =
      <({String target, String label, IconData icon})>[
    (target: 'telegram', label: 'Telegram', icon: Icons.send_outlined),
    (target: 'mt5', label: 'MetaTrader 5', icon: Icons.candlestick_chart_outlined),
    (target: 'openrouter', label: 'OpenRouter', icon: Icons.auto_awesome_outlined),
    (target: 'websocket', label: 'Temps réel', icon: Icons.bolt_outlined),
  ];

  final Map<String, _TestResult> _results = <String, _TestResult>{};
  String? _running;

  Future<void> _runTest(String target) async {
    if (_running != null) return;
    setState(() => _running = target);
    try {
      final Map<String, dynamic> result =
          await ref.read(apiClientProvider).postJson(Endpoints.diagnosticTest(target));
      if (!mounted) return;
      setState(() {
        _results[target] = _TestResult(
          ok: Json.flag(result['ok']),
          detail: Json.text(result['detail']),
        );
      });
      ref.invalidate(onboardingStateProvider);
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() => _results[target] = _TestResult(ok: false, detail: error.message));
    } finally {
      if (mounted) setState(() => _running = null);
    }
  }

  Future<void> _runAll() async {
    for (final ({String target, String label, IconData icon}) test in _tests) {
      if (!mounted) return;
      await _runTest(test.target);
    }
  }

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    final Map<String, dynamic> summary = Json.map(widget.payload['summary']);

    return OnboardingStep(
      title: 'Test général et récapitulatif',
      intro: 'Vérifiez que chaque liaison répond, puis relisez l\'état final '
          'avant de terminer la configuration.',
      done: Json.flag(OnboardingStep.stepByKey(widget.payload, 'tests')['done']),
      children: <Widget>[
        AppCard(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: <Widget>[
              Text('Tests de connexion', style: theme.textTheme.titleMedium),
              const SizedBox(height: AppSpacing.xs),
              Text(
                'Aucun de ces tests n\'envoie d\'ordre : ils vérifient '
                'uniquement que chaque service répond.',
                style: theme.textTheme.bodySmall,
              ),
              const SizedBox(height: AppSpacing.md),
              for (final ({String target, String label, IconData icon}) test in _tests)
                _TestRow(
                  label: test.label,
                  icon: test.icon,
                  running: _running == test.target,
                  result: _results[test.target],
                  onRun: _running == null ? () => _runTest(test.target) : null,
                ),
              const SizedBox(height: AppSpacing.md),
              SizedBox(
                width: double.infinity,
                child: OutlinedButton.icon(
                  onPressed: _running == null ? _runAll : null,
                  icon: const Icon(Icons.playlist_play, size: 18),
                  label: const Text('Tout tester'),
                ),
              ),
            ],
          ),
        ),
        const SizedBox(height: AppSpacing.xl),
        _SummaryCard(summary: summary),
        const SizedBox(height: AppSpacing.lg),
        Text(
          'Après « Terminer », l\'accueil affiche en permanence le mode '
          'd\'exécution, l\'état des liaisons et les commandes de pause et '
          'd\'urgence.',
          style: theme.textTheme.bodySmall,
        ),
      ],
    );
  }
}

/// Une ligne de test : nom, bouton, résultat réel renvoyé par le Bridge.
class _TestRow extends StatelessWidget {
  const _TestRow({
    required this.label,
    required this.icon,
    required this.running,
    required this.result,
    required this.onRun,
  });

  final String label;
  final IconData icon;
  final bool running;
  final _TestResult? result;
  final VoidCallback? onRun;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: AppSpacing.sm),
      child: Row(
        children: <Widget>[
          Icon(icon, size: 18),
          const SizedBox(width: AppSpacing.md),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: <Widget>[
                Text(label, style: theme.textTheme.bodyMedium),
                if (result?.detail != null) ...<Widget>[
                  const SizedBox(height: 2),
                  Text(result!.detail!, style: theme.textTheme.bodySmall),
                ],
              ],
            ),
          ),
          if (running)
            const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2))
          else if (result != null)
            StatusChip(
              label: result!.ok ? 'OK' : 'Échec',
              tone: result!.ok ? StatusTone.good : StatusTone.bad,
              dense: true,
            )
          else
            TextButton(onPressed: onRun, child: const Text('Tester')),
        ],
      ),
    );
  }
}

/// Récapitulatif final, exactement les six lignes attendues par le CDC §7.
class _SummaryCard extends StatelessWidget {
  const _SummaryCard({required this.summary});

  final Map<String, dynamic> summary;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    final bool autoTrading = Json.flag(summary['autoTrading']);
    final String? accountKind = Json.text(summary['account']);

    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Text('Récapitulatif', style: theme.textTheme.titleMedium),
          const SizedBox(height: AppSpacing.md),
          _SummaryLine(
            label: 'Telegram',
            connected: BridgeLabels.isConnected(Json.text(summary['telegram'])),
          ),
          _SummaryLine(
            label: 'OpenRouter',
            connected: BridgeLabels.isConnected(Json.text(summary['openrouter'])),
          ),
          _SummaryLine(
            label: 'Bridge',
            connected: BridgeLabels.isConnected(Json.text(summary['bridge'])),
          ),
          _SummaryLine(
            label: 'MT5',
            connected: BridgeLabels.isConnected(Json.text(summary['mt5'])),
          ),
          _SummaryLine(
            label: 'Compte',
            connected: accountKind == 'DEMO',
            valueLabel: BridgeLabels.accountKind(accountKind),
            tone: BridgeLabels.accountTone(accountKind),
          ),
          _SummaryLine(
            label: 'Auto trading',
            connected: autoTrading,
            valueLabel: autoTrading ? 'Actif' : 'Inactif',
            tone: autoTrading ? StatusTone.good : StatusTone.neutral,
          ),
          const Divider(height: AppSpacing.xl),
          DetailRow(
            label: 'Mode d\'exécution',
            value: BridgeLabels.executionMode(Json.text(summary['executionMode'])),
          ),
        ],
      ),
    );
  }
}

class _SummaryLine extends StatelessWidget {
  const _SummaryLine({
    required this.label,
    required this.connected,
    this.valueLabel,
    this.tone,
  });

  final String label;
  final bool connected;
  final String? valueLabel;
  final StatusTone? tone;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 5),
      child: Row(
        children: <Widget>[
          Expanded(child: Text(label, style: theme.textTheme.bodyMedium)),
          if (valueLabel == null)
            StatusChip.connection(
              connected: connected,
              labelOverride: connected ? 'Connecté' : 'Non connecté',
            )
          else
            StatusChip(
              label: valueLabel!,
              tone: tone ?? (connected ? StatusTone.good : StatusTone.bad),
              dense: true,
            ),
        ],
      ),
    );
  }
}
