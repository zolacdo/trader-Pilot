import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_exception.dart';
import '../../../core/api/endpoints.dart';
import '../../../core/connection/connection_controller.dart';
import '../../../core/providers/bridge_data.dart';
import '../../../core/widgets/app_widgets.dart';
import '../models/bridge_json.dart';
import '../models/bridge_labels.dart';
import 'connection_block.dart';

/// Liaison OpenRouter : clé masquée et modèles gratuits réellement actifs.
class OpenRouterConnectionCard extends ConsumerStatefulWidget {
  const OpenRouterConnectionCard({super.key, required this.payload});

  final Map<String, dynamic> payload;

  @override
  ConsumerState<OpenRouterConnectionCard> createState() => _OpenRouterConnectionCardState();
}

class _OpenRouterConnectionCardState extends ConsumerState<OpenRouterConnectionCard> {
  bool _busy = false;

  Future<void> _test() async {
    if (_busy) return;
    setState(() => _busy = true);
    try {
      final Map<String, dynamic> result =
          await ref.read(apiClientProvider).postJson(Endpoints.openrouterTest);
      if (!mounted) return;
      final bool ok = Json.flag(result['ok']);
      final int? latency = Json.integer(result['latencyMs']);
      showToast(
        context,
        ok
            ? 'Modèle ${Json.text(result['model']) ?? 'inconnu'} joignable'
                '${latency == null ? '' : ' en $latency ms'}.'
            : Json.text(result['error']) ?? 'Le test a échoué.',
        error: !ok,
      );
    } on ApiException catch (error) {
      if (!mounted) return;
      showToast(context, error.message, error: true);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
    if (mounted) refreshBridgeData(ref);
  }

  @override
  Widget build(BuildContext context) {
    final Map<String, dynamic> openrouter = Json.map(widget.payload['openrouter']);
    final String? state = Json.text(openrouter['state']);
    final bool configured = Json.flag(openrouter['configured']);

    return ConnectionBlock(
      title: 'OpenRouter',
      icon: Icons.auto_awesome_outlined,
      connected: Json.flag(openrouter['textModelOk']),
      stateLabel: BridgeLabels.connection(state),
      subtitle: 'Analyse des signaux par IA. Seuls des modèles gratuits sont utilisés.',
      errorMessage: Json.text(openrouter['lastError']),
      rows: <Widget>[
        DetailRow(
          label: 'Clé API',
          value: configured ? (Json.text(openrouter['apiKeyHint']) ?? 'Enregistrée') : 'Aucune clé',
          monospace: configured,
        ),
        DetailRow(label: 'Modèle texte', value: Json.text(openrouter['textModel']) ?? '--'),
        DetailRow(label: 'Modèle vision', value: Json.text(openrouter['visionModel']) ?? '--'),
        DetailRow(
          label: 'Sélection',
          value: Json.flag(openrouter['autoMode']) ? 'Automatique' : 'Manuelle',
        ),
      ],
      actions: <Widget>[
        ConnectionAction(
          label: 'Tester',
          icon: Icons.play_circle_outline,
          busy: _busy,
          onPressed: configured ? _test : null,
        ),
      ],
    );
  }
}
