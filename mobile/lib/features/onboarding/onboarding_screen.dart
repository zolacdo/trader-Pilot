import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/api/api_exception.dart';
import '../../core/api/endpoints.dart';
import '../../core/connection/connection_controller.dart';
import '../../core/providers/bridge_data.dart';
import '../../core/routing/app_router.dart';
import '../../core/theme/app_colors.dart';
import '../../core/theme/app_theme.dart';
import '../../core/widgets/app_widgets.dart';
import '../bridge/widgets/bridge_error_view.dart';
import 'providers/onboarding_providers.dart';
import 'widgets/final_step.dart';
import 'widgets/openrouter_step.dart';
import 'widgets/risk_and_mode_steps.dart';
import 'widgets/setup_steps.dart';
import 'widgets/telegram_step.dart';

/// Configuration guidée en huit étapes (CDC section 7).
///
/// L'onboarding ne fabrique aucun état : chaque étape lit ce que le Bridge
/// rapporte réellement via `GET /onboarding/state`.
class OnboardingScreen extends ConsumerStatefulWidget {
  const OnboardingScreen({super.key});

  @override
  ConsumerState<OnboardingScreen> createState() => _OnboardingScreenState();
}

class _OnboardingScreenState extends ConsumerState<OnboardingScreen> {
  static const List<String> _labels = <String>[
    'Présentation',
    'Configuration du Bridge',
    'Vérification de MetaTrader 5',
    'Connexion Telegram',
    'Configuration OpenRouter',
    'Configuration du risque',
    'Choix du mode',
    'Test général',
  ];

  final PageController _pages = PageController();
  int _index = 0;
  bool _finishing = false;

  @override
  void dispose() {
    _pages.dispose();
    super.dispose();
  }

  void _goTo(int index) {
    if (index < 0 || index >= _labels.length) return;
    _pages.animateToPage(
      index,
      duration: const Duration(milliseconds: 240),
      curve: Curves.easeOut,
    );
  }

  Future<void> _finish() async {
    if (_finishing) return;
    setState(() => _finishing = true);
    try {
      await ref.read(apiClientProvider).postJson(Endpoints.onboardingComplete);
      if (!mounted) return;
      refreshBridgeData(ref);
      context.go(Routes.dashboard);
    } on ApiException catch (error) {
      if (!mounted) return;
      showToast(context, error.message, error: true);
      setState(() => _finishing = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final AsyncValue<Map<String, dynamic>> state = ref.watch(onboardingStateProvider);

    return Scaffold(
      appBar: AppBar(
        title: const Text('Configuration guidée'),
        actions: <Widget>[
          IconButton(
            tooltip: 'Actualiser',
            onPressed: () => ref.invalidate(onboardingStateProvider),
            icon: const Icon(Icons.refresh),
          ),
        ],
      ),
      body: state.when(
        loading: () => const LoadingView(label: 'Lecture de la configuration…'),
        error: (Object error, StackTrace _) => BridgeErrorView(
          error: error,
          onRetry: () => ref.invalidate(onboardingStateProvider),
        ),
        data: (Map<String, dynamic> payload) => Column(
          children: <Widget>[
            _StepProgress(index: _index, total: _labels.length, label: _labels[_index]),
            Expanded(
              child: PageView(
                controller: _pages,
                onPageChanged: (int index) => setState(() => _index = index),
                children: <Widget>[
                  const IntroStep(),
                  BridgeStep(payload: payload),
                  MetaTraderStep(payload: payload),
                  TelegramStep(payload: payload),
                  OpenRouterStep(payload: payload),
                  RiskStep(payload: payload),
                  ModeStep(payload: payload),
                  FinalStep(payload: payload),
                ],
              ),
            ),
            _StepNavigation(
              index: _index,
              total: _labels.length,
              finishing: _finishing,
              onPrevious: () => _goTo(_index - 1),
              onNext: () => _goTo(_index + 1),
              onFinish: _finish,
            ),
          ],
        ),
      ),
    );
  }
}

/// Avancement : barre fine et libellé de l'étape en cours.
class _StepProgress extends StatelessWidget {
  const _StepProgress({required this.index, required this.total, required this.label});

  final int index;
  final int total;
  final String label;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.fromLTRB(AppSpacing.lg, 0, AppSpacing.lg, AppSpacing.sm),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          ClipRRect(
            borderRadius: BorderRadius.circular(4),
            child: LinearProgressIndicator(
              value: (index + 1) / total,
              minHeight: 4,
              backgroundColor: theme.colorScheme.outline,
            ),
          ),
          const SizedBox(height: AppSpacing.sm),
          Text('Étape ${index + 1} sur $total · $label', style: theme.textTheme.labelSmall),
        ],
      ),
    );
  }
}

/// Barre de navigation entre les étapes.
class _StepNavigation extends StatelessWidget {
  const _StepNavigation({
    required this.index,
    required this.total,
    required this.finishing,
    required this.onPrevious,
    required this.onNext,
    required this.onFinish,
  });

  final int index;
  final int total;
  final bool finishing;
  final VoidCallback onPrevious;
  final VoidCallback onNext;
  final VoidCallback onFinish;

  @override
  Widget build(BuildContext context) {
    final bool last = index == total - 1;
    return SafeArea(
      top: false,
      child: Container(
        padding: const EdgeInsets.all(AppSpacing.lg),
        decoration: BoxDecoration(
          border: Border(top: BorderSide(color: Theme.of(context).colorScheme.outline)),
          color: Theme.of(context).cardTheme.color,
        ),
        child: Row(
          children: <Widget>[
            if (index > 0)
              OutlinedButton(
                onPressed: finishing ? null : onPrevious,
                child: const Text('Précédent'),
              ),
            const Spacer(),
            if (last)
              FilledButton.icon(
                onPressed: finishing ? null : onFinish,
                icon: finishing
                    ? const SizedBox(
                        width: 16,
                        height: 16,
                        child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white),
                      )
                    : const Icon(Icons.check, size: 18),
                label: Text(finishing ? 'Finalisation…' : 'Terminer'),
              )
            else
              FilledButton.icon(
                onPressed: onNext,
                style: FilledButton.styleFrom(backgroundColor: AppColors.primary),
                icon: const Icon(Icons.arrow_forward, size: 18),
                label: const Text('Suivant'),
              ),
          ],
        ),
      ),
    );
  }
}
