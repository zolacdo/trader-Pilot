import 'package:flutter/material.dart';

import '../../../core/theme/app_colors.dart';
import '../../../core/theme/app_theme.dart';
import '../../../core/utils/formatters.dart';
import '../../../core/widgets/app_widgets.dart';
import '../../bridge/models/bridge_json.dart';

/// Bloc de chiffres de l'accueil (CDC section 31).
///
/// Une valeur absente reste « -- » : aucun solde ni aucun profit n'est inventé.
class DashboardMetrics extends StatelessWidget {
  const DashboardMetrics({super.key, required this.payload});

  final Map<String, dynamic> payload;

  @override
  Widget build(BuildContext context) {
    final Map<String, dynamic> metrics = Json.map(payload['metrics']);
    final String currency = Json.text(metrics['currency']) ?? 'USD';

    final num? profitToday = Json.number(metrics['profitToday']);
    final num? lossToday = Json.number(metrics['lossToday']);
    final num? drawdown = Json.number(metrics['drawdownPercent']);
    final num? floating = Json.number(metrics['floatingPnl']);

    final List<_Metric> tiles = <_Metric>[
      _Metric(
        label: 'Balance',
        value: Fmt.money(Json.number(metrics['balance']), currency: currency),
      ),
      _Metric(
        label: 'Equity',
        value: Fmt.money(Json.number(metrics['equity']), currency: currency),
        caption: floating == null
            ? null
            : 'Latent ${Fmt.signedMoney(floating, currency: currency)}',
      ),
      _Metric(
        label: 'Profit aujourd\'hui',
        value: profitToday == null ? '--' : Fmt.signedMoney(profitToday, currency: currency),
        color: profitToday == null ? null : AppColors.forAmount(profitToday),
      ),
      _Metric(
        label: 'Perte aujourd\'hui',
        value: lossToday == null ? '--' : Fmt.signedMoney(lossToday, currency: currency),
        color: lossToday == null ? null : AppColors.forAmount(lossToday),
      ),
      _Metric(
        label: 'Drawdown',
        value: Fmt.percent(drawdown),
        color: (drawdown ?? 0) > 0 ? AppColors.loss : null,
        caption: 'Depuis le plus haut de l\'equity',
      ),
      _Metric(
        label: 'Marge libre',
        value: Fmt.money(Json.number(metrics['marginFree']), currency: currency),
      ),
    ];

    return LayoutBuilder(
      builder: (BuildContext context, BoxConstraints constraints) {
        final double width = (constraints.maxWidth - AppSpacing.md) / 2;
        return Wrap(
          spacing: AppSpacing.md,
          runSpacing: AppSpacing.md,
          children: <Widget>[
            for (final _Metric tile in tiles)
              SizedBox(
                width: width,
                child: AppCard(
                  padding: const EdgeInsets.all(AppSpacing.md),
                  child: MetricTile(
                    label: tile.label,
                    value: tile.value,
                    valueColor: tile.color,
                    caption: tile.caption,
                    compact: true,
                  ),
                ),
              ),
          ],
        );
      },
    );
  }
}

/// Description d'une tuile, assemblée avant l'affichage.
class _Metric {
  const _Metric({required this.label, required this.value, this.color, this.caption});

  final String label;
  final String value;
  final Color? color;
  final String? caption;
}
