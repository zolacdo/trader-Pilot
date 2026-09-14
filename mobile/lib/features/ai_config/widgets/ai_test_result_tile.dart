import 'package:flutter/material.dart';

import '../../../core/theme/app_theme.dart';
import '../../../core/utils/formatters.dart';
import '../../../core/widgets/app_widgets.dart';
import '../ai_config_providers.dart';
import '../ai_labels.dart';
import '../models/ai_status.dart';

/// Résultat du dernier test de connexion : réussite, latence, message d'échec.
///
/// En cas d'échec, le message du Bridge est repris mot pour mot : c'est lui qui
/// sait pourquoi le serveur ne répond pas.
class AiTestResultTile extends StatelessWidget {
  const AiTestResultTile({super.key, required this.state});

  final AiTestState state;

  @override
  Widget build(BuildContext context) {
    final AiTestResult? result = state.result;
    if (result == null) return const SizedBox.shrink();

    final ThemeData theme = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.only(top: AppSpacing.md),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Wrap(
            spacing: AppSpacing.sm,
            runSpacing: AppSpacing.sm,
            crossAxisAlignment: WrapCrossAlignment.center,
            children: <Widget>[
              StatusChip(
                label: result.ok ? 'Connexion établie' : 'Échec',
                tone: result.ok ? StatusTone.good : StatusTone.bad,
                icon: result.ok ? Icons.check_circle_outline : Icons.error_outline,
                dense: true,
              ),
              if (result.latencyMs != null)
                StatusChip(
                  label: 'Latence ${AiLabels.latency(result.latencyMs)}',
                  dense: true,
                ),
              if (result.at != null)
                Text('à ${Fmt.time(result.at)}', style: theme.textTheme.bodySmall),
            ],
          ),
          if (result.model != null) ...<Widget>[
            const SizedBox(height: AppSpacing.xs),
            Text('Modèle interrogé : ${result.model}', style: theme.textTheme.bodySmall),
          ],
          if (result.error != null) ...<Widget>[
            const SizedBox(height: AppSpacing.xs),
            Text(result.error!, style: theme.textTheme.bodySmall),
          ],
        ],
      ),
    );
  }
}
