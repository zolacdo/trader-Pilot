import 'package:flutter/material.dart';

import '../risk_form.dart';
import 'risk_fields.dart';
import 'risk_window_fields.dart';

/// Sections « gestion de position » : TP multiples, break even, trailing,
/// paper trading (CDC sections 28, 29, 30 et 71).
class RiskManagementSections extends StatelessWidget {
  const RiskManagementSections({
    super.key,
    required this.draft,
    required this.controller,
  });

  final RiskDraft draft;
  final RiskFormController controller;

  static const List<RiskOption<String>> _tpStrategies = <RiskOption<String>>[
    RiskOption<String>(
      value: 'FIRST_TP_ONLY',
      label: 'Premier objectif seulement',
      description: 'Une seule position, fermée dès le premier take profit. Le plus simple et '
          'le plus prudent.',
    ),
    RiskOption<String>(
      value: 'SPLIT_POSITIONS',
      label: 'Positions séparées',
      description: 'Une position distincte par objectif, selon la répartition ci-dessous. '
          'Chacune vit sa vie.',
    ),
    RiskOption<String>(
      value: 'PARTIAL_CLOSE',
      label: 'Fermetures partielles',
      description: 'Une seule position, fermée par morceaux à chaque objectif atteint.',
    ),
    RiskOption<String>(
      value: 'LAST_TP_ONLY',
      label: 'Dernier objectif seulement',
      description: 'Une seule position gardée jusqu\'au dernier objectif. Le plus ambitieux, '
          'et le plus souvent ramené au break even.',
    ),
  ];

  static const List<RiskOption<String>> _breakEvenTriggers = <RiskOption<String>>[
    RiskOption<String>(
      value: 'TP1_HIT',
      label: 'Premier objectif atteint',
      description: 'Le stop remonte dès que le premier take profit est touché.',
    ),
    RiskOption<String>(
      value: 'R_MULTIPLE',
      label: 'Multiple du risque atteint',
      description: 'Le stop remonte quand le gain latent atteint un multiple du risque initial.',
    ),
    RiskOption<String>(
      value: 'POINTS',
      label: 'Nombre de points atteint',
      description: 'Le stop remonte après un gain exprimé en points de cotation.',
    ),
    RiskOption<String>(
      value: 'SIGNAL_ONLY',
      label: 'Sur demande du canal',
      description: 'Le break even n\'est appliqué que si le canal l\'annonce explicitement.',
    ),
  ];

  static const List<RiskOption<String>> _trailingModes = <RiskOption<String>>[
    RiskOption<String>(
      value: 'DISABLED',
      label: 'Désactivé',
      description: 'Le stop loss ne bouge pas tout seul.',
    ),
    RiskOption<String>(
      value: 'FIXED_DISTANCE',
      label: 'Distance fixe',
      description: 'Le stop suit le prix à une distance constante, dès que le trade est en gain.',
    ),
    RiskOption<String>(
      value: 'AFTER_TP1',
      label: 'Après le premier objectif',
      description: 'Le suivi ne démarre qu\'une fois le premier take profit touché.',
    ),
    RiskOption<String>(
      value: 'R_BASED',
      label: 'Basé sur le risque',
      description: 'Le stop suit le prix par paliers exprimés en multiples du risque initial.',
    ),
  ];

