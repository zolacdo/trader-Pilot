import 'package:flutter/material.dart';

import '../../../core/utils/formatters.dart';
import '../risk_form.dart';
import 'risk_fields.dart';
import 'risk_window_fields.dart';

/// Sections « limites » du moteur de risque (CDC section 23).
class RiskLimitsSections extends StatelessWidget {
  const RiskLimitsSections({
    super.key,
    required this.draft,
    required this.controller,
    required this.reference,
  });

  final RiskDraft draft;
  final RiskFormController controller;
  final RiskReference reference;

  /// Exemple chiffré et vivant du risque par trade.
  String _riskExample() {
    final double? percent = draft.number('riskPercent');
    final double? balance = reference.balance ?? draft.number('paperBalance');
    final String currency = reference.currency ?? draft.text('paperCurrency') ?? 'USD';
    if (percent == null || balance == null || balance <= 0) {
      return 'Solde de référence inconnu : impossible de chiffrer l\'exemple pour le moment.';
    }
    final double amount = balance * percent / 100;
    return '${Fmt.percent(percent)} de ${Fmt.money(balance, currency: currency)} = '
        '${Fmt.money(amount, currency: currency)} risqués par trade.';
  }

  /// Traduit le plancher en pourcentage réel : c'est la seule lecture qui
  /// empêche de le confondre avec un pourcentage de capital. Saisi à 1, il
  /// éteignait la modulation en laissant l'interrupteur sur « activé ».
  String _dynamicFloorExample() {
    final double? percent = draft.number('riskPercent');
    final double? floor = draft.number('dynamicRiskFloor');
    if (percent == null || floor == null || floor <= 0) {
      return 'Renseignez le risque par trade pour chiffrer l\'exemple.';
    }
    return 'Le plus mauvais signal prendra ${Fmt.percent(percent * floor)} '
        'au lieu de ${Fmt.percent(percent)}.';
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        RiskSection(
          title: 'Risque par trade',
          subtitle: 'La base du calcul du lot : ce que vous acceptez de perdre à chaque entrée.',
          children: <Widget>[
            RiskNumberField(
              label: 'Risque par trade',
              description: 'Part du capital risquée sur une seule position. C\'est exactement ce '
                  'que vous perdez si le stop loss est touché.',
              suffix: '%',
              value: draft.number('riskPercent'),
              example: _riskExample(),
              onChanged: (num? value) => controller.set('riskPercent', value),
            ),
            const RiskNote(
              text: 'Le lot est calculé à partir de ce pourcentage et de la distance au stop loss. '
                  'Plus le stop est loin, plus le lot est petit : le montant risqué, lui, ne bouge pas.',
            ),
            RiskSwitchField(
              label: 'Adapter le risque à chaque signal',
              description: 'Le pourcentage ci-dessus devient un plafond : chaque signal est '
                  'dimensionné selon sa qualité réelle (rendement attendu, spread, fraîcheur, '
                  'série de pertes en cours). Le risque peut être réduit, jamais augmenté.',
              value: draft.boolean('dynamicRiskEnabled', fallback: false),
              onChanged: (bool value) => controller.set('dynamicRiskEnabled', value),
            ),
            if (draft.boolean('dynamicRiskEnabled', fallback: false))
              RiskNumberField(
                label: 'Réduction maximale',
                description: 'Fraction du risque configuré au-dessous de laquelle un mauvais '
                    'signal ne descend jamais. Entre 0,05 et 0,90 : plus le chiffre est bas, '
                    'plus la modulation a de marge. 0,35 par défaut.',
                value: draft.number('dynamicRiskFloor'),
                example: _dynamicFloorExample(),
                onChanged: (num? value) => controller.set('dynamicRiskFloor', value),
              ),
          ],
        ),
        RiskSection(
          title: 'Limites journalières',
          subtitle: 'Les garde-fous qui arrêtent la journée avant qu\'elle ne dérape.',
          children: <Widget>[
            RiskNumberField(
              label: 'Risque journalier maximum',
              description: 'Somme des risques engagés depuis le début de la journée. Une fois '
                  'atteinte, aucun nouveau trade n\'est ouvert.',
              suffix: '%',
              value: draft.number('maxDailyRiskPercent'),
              onChanged: (num? value) => controller.set('maxDailyRiskPercent', value),
            ),
            RiskNumberField(
              label: 'Perte journalière maximum',
              description: 'Au-delà de cette perte sur la journée, plus aucun nouveau trade '
                  'n\'est ouvert.',
              suffix: '%',
              value: draft.number('maxDailyLossPercent'),
              onChanged: (num? value) => controller.set('maxDailyLossPercent', value),
            ),
            RiskNumberField(
              label: 'Drawdown maximum',
              description: 'Recul maximum accepté depuis le plus haut atteint par le compte. '
                  'Atteint, l\'automatisation cesse d\'ouvrir des positions.',
              suffix: '%',
              value: draft.number('maxDrawdownPercent'),
              onChanged: (num? value) => controller.set('maxDrawdownPercent', value),
            ),
            RiskNumberField(
              label: 'Objectif de gain journalier',
              description: 'Gain du jour à partir duquel on arrête de trader, pour ne pas rendre '
                  'au marché ce qui vient d\'être pris.',
              suffix: '%',
              value: draft.number('dailyProfitTargetPercent'),
              onChanged: (num? value) => controller.set('dailyProfitTargetPercent', value),
            ),
          ],
        ),
        RiskSection(
          title: 'Volumes et exposition',
          subtitle: 'Combien de positions et quelle taille au total.',
          children: <Widget>[
            RiskNumberField(
              label: 'Lot maximum',
              description: 'Taille maximale d\'une position, même si le calcul de risque autorise '
                  'davantage.',
              suffix: 'lot',
              value: draft.number('maxLot'),
              onChanged: (num? value) => controller.set('maxLot', value),
            ),
            RiskNumberField(
              label: 'Positions simultanées',
              description: 'Nombre de positions ouvertes en même temps, tous instruments '
                  'confondus.',
              decimal: false,
              value: draft.integer('maxPositions'),
              onChanged: (num? value) => controller.set('maxPositions', value?.toInt()),
            ),
            RiskNumberField(
              label: 'Positions par instrument',
              description: 'Empêche d\'empiler plusieurs positions sur le même instrument, où '
                  'un seul mouvement fait tout perdre en même temps.',
              decimal: false,
              value: draft.integer('maxPositionsPerSymbol'),
              onChanged: (num? value) => controller.set('maxPositionsPerSymbol', value?.toInt()),
            ),
            RiskNumberField(
              label: 'Exposition totale',
              description: 'Somme des lots ouverts. Limite l\'exposition globale au marché, même '
                  'répartie sur plusieurs instruments.',
              suffix: 'lot',
              value: draft.number('maxTotalExposureLots'),
              onChanged: (num? value) => controller.set('maxTotalExposureLots', value),
            ),
          ],
        ),
        RiskSection(
          title: 'Conditions de marché',
          subtitle: 'Refuser une entrée quand le marché la rend trop coûteuse.',
          children: <Widget>[
            RiskNumberField(
              label: 'Spread maximum',
              description: 'Un spread plus large que cette valeur fait refuser le signal : '
                  'l\'entrée démarrerait avec un handicap trop lourd.',
              suffix: 'points',
              decimal: false,
              value: draft.integer('maxSpreadPoints'),
              onChanged: (num? value) => controller.set('maxSpreadPoints', value?.toInt()),
            ),
            RiskNumberField(
              label: 'Slippage maximum',
              description: 'Écart de prix toléré entre le prix demandé et le prix réellement '
                  'obtenu par le broker.',
              suffix: 'points',
              decimal: false,
              value: draft.integer('maxSlippagePoints'),
              onChanged: (num? value) => controller.set('maxSlippagePoints', value?.toInt()),
            ),
            RiskNumberField(
              label: 'Âge maximum d\'un signal',
              description: 'Un signal reçu il y a plus longtemps que ce délai est refusé : le '
                  'prix a déjà bougé, le point d\'entrée n\'est plus valable.',
              suffix: 'secondes',
              decimal: false,
              value: draft.integer('maxSignalAgeSeconds'),
              onChanged: (num? value) => controller.set('maxSignalAgeSeconds', value?.toInt()),
            ),
          ],
        ),
        RiskSection(
          title: 'Exigences sur le signal',
          subtitle: 'Ce qu\'un signal doit contenir pour être seulement envisagé.',
          children: <Widget>[
            RiskSwitchField(
              label: 'Stop loss obligatoire',
              description: 'Un signal sans stop loss est refusé. Une position sans stop peut '
                  'perdre sans limite.',
              value: draft.boolean('requireStopLoss', fallback: true),
              onChanged: (bool value) => controller.set('requireStopLoss', value),
            ),
            RiskSwitchField(
              label: 'Take profit obligatoire',
              description: 'Un signal sans objectif de gain est refusé.',
              value: draft.boolean('requireTakeProfit'),
              onChanged: (bool value) => controller.set('requireTakeProfit', value),
            ),
            RiskNumberField(
              label: 'Ratio rendement / risque minimum',
              description: 'Rapport minimum entre le gain visé et la perte risquée. 2 signifie '
                  'viser deux fois ce que l\'on met en jeu.',
              value: draft.number('minRiskReward'),
              onChanged: (num? value) => controller.set('minRiskReward', value),
            ),
            RiskNumberField(
              label: 'Confiance minimum',
              description: 'Score attribué au signal lors de son interprétation, entre 0 et 1. '
                  'En dessous, le signal est refusé.',
              value: draft.number('minConfidence'),
              example: draft.number('minConfidence') == null
                  ? null
                  : 'Confiance exigée : ${Fmt.confidence(draft.number('minConfidence'))}.',
              onChanged: (num? value) => controller.set('minConfidence', value),
            ),
          ],
        ),
        RiskSection(
          title: 'Protections comportementales',
          subtitle: 'Couper court aux séries de pertes plutôt que de vouloir se refaire.',
          children: <Widget>[
            RiskNumberField(
              label: 'Pertes consécutives maximum',
              description: 'Nombre de pertes d\'affilée avant que l\'automatisation ne se '
                  'protège elle-même.',
              decimal: false,
              value: draft.integer('maxConsecutiveLosses'),
              onChanged: (num? value) => controller.set('maxConsecutiveLosses', value?.toInt()),
            ),
            RiskSwitchField(
              label: 'Pause après ces pertes',
              description: 'Met automatiquement le trading en pause une fois ce nombre de pertes '
                  'atteint. Les positions ouvertes ne sont pas fermées.',
              value: draft.boolean('pauseAfterMaxLosses'),
              onChanged: (bool value) => controller.set('pauseAfterMaxLosses', value),
            ),
            RiskNumberField(
              label: 'Durée de la pause',
              description: 'Temps pendant lequel aucun nouveau trade n\'est ouvert après cette '
                  'série de pertes.',
              suffix: 'minutes',
              decimal: false,
              value: draft.integer('pauseDurationMinutes'),
              onChanged: (num? value) => controller.set('pauseDurationMinutes', value?.toInt()),
            ),
          ],
        ),
        RiskSection(
          title: 'Fenêtres autorisées',
          subtitle: 'Quand et sur quoi le Bridge a le droit de trader.',
          children: <Widget>[
            RiskTimeField(
              label: 'Début de la plage horaire',
              description: 'Avant cette heure, les signaux sont refusés.',
              value: draft.text('tradingHoursStart'),
              onChanged: (String value) => controller.set('tradingHoursStart', value),
            ),
            RiskTimeField(
              label: 'Fin de la plage horaire',
              description: 'Après cette heure, les signaux sont refusés.',
              value: draft.text('tradingHoursEnd'),
              onChanged: (String value) => controller.set('tradingHoursEnd', value),
            ),
            const RiskNote(
              text: 'Les heures suivent le fuseau du poste qui héberge le Bridge, pas celui du '
                  'téléphone.',
            ),
            RiskDaysField(
              selected: draft.integers('tradingDays'),
              onChanged: (List<int> days) => controller.set('tradingDays', days),
            ),
            RiskSymbolsField(
              symbols: draft.strings('allowedSymbols'),
              onChanged: (List<String> symbols) => controller.set('allowedSymbols', symbols),
            ),
          ],
        ),
      ],
    );
  }
}
