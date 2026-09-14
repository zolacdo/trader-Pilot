import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/providers/bridge_data.dart';
import '../../../core/theme/app_colors.dart';
import '../../../core/theme/app_theme.dart';
import '../../../core/utils/formatters.dart';
import '../../../core/widgets/app_widgets.dart';
import '../trades_models.dart';
import '../trades_providers.dart';

/// Libellé français du mode d'exécution.
String executionModeLabel(String? mode) {
  return switch (mode) {
    'PAPER' => 'Paper trading',
    'MT5_DEMO' => 'MT5 démo',
    'MT5_LIVE' => 'MT5 réel',
    null => '--',
    _ => mode,
  };
}

/// Bandeau rappelant où partent réellement les ordres et combien la journée
/// pèse en flottant.
class TradesHeader extends ConsumerWidget {
  const TradesHeader({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final ThemeData theme = Theme.of(context);
    final bool dark = theme.brightness == Brightness.dark;

    final Map<String, dynamic> state =
        ref.watch(tradingStateProvider).valueOrNull ?? const <String, dynamic>{};
    final PositionsSnapshot? positions = ref.watch(openPositionsProvider).valueOrNull;

    final String? mode = asText(state['executionMode']) ?? positions?.executionMode;
    final bool live = mode == 'MT5_LIVE';
    final bool paused = asBool(state['paused']);
    final bool autoTrading = asBool(state['autoTradingEnabled']);
    final String? pauseReason = asText(state['pauseReason']);
    final double? floating = positions?.floatingPnl;

    return Padding(
      padding: const EdgeInsets.fromLTRB(AppSpacing.lg, AppSpacing.md, AppSpacing.lg, 0),
      child: AppCard(
        padding: const EdgeInsets.all(AppSpacing.md),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: <Widget>[
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: <Widget>[
                Expanded(
                  child: MetricTile(
                    label: 'Mode d\'exécution',
                    value: executionModeLabel(mode),
                    compact: true,
                    caption: live
                        ? 'Les ordres partent sur un compte réel'
                        : 'Aucun ordre sur compte réel',
                  ),
                ),
                Expanded(
                  child: MetricTile(
                    label: 'P&L flottant',
                    value: Fmt.signedMoney(floating),
                    compact: true,
                    valueColor: floating == null ? null : AppColors.forAmount(floating, dark: dark),
                    caption: positions == null
                        ? null
                        : '${positions.items.length} position(s) ouverte(s)',
                  ),
                ),
              ],
            ),
            const SizedBox(height: AppSpacing.sm),
            Wrap(
              spacing: AppSpacing.sm,
              runSpacing: AppSpacing.sm,
              children: <Widget>[
                StatusChip(
                  label: autoTrading ? 'Auto trading actif' : 'Auto trading arrêté',
                  tone: autoTrading ? StatusTone.good : StatusTone.neutral,
                  dense: true,
                ),
                if (paused)
                  const StatusChip(
                    label: 'En pause',
                    tone: StatusTone.warning,
                    icon: Icons.pause_circle_outline,
                    dense: true,
                  ),
              ],
            ),
            if (paused && pauseReason != null) ...<Widget>[
              const SizedBox(height: AppSpacing.xs),
              Text('Motif : $pauseReason', style: theme.textTheme.bodySmall),
            ],
          ],
        ),
      ),
    );
  }
}
