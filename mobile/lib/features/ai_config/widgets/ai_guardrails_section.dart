import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/widgets/app_widgets.dart';
import '../ai_config_providers.dart';
import '../models/ai_settings.dart';
import 'ai_shell.dart';

/// Garde-fous du trading IA (CDC2 sections 95 et 110).
///
/// Le mode d'exécution (paper, démo, réel) n'est pas modifiable ici : il reste
/// dans les Paramètres. Cet écran ne règle que ce que l'IA a le droit de faire.
class AiGuardrailsSection extends ConsumerWidget {
  const AiGuardrailsSection({super.key, required this.settings});

  final AiSettings settings;

  Future<void> _toggleAiTrading(BuildContext context, WidgetRef ref, bool enabled) async {
    if (enabled) {
      final bool ok = await confirmAction(
        context,
        title: 'Activer le trading piloté par l’IA',
        message: 'Le Bridge pourra ouvrir des positions à partir des opportunités trouvées par '
            'l’IA, sans vous les soumettre une par une. Le moteur de risque garde le '
            'dernier mot : il refusera tout ordre qui dépasse vos limites.\n\n'
            'Tant que le mode observation reste actif, ces décisions sont enregistrées mais '
            'aucun ordre n’est envoyé.',
        confirmLabel: 'Activer',
      );
      if (!ok) return;
    }
    ref
        .read(aiConfigProvider.notifier)
        .edit((AiSettings current) => current.copyWith(aiTradingEnabled: enabled));
  }

  Future<void> _toggleShadow(BuildContext context, WidgetRef ref, bool enabled) async {
    if (!enabled) {
      final bool ok = await confirmAction(
        context,
        title: 'Quitter le mode observation',
        message: 'Les décisions de l’IA cesseront d’être seulement enregistrées : '
            'elles pourront devenir de vrais ordres, dans le mode d’exécution configuré '
            'dans les Paramètres.',
        confirmLabel: 'Quitter l’observation',
        destructive: true,
      );
      if (!ok) return;
    }
    ref
        .read(aiConfigProvider.notifier)
        .edit((AiSettings current) => current.copyWith(shadowMode: enabled));
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    void edit(AiSettings Function(AiSettings) change) =>
        ref.read(aiConfigProvider.notifier).edit(change);

    return AiSection(
      title: 'Garde-fous du trading IA',
      subtitle: 'Ce que l’IA a le droit de déclencher, et jusqu’où.',
      accent: true,
      children: <Widget>[
        AiSwitchField(
          label: 'Trading piloté par l’IA',
          description: 'Autorise le Bridge à agir sur les opportunités trouvées par l’IA.',
          value: settings.aiTradingEnabled,
          onChanged: (bool value) => _toggleAiTrading(context, ref, value),
        ),
        AiSwitchField(
          label: 'Trading à partir des signaux Telegram',
          description: 'Autorise l’exécution des signaux reçus des canaux suivis.',
          value: settings.telegramTradingEnabled,
          onChanged: (bool value) =>
              edit((AiSettings current) => current.copyWith(telegramTradingEnabled: value)),
        ),
        AiSwitchField(
          label: 'Mode observation',
          description: 'Les décisions sont enregistrées et mesurées, mais aucun ordre ne part.',
          value: settings.shadowMode,
          onChanged: (bool value) => _toggleShadow(context, ref, value),
        ),
        const AiNote(
          text: 'Le mode d’exécution (paper, MT5 démo, MT5 réel) ne se change pas ici : '
              'il reste dans les Paramètres. Quelles que soient ces autorisations, le moteur '
              'de risque garde le dernier mot sur chaque ordre.',
          warning: true,
        ),
        AiNumberField(
          label: 'Trades IA par jour',
          description: 'Nombre maximal de positions ouvertes sur décision de l’IA '
              '(0 à 50).',
          value: settings.maxAiTradesPerDay,
          onChanged: (num? value) =>
              edit((AiSettings current) => current.copyWith(maxAiTradesPerDay: value?.toInt() ?? 0)),
        ),
        AiNumberField(
          label: 'Trades Telegram par jour',
          description: 'Toutes sources confondues, tous canaux suivis (0 à 100).',
          value: settings.maxTelegramTradesPerDay,
          onChanged: (num? value) => edit(
            (AiSettings current) =>
                current.copyWith(maxTelegramTradesPerDay: value?.toInt() ?? 0),
          ),
        ),
        AiNumberField(
          label: 'Trades par instrument et par jour',
          description: 'Évite d’empiler plusieurs positions sur le même instrument '
              '(0 à 50).',
          value: settings.maxTradesPerSymbolPerDay,
          onChanged: (num? value) => edit(
            (AiSettings current) =>
                current.copyWith(maxTradesPerSymbolPerDay: value?.toInt() ?? 0),
          ),
        ),
        AiNumberField(
          label: 'Confiance minimale d’une opportunité',
          description: 'En dessous de ce seuil, l’opportunité est ignorée (0 à 100 %).',
          suffix: '%',
          value: (settings.minOpportunityConfidence * 100).round(),
          onChanged: (num? value) => edit(
            (AiSettings current) => current.copyWith(
              // Pas de correction silencieuse : une valeur hors bornes est
              // refusée à l'enregistrement, avec un message explicite.
              minOpportunityConfidence: (value?.toDouble() ?? 0) / 100,
            ),
          ),
        ),
      ],
    );
  }
}
