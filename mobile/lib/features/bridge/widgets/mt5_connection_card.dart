import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/endpoints.dart';
import '../../../core/connection/connection_controller.dart';
import '../../../core/providers/bridge_data.dart';
import '../../../core/utils/formatters.dart';
import '../../../core/widgets/app_widgets.dart';
import '../models/bridge_action.dart';
import '../models/bridge_json.dart';
import '../models/bridge_labels.dart';
import 'connection_block.dart';

/// Liaison MetaTrader 5 : terminal, compte et type de compte.
///
/// Le numéro de compte n'est jamais affiché en entier : seuls les quatre
/// derniers chiffres sont visibles (`***1234`).
class Mt5ConnectionCard extends ConsumerStatefulWidget {
  const Mt5ConnectionCard({super.key, required this.payload});

  final Map<String, dynamic> payload;

  @override
  ConsumerState<Mt5ConnectionCard> createState() => _Mt5ConnectionCardState();
}

class _Mt5ConnectionCardState extends ConsumerState<Mt5ConnectionCard> {
  bool _busy = false;

  Future<void> _reconnect() async {
    if (_busy) return;
    setState(() => _busy = true);
    await runBridgeAction(
      context,
      action: () => ref.read(apiClientProvider).postJson(Endpoints.mt5Reconnect),
      successMessage: 'Reconnexion MetaTrader 5 demandée.',
    );
    if (!mounted) return;
    setState(() => _busy = false);
    refreshBridgeData(ref);
  }

  @override
  Widget build(BuildContext context) {
    final Map<String, dynamic> mt5 = Json.map(widget.payload['mt5']);
    final Map<String, dynamic> mt5Account = Json.map(mt5['account']);
    final Map<String, dynamic> account = Json.map(widget.payload['account']);

    final String? state = Json.text(mt5['state']);
    final bool connected = BridgeLabels.isConnected(state);
    final String? kind = Json.text(mt5Account['kind']) ?? Json.text(account['kind']);
    final String currency = Json.text(mt5Account['currency']) ?? 'USD';

    return ConnectionBlock(
      title: 'MetaTrader 5',
      icon: Icons.candlestick_chart_outlined,
      connected: connected,
      stateLabel: BridgeLabels.connection(state),
      subtitle: 'Terminal utilisé pour envoyer et suivre les ordres.',
      errorMessage: Json.text(mt5['error']),
      rows: <Widget>[
        DetailRow(
          label: 'Compte',
          value: BridgeLabels.maskedLogin(mt5Account['login']),
          monospace: true,
        ),
        DetailRow(label: 'Serveur', value: Json.text(mt5Account['server']) ?? '--'),
        DetailRow(
          label: 'Balance',
          value: Fmt.money(Json.number(mt5Account['balance']), currency: currency),
          monospace: true,
        ),
        DetailRow(label: 'Type de compte', value: BridgeLabels.accountKind(kind)),
        if (Json.text(mt5['terminalPath']) != null)
          DetailRow(label: 'Terminal', value: Json.text(mt5['terminalPath'])!),
      ],
      actions: <Widget>[
        ConnectionAction(
          label: 'Reconnecter',
          icon: Icons.refresh,
          busy: _busy,
          onPressed: _reconnect,
        ),
      ],
    );
  }
}