  @override
  Widget build(BuildContext context) {
    final String trailingMode = draft.text('trailingMode') ?? 'DISABLED';
    final bool trailingActive = trailingMode != 'DISABLED';
    final bool breakEvenEnabled = draft.boolean('breakEvenEnabled');
    final String breakEvenTrigger = draft.text('breakEvenTrigger') ?? 'TP1_HIT';

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        RiskSection(
          title: 'Take profits multiples',
          subtitle: 'Ce que le Bridge fait quand un signal annonce TP1, TP2, TP3.',
          children: <Widget>[
            RiskChoiceField<String>(
              label: 'Stratégie appliquée',
              description: 'Choisissez comment le volume est réparti entre les objectifs.',
              options: _tpStrategies,
              selected: draft.text('multiTpStrategy'),
              onChanged: (String value) => controller.set('multiTpStrategy', value),
            ),
            RiskRatiosField(
              ratios: draft.doubles('splitRatios'),
              onChanged: (List<double> ratios) => controller.set('splitRatios', ratios),
            ),
            const RiskNote(
              text: 'La répartition n\'est utilisée que par les stratégies « positions séparées » '
                  'et « fermetures partielles ».',
            ),
          ],
        ),
        RiskSection(
          title: 'Break even',
          subtitle: 'Remonter le stop au prix d\'entrée pour qu\'un trade ne puisse plus perdre.',
          children: <Widget>[
            RiskSwitchField(
              label: 'Break even automatique',
              description: 'Quand la condition ci-dessous est remplie, le stop loss est déplacé '
                  'au prix d\'entrée sans intervention.',
              value: breakEvenEnabled,
              onChanged: (bool value) => controller.set('breakEvenEnabled', value),
            ),
            if (breakEvenEnabled) ...<Widget>[
              RiskChoiceField<String>(
                label: 'Déclencheur',
                description: 'Le moment exact où le stop est remonté.',
                options: _breakEvenTriggers,
                selected: breakEvenTrigger,
                onChanged: (String value) => controller.set('breakEvenTrigger', value),
              ),
              if (breakEvenTrigger == 'R_MULTIPLE')
                RiskNumberField(
                  key: const ValueKey<String>('breakEvenRMultiple'),
                  label: 'Multiple du risque',
                  description: 'Gain latent, exprimé en fois le risque initial, à partir duquel '
                      'le stop remonte. 1 signifie « autant gagné que risqué ».',
                  suffix: 'R',
                  value: draft.number('breakEvenRMultiple'),
                  onChanged: (num? value) => controller.set('breakEvenRMultiple', value),
                ),
              if (breakEvenTrigger == 'POINTS')
                RiskNumberField(
                  key: const ValueKey<String>('breakEvenPoints'),
                  label: 'Gain en points',
                  description: 'Nombre de points de gain à partir duquel le stop remonte.',
                  suffix: 'points',
                  decimal: false,
                  value: draft.integer('breakEvenPoints'),
                  onChanged: (num? value) => controller.set('breakEvenPoints', value?.toInt()),
                ),
              RiskNumberField(
                key: const ValueKey<String>('breakEvenOffsetPoints'),
                label: 'Marge au-dessus de l\'entrée',
                description: 'Petit décalage placé en votre faveur pour couvrir le spread et les '
                    'frais. 0 place le stop exactement au prix d\'entrée.',
                suffix: 'points',
                decimal: false,
                value: draft.integer('breakEvenOffsetPoints'),
                onChanged: (num? value) => controller.set('breakEvenOffsetPoints', value?.toInt()),
              ),
              const RiskNote(
                text: 'Le Bridge respecte toujours la distance minimale imposée par le broker : '
                    'un break even trop proche du prix est refusé côté MetaTrader.',
              ),
            ],
          ],
        ),
        RiskSection(
          title: 'Trailing stop',
          subtitle: 'Faire suivre le stop loss au prix pour protéger un gain qui grandit.',
          children: <Widget>[
            RiskChoiceField<String>(
              label: 'Mode de suivi',
              description: 'Aucune intelligence artificielle n\'intervient ici : ce sont des '
                  'règles fixes.',
              options: _trailingModes,
              selected: trailingMode,
              onChanged: (String value) => controller.set('trailingMode', value),
            ),
            if (trailingActive) ...<Widget>[
              RiskNumberField(
                key: const ValueKey<String>('trailingDistancePoints'),
                label: 'Distance de suivi',
                description: 'Écart conservé entre le prix et le stop loss pendant le suivi.',
                suffix: 'points',
                decimal: false,
                value: draft.integer('trailingDistancePoints'),
                onChanged: (num? value) => controller.set('trailingDistancePoints', value?.toInt()),
              ),
              RiskNumberField(
                key: const ValueKey<String>('trailingStepPoints'),
                label: 'Pas de déplacement',
                description: 'Le stop n\'est déplacé que lorsque le prix a avancé d\'au moins '
                    'cette valeur. Évite de harceler le broker à chaque tick.',
                suffix: 'points',
                decimal: false,
                value: draft.integer('trailingStepPoints'),
                onChanged: (num? value) => controller.set('trailingStepPoints', value?.toInt()),
              ),
            ],
          ],
        ),
        RiskSection(
          title: 'Paper trading',
          subtitle: 'Le mode d\'entraînement : les signaux sont simulés, aucun ordre ne part.',
          children: <Widget>[
            RiskNumberField(
              label: 'Capital simulé',
              description: 'Solde de départ du compte fictif. Il sert de base au calcul des lots '
                  'et des statistiques en mode paper trading.',
              suffix: draft.text('paperCurrency') ?? 'USD',
              value: draft.number('paperBalance'),
              onChanged: (num? value) => controller.set('paperBalance', value),
            ),
            const RiskNote(
              text: 'Modifier ce capital n\'a aucun effet sur un compte MetaTrader réel ou démo : '
                  'seul le mode paper trading l\'utilise.',
            ),
          ],
        ),
      ],
    );
  }
}
