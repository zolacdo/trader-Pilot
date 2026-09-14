import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/theme/app_theme.dart';
import '../../core/widgets/app_widgets.dart';
import 'ai_config_providers.dart';
import 'ai_routes.dart';
import 'models/ai_settings.dart';
import 'widgets/ai_ensemble_section.dart';
import 'widgets/ai_guardrails_section.dart';
import 'widgets/ai_mode_section.dart';
import 'widgets/ai_openrouter_section.dart';
import 'widgets/ai_shell.dart';

/// Configuration de l'intelligence artificielle (CDC2 section 95).
///
/// Les modifications restent locales tant qu'elles ne sont pas enregistrées :
/// un seul `PUT /ai/router/settings` part, avec les seuls champs changés.
class AiConfigScreen extends ConsumerWidget {
  const AiConfigScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final AiConfigState state = ref.watch(aiConfigProvider);
    final AiSettings? settings = state.draft;

    final Widget body;
    if (settings != null) {
      body = _AiConfigBody(state: state, settings: settings);
    } else if (state.loading) {
      body = const LoadingView(label: 'Lecture des réglages IA…');
    } else {
      body = ErrorView(
        message: state.error ?? 'Réglages IA indisponibles.',
        technical: state.technical,
        onRetry: () => ref.read(aiConfigProvider.notifier).load(),
      );
    }

    return Scaffold(
      appBar: AppBar(
        title: const Text('Intelligence artificielle'),
        actions: <Widget>[
          IconButton(
            tooltip: 'Diagnostic IA',
            onPressed: () => context.push(AiRoutes.diagnostic),
            icon: const Icon(Icons.monitor_heart_outlined),
          ),
        ],
      ),
      body: body,
      bottomNavigationBar: settings == null ? null : _SaveBar(state: state),
    );
  }
}

class _AiConfigBody extends StatelessWidget {
  const _AiConfigBody({required this.state, required this.settings});

  final AiConfigState state;
  final AiSettings settings;

  @override
  Widget build(BuildContext context) {
    return ListView(
      padding: AppSpacing.page,
      physics: const AlwaysScrollableScrollPhysics(),
      children: <Widget>[
        if (state.error != null)
          Padding(
            padding: const EdgeInsets.only(bottom: AppSpacing.lg),
            child: AiNote(text: state.error!, warning: true),
          ),
        AiModeSection(settings: settings),
        AiOpenRouterSection(settings: settings),
        AiEnsembleSection(settings: settings),
        AiGuardrailsSection(settings: settings),
        const SizedBox(height: AppSpacing.xl),
      ],
    );
  }
}

/// Barre d'enregistrement : visible seulement quand quelque chose a changé.
class _SaveBar extends ConsumerWidget {
  const _SaveBar({required this.state});

  final AiConfigState state;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    if (!state.dirty && !state.saving) return const SizedBox.shrink();

    return SafeArea(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(
          AppSpacing.lg,
          AppSpacing.sm,
          AppSpacing.lg,
          AppSpacing.md,
        ),
        child: Row(
          children: <Widget>[
            Expanded(
              child: OutlinedButton(
                onPressed:
                    state.saving ? null : () => ref.read(aiConfigProvider.notifier).reset(),
                child: const Text('Annuler'),
              ),
            ),
            const SizedBox(width: AppSpacing.md),
            Expanded(
              child: FilledButton(
                onPressed: state.saving
                    ? null
                    : () async {
                        final String? error =
                            await ref.read(aiConfigProvider.notifier).save();
                        if (!context.mounted) return;
                        if (error == null) {
                          // Le diagnostic doit refléter les nouveaux réglages.
                          ref.invalidate(aiStatusProvider);
                          showToast(context, 'Réglages IA enregistrés.');
                        } else {
                          showToast(context, error, error: true);
                        }
                      },
                child: Text(state.saving ? 'Enregistrement…' : 'Enregistrer'),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
