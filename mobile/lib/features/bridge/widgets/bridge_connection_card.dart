import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/connection/connection_controller.dart';
import '../../../core/providers/bridge_data.dart';
import '../../../core/routing/app_router.dart';
import '../../../core/theme/app_theme.dart';
import '../../../core/widgets/app_widgets.dart';
import '../models/bridge_json.dart';
import 'connection_block.dart';

/// Liaison téléphone ↔ Bridge : adresses, latence mesurée, dissociation.
class BridgeConnectionCard extends ConsumerStatefulWidget {
  const BridgeConnectionCard({super.key, required this.payload});

  /// Charge utile complète de `GET /status`.
  final Map<String, dynamic> payload;

  @override
  ConsumerState<BridgeConnectionCard> createState() => _BridgeConnectionCardState();
}

class _BridgeConnectionCardState extends ConsumerState<BridgeConnectionCard> {
  bool _testing = false;
  bool _busy = false;

  /// Latence du dernier test, en millisecondes. Jamais estimée : tant qu'aucun
  /// test n'a été lancé, l'écran affiche « -- ».
  int? _latencyMs;

  Future<void> _test(String? url) async {
    if (url == null || url.isEmpty || _testing) return;
    setState(() => _testing = true);
    final Stopwatch watch = Stopwatch()..start();
    final bool reachable = await ref.read(connectionProvider.notifier).testAddress(url);
    watch.stop();
    if (!mounted) return;
    setState(() {
      _testing = false;
      _latencyMs = reachable ? watch.elapsedMilliseconds : null;
    });
    showToast(
      context,
      reachable
          ? 'Bridge joignable en ${watch.elapsedMilliseconds} ms.'
          : 'Aucune réponse à cette adresse.',
      error: !reachable,
    );
  }

  Future<void> _changeAddress(String? current) async {
    final String? url = await _askAddress(current);
    if (url == null || !mounted) return;
    setState(() => _busy = true);
    await ref.read(connectionProvider.notifier).setBaseUrl(url);
    if (!mounted) return;
    setState(() {
      _busy = false;
      _latencyMs = null;
    });
    refreshBridgeData(ref);
    showToast(context, 'Nouvelle adresse enregistrée.');
  }

  Future<String?> _askAddress(String? current) async {
    final TextEditingController controller = TextEditingController(text: current ?? '');
    final String? result = await showDialog<String>(
      context: context,
      builder: (BuildContext context) => AlertDialog(
        title: const Text('Changer d\'adresse'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: <Widget>[
            const Text(
              'Saisissez l\'adresse à laquelle joindre le Bridge. '
              'L\'appairage actuel est conservé.',
            ),
            const SizedBox(height: AppSpacing.lg),
            TextField(
              controller: controller,
              autocorrect: false,
              enableSuggestions: false,
              keyboardType: TextInputType.url,
              decoration: const InputDecoration(hintText: '192.168.1.20:8787'),
            ),
          ],
        ),
        actions: <Widget>[
          TextButton(
            onPressed: () => Navigator.of(context).pop(),
            child: const Text('Annuler'),
          ),
          FilledButton(
            onPressed: () => Navigator.of(context).pop(controller.text.trim()),
            child: const Text('Enregistrer'),
          ),
        ],
      ),
    );
    controller.dispose();
    return result == null || result.isEmpty ? null : result;
  }

  Future<void> _unpair() async {
    final bool confirmed = await confirmAction(
      context,
      title: 'Dissocier ce téléphone',
      message: 'Le jeton enregistré sur ce téléphone sera effacé. Vous devrez '
          'refaire un appairage avec un nouveau code du Bridge pour accéder '
          'de nouveau aux données de trading.',
      confirmLabel: 'Dissocier',
      destructive: true,
    );
    if (!confirmed || !mounted) return;
    setState(() => _busy = true);
    await ref.read(connectionProvider.notifier).unpair();
    if (!mounted) return;
    context.go(Routes.pairing);
  }

  @override
  Widget build(BuildContext context) {
    final BridgeConnectionState connection = ref.watch(connectionProvider);
    final Map<String, dynamic> bridge = Json.map(widget.payload['bridge']);
    final Map<String, dynamic> tunnel = Json.map(widget.payload['tunnel']);

    final String? publicUrl =
        Json.text(tunnel['publicUrl']) ?? Json.text(bridge['publicUrl']);
    final String? tunnelError = Json.text(tunnel['error']);

    return ConnectionBlock(
      title: 'Bridge',
      icon: Icons.dns_outlined,
      connected: connection.online,
      stateLabel: connection.online ? 'Connecté' : 'Injoignable',
      subtitle: 'Le Bridge tourne sur l\'ordinateur qui héberge MetaTrader 5.',
      errorMessage: tunnelError,
      rows: <Widget>[
        DetailRow(label: 'Adresse utilisée', value: connection.baseUrl ?? '--'),
        DetailRow(
          label: 'Adresse publique',
          value: publicUrl ?? 'Aucune (réseau local uniquement)',
        ),
        if (connection.fallbackUrl != null)
          DetailRow(label: 'Adresse de repli', value: connection.fallbackUrl!),
        DetailRow(
          label: 'Latence du dernier test',
          value: _latencyMs == null ? '--' : '$_latencyMs ms',
          monospace: true,
        ),
        DetailRow(label: 'Version du Bridge', value: Json.text(bridge['version']) ?? '--'),
      ],
      actions: <Widget>[
        ConnectionAction(
          label: 'Tester',
          icon: Icons.wifi_tethering,
          busy: _testing,
          onPressed: _busy ? null : () => _test(connection.baseUrl),
        ),
        ConnectionAction(
          label: 'Changer d\'adresse',
          icon: Icons.edit_outlined,
          busy: _busy,
          onPressed: () => _changeAddress(connection.baseUrl),
        ),
        ConnectionAction(
          label: 'Dissocier ce téléphone',
          icon: Icons.link_off,
          destructive: true,
          busy: _busy,
          onPressed: _unpair,
        ),
      ],
    );
  }
}
