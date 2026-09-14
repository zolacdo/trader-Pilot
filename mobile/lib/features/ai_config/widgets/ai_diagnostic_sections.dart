import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/theme/app_theme.dart';
import '../../../core/utils/formatters.dart';
import '../../../core/widgets/app_widgets.dart';
import '../ai_config_providers.dart';
import '../ai_labels.dart';
import '../models/ai_status.dart';
import 'ai_shell.dart';

/// Pastille d'état d'un moteur : vert en ligne, rouge hors service.
StatusChip aiHealthChip(String health) {
  final String code = health.toUpperCase();
  return StatusChip(
    label: AiLabels.health(code),
    tone: switch (code) {
      'ONLINE' => StatusTone.good,
      'DEGRADED' => StatusTone.warning,
      _ => StatusTone.bad,
    },
    icon: switch (code) {
      'ONLINE' => Icons.check_circle_outline,
      'DEGRADED' => Icons.error_outline,
      _ => Icons.cancel_outlined,
    },
    dense: true,
  );
}

/// Pastille d'état vivante d'un moteur, affichée en tête de section.
///
/// Elle interroge `GET /ai/status` : l'écran de configuration montre ainsi
/// l'état réel du moteur qu'on est en train de régler (CDC2 section 95).
class AiHealthBadge extends ConsumerWidget {
  const AiHealthBadge({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return ref.watch(aiStatusProvider).maybeWhen(
          data: (AiStatus status) => aiHealthChip(status.openRouter.health),
          orElse: () => const SizedBox.shrink(),
        );
  }
}

/// Fiche d'un moteur : état, modèle, capacités, latence.
class AiProviderCard extends StatelessWidget {
  const AiProviderCard({super.key, required this.state, required this.title});

  final AiProviderState state;
  final String title;

  @override
  Widget build(BuildContext context) {
    return AiSection(
      title: title,
      subtitle: 'État renvoyé par le Bridge, sans interprétation.',
      action: aiHealthChip(state.health),
      children: <Widget>[
        DetailRow(label: 'Configuré', value: AiLabels.yesNo(state.configured)),
        DetailRow(label: 'Joignable', value: AiLabels.yesNo(state.available)),
        DetailRow(label: 'Modèle actif', value: state.model ?? '--'),
        DetailRow(label: 'Modèle vision', value: state.visionModel ?? '--'),
        DetailRow(label: 'Réponses JSON', value: AiLabels.yesNo(state.supportsJson)),
        DetailRow(label: 'Appels d’outils', value: AiLabels.yesNo(state.supportsTools)),
        DetailRow(label: 'Vision', value: AiLabels.yesNo(state.supportsVision)),
        DetailRow(
          label: 'Taille de contexte',
          value: state.contextSize == null ? '--' : '${state.contextSize} jetons',
        ),
        DetailRow(label: 'Latence', value: AiLabels.latency(state.latencyMs)),
        if (state.detail != null) AiNote(text: state.detail!),
        if (state.error != null) AiNote(text: state.error!, warning: true),
      ],
    );
  }
}

/// État du routeur et dernière décision de routage (CDC2 section 96).
class AiRouterCard extends StatelessWidget {
  const AiRouterCard({super.key, required this.status});

  final AiStatus status;

  @override
  Widget build(BuildContext context) {
    final AiRoutingDecision? routing = status.lastRouting;
    return AiSection(
      title: 'Routeur IA',
      subtitle: 'Qui a répondu en dernier, et pourquoi.',
      action: StatusChip(
        label: AiLabels.mode(status.mode),
        tone: status.anyAvailable ? StatusTone.accent : StatusTone.bad,
        dense: true,
      ),
      children: <Widget>[
        DetailRow(label: 'Mode de routage', value: AiLabels.mode(status.mode)),
        DetailRow(
          label: 'Une intelligence disponible',
          value: AiLabels.yesNo(status.anyAvailable),
        ),
        const SizedBox(height: AppSpacing.sm),
        Text('Dernière décision de routage', style: Theme.of(context).textTheme.titleMedium),
        if (routing == null)
          const AiNote(text: 'Aucune décision de routage enregistrée pour l’instant.')
        else ...<Widget>[
          DetailRow(label: 'Tâche', value: AiLabels.task(routing.task)),
          DetailRow(label: 'Moteur retenu', value: AiLabels.provider(routing.chosen)),
          DetailRow(label: 'Repli utilisé', value: AiLabels.yesNo(routing.fallbackUsed)),
          DetailRow(label: 'Motif', value: routing.reason ?? '--'),
          DetailRow(label: 'Horodatage', value: Fmt.dayTime(routing.at)),
        ],
        if (status.detail != null) AiNote(text: status.detail!, warning: true),
      ],
    );
  }
}

/// État du service de consensus.
class AiConsensusCard extends StatelessWidget {
  const AiConsensusCard({super.key, required this.status});

  final AiStatus status;

  @override
  Widget build(BuildContext context) {
    final bool online = status.consensusOnline;
    return AiSection(
      title: 'Service de consensus',
      subtitle: 'Confrontation des deux moteurs avant décision.',
      action: StatusChip(
        label: online ? 'En ligne' : 'Hors service',
        tone: online ? StatusTone.good : StatusTone.bad,
        icon: online ? Icons.check_circle_outline : Icons.cancel_outlined,
        dense: true,
      ),
      children: <Widget>[
        DetailRow(label: 'Mode Ensemble', value: AiLabels.yesNo(status.ensembleEnabled)),
        DetailRow(
          label: 'Consensus exigé avant un trade automatique',
          value: AiLabels.yesNo(status.requireConsensus),
        ),
        DetailRow(
          label: 'En cas de désaccord',
          value: AiLabels.disagreement(status.disagreementBehaviour),
        ),
        DetailRow(label: 'Trading IA autorisé', value: AiLabels.yesNo(status.aiTradingEnabled)),
        DetailRow(label: 'Mode observation', value: AiLabels.yesNo(status.shadowMode)),
        if (status.ensembleEnabled && !online)
          const AiNote(
            text: 'La confrontation est demandée mais les deux moteurs ne répondent pas '
                'ensemble : aucune décision ne peut être validée par consensus.',
            warning: true,
          ),
      ],
    );
  }
}
