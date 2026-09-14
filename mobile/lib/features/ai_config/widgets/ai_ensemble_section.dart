import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../ai_config_providers.dart';
import '../models/ai_settings.dart';
import 'ai_shell.dart';

/// Ensemble : les deux moteurs sont confrontés avant toute décision.
class AiEnsembleSection extends ConsumerWidget {
  const AiEnsembleSection({super.key, required this.settings});

  final AiSettings settings;

  static const List<AiOption<String>> _behaviours = <AiOption<String>>[
    AiOption<String>(
      value: AiDisagreement.noTrade,
      label: 'Aucun trade',
      description: 'En cas de désaccord, la décision est abandonnée. Rien n’est envoyé.',
    ),
    AiOption<String>(
      value: AiDisagreement.manualReview,
      label: 'Revue manuelle',
      description: 'En cas de désaccord, l’opportunité vous est soumise : c’est vous '
          'qui tranchez, depuis les Signaux.',
    ),
  ];

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final bool on = settings.ensembleEnabled;
    void edit(AiSettings Function(AiSettings) change) =>
        ref.read(aiConfigProvider.notifier).edit(change);

    return AiSection(
      title: 'Ensemble',
      subtitle: 'Confronter les deux moteurs avant de conclure.',
      children: <Widget>[
        AiSwitchField(
          label: 'Activer la confrontation',
          description: 'Les deux moteurs sont interrogés, puis leurs conclusions comparées.',
          value: on,
          onChanged: (bool value) =>
              edit((AiSettings current) => current.copyWith(ensembleEnabled: value)),
        ),
        AiSwitchField(
          label: 'Exiger un consensus avant un trade automatique',
          description: 'Sans accord des deux moteurs, aucun ordre n’est passé sans vous.',
          value: settings.requireConsensus,
          onChanged: on
              ? (bool value) =>
                  edit((AiSettings current) => current.copyWith(requireConsensus: value))
              : null,
        ),
        const SizedBox(height: 4),
        Text('En cas de désaccord', style: Theme.of(context).textTheme.titleMedium),
        const SizedBox(height: 8),
        AiChoiceField<String>(
          options: _behaviours,
          selected: settings.disagreementBehaviour,
          enabled: on,
          onChanged: (String value) =>
              edit((AiSettings current) => current.copyWith(disagreementBehaviour: value)),
        ),
        if (!on)
          const AiNote(
            text: 'La confrontation est désactivée : un seul moteur décide, selon le mode IA '
                'choisi plus haut.',
          ),
      ],
    );
  }
}
