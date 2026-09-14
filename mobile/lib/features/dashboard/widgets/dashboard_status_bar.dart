import 'package:flutter/material.dart';

import '../../../core/theme/app_theme.dart';
import '../../../core/widgets/app_widgets.dart';
import '../../bridge/models/bridge_json.dart';

/// Bandeau des cinq statuts suivis par l'accueil (CDC section 31) :
/// Bridge, Telegram, MT5, OpenRouter et trading automatique.
class DashboardStatusBar extends StatelessWidget {
  const DashboardStatusBar({
    super.key,
    required this.payload,
    required this.bridgeOnline,
  });

  final Map<String, dynamic> payload;

  /// Joignabilité réelle mesurée par l'application, pas celle annoncée par
  /// le Bridge : hors ligne, la charge utile vient du cache.
  final bool bridgeOnline;

  @override
  Widget build(BuildContext context) {
    final Map<String, dynamic> telegram = Json.map(payload['telegram']);
    final Map<String, dynamic> mt5 = Json.map(payload['mt5']);
    final Map<String, dynamic> openrouter = Json.map(payload['openrouter']);
    final Map<String, dynamic> trading = Json.map(payload['trading']);

    final bool autoEnabled = Json.flag(trading['autoTradingEnabled']);
    final bool paused = Json.flag(trading['paused']);

    final List<_Status> items = <_Status>[
      _Status('Bridge', bridgeOnline),
      _Status('Telegram', Json.flag(telegram['authorized'])),
      _Status('MT5', Json.text(mt5['state']) == 'CONNECTED'),
      _Status('OpenRouter', Json.flag(openrouter['textModelOk'])),
      _Status(
        'Auto trading',
        autoEnabled && !paused,
        onLabel: 'actif',
        offLabel: paused ? 'en pause' : 'inactif',
        warning: autoEnabled && paused,
      ),
    ];

    return AppCard(
      padding: const EdgeInsets.all(AppSpacing.md),
      child: Wrap(
        spacing: AppSpacing.sm,
        runSpacing: AppSpacing.sm,
        children: <Widget>[
          for (final _Status item in items)
            StatusChip(
              label: '${item.label} : ${item.ok ? item.onLabel : item.offLabel}',
              tone: item.ok
                  ? StatusTone.good
                  : (item.warning ? StatusTone.warning : StatusTone.bad),
              icon: item.ok ? Icons.check_circle_outline : Icons.error_outline,
              dense: true,
            ),
        ],
      ),
    );
  }
}

class _Status {
  const _Status(
    this.label,
    this.ok, {
    this.onLabel = 'connecté',
    this.offLabel = 'non connecté',
    this.warning = false,
  });

  final String label;
  final bool ok;
  final String onLabel;
  final String offLabel;
  final bool warning;
}
