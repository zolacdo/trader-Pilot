import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_exception.dart';
import '../../../core/theme/app_colors.dart';
import '../../../core/theme/app_theme.dart';
import '../../../core/widgets/app_widgets.dart';
import '../ai_config_providers.dart';
import '../models/ai_settings.dart';
import '../models/ai_status.dart';
import 'ai_diagnostic_sections.dart';
import 'ai_shell.dart';
import 'ai_test_result_tile.dart';

/// OpenRouter : modèles gratuits uniquement, aucune clé affichée ici.
class AiOpenRouterSection extends ConsumerWidget {
  const AiOpenRouterSection({super.key, required this.settings});

  final AiSettings settings;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final AsyncValue<AiOpenRouterModels> models = ref.watch(aiOpenRouterModelsProvider);
    final AiTestState test =
        ref.watch(aiTestProvider)[AiTestController.openRouter] ?? const AiTestState();

    return AiSection(
      title: 'OpenRouter',
      subtitle: 'Moteur distant, limité aux modèles gratuits.',
      action: const AiHealthBadge(),
      children: <Widget>[
        AiSwitchField(
          label: 'Utiliser OpenRouter',
          description: 'Le Bridge peut interroger le modèle gratuit sélectionné.',
          value: settings.openRouterEnabled,
          onChanged: (bool value) => ref
              .read(aiConfigProvider.notifier)
              .edit((AiSettings current) => current.copyWith(openRouterEnabled: value)),
        ),
        models.when(
          loading: () => const SizedBox(height: 88, child: LoadingView()),
          error: (Object error, StackTrace stack) => ErrorView(
            message: error is ApiException ? error.message : 'État OpenRouter indisponible.',
            technical: error is ApiException ? error.technical : error.toString(),
            onRetry: () => ref.invalidate(aiOpenRouterModelsProvider),
          ),
          data: (AiOpenRouterModels data) => _OpenRouterDetails(models: data),
        ),
        const AiNote(
          text: 'La clé OpenRouter se saisit dans les Paramètres. Elle n’est jamais '
              'affichée ici, ni envoyée à un autre service.',
        ),
        const SizedBox(height: AppSpacing.sm),
        Align(
          alignment: Alignment.centerLeft,
          child: FilledButton.icon(
            onPressed: test.running
                ? null
                : () => ref.read(aiTestProvider.notifier).run(AiTestController.openRouter),
            icon: const Icon(Icons.network_check, size: 18),
            label: Text(test.running ? 'Test en cours…' : 'Tester OpenRouter'),
          ),
        ),
        AiTestResultTile(state: test),
      ],
    );
  }
}

class _OpenRouterDetails extends StatelessWidget {
  const _OpenRouterDetails({required this.models});

  final AiOpenRouterModels models;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        DetailRow(label: 'Modèle texte actif', value: models.textModel ?? '--'),
        DetailRow(label: 'Modèle vision actif', value: models.visionModel ?? '--'),
        DetailRow(
          label: 'Sélection automatique des modèles gratuits',
          value: models.autoMode ? 'Activée' : 'Désactivée',
        ),
        DetailRow(
          label: 'Modèles gratuits détectés',
          value: '${models.freeModels.length}',
        ),
        if (models.freeModels.isNotEmpty) ...<Widget>[
          const SizedBox(height: AppSpacing.sm),
          // Les identifiants OpenRouter sont longs : une ligne par modèle,
          // tronquée proprement, plutôt qu'une pastille qui déborde.
          for (final AiFreeModel model in models.freeModels.take(6))
            Padding(
              padding: const EdgeInsets.only(bottom: 4),
              child: Row(
                children: <Widget>[
                  Icon(
                    model.id == models.textModel
                        ? Icons.radio_button_checked
                        : Icons.radio_button_unchecked,
                    size: 16,
                    color: model.id == models.textModel
                        ? AppColors.primary
                        : AppColors.textTertiary,
                  ),
                  const SizedBox(width: AppSpacing.sm),
                  Expanded(
                    child: Text(
                      model.id,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: Theme.of(context).textTheme.bodySmall,
                    ),
                  ),
                  if (model.vision)
                    Text('vision', style: Theme.of(context).textTheme.labelSmall),
                ],
              ),
            ),
        ],
      ],
    );
  }
}
