import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../ai_config_providers.dart';
import '../ai_labels.dart';
import '../models/ai_settings.dart';
import 'ai_shell.dart';

/// Mode IA (CDC2 section 95) : qui répond, dans quel ordre.
class AiModeSection extends ConsumerWidget {
  const AiModeSection({super.key, required this.settings});

  final AiSettings settings;

  static final List<AiOption<String>> _options = AiMode.all
      .map((String code) => AiOption<String>(
            value: code,
            label: AiLabels.mode(code),
            description: AiLabels.modeDescription(code),
          ))
      .toList(growable: false);

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return AiSection(
      title: 'Mode IA',
      subtitle: 'Quel moteur répond, et dans quel ordre.',
      children: <Widget>[
        AiChoiceField<String>(
          options: _options,
          selected: settings.mode,
          onChanged: (String mode) => ref.read(aiConfigProvider.notifier).edit(
                (AiSettings current) => current.copyWith(
                  mode: mode,
                  // Choisir « Ensemble » comme mode de routage active la
                  // confrontation : sans cela le réglage resterait sans effet.
                  ensembleEnabled: mode == AiMode.ensemble ? true : null,
                ),
              ),
        ),
        const AiNote(
          text: 'Le mode ne change rien à la destination des ordres. Le mode d’exécution '
              '(paper, démo, réel) reste dans les Paramètres, et le moteur de risque garde '
              'le dernier mot sur chaque trade.',
        ),
      ],
    );
  }
}
