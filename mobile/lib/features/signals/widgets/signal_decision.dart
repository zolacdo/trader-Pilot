import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_exception.dart';
import '../../../core/theme/app_colors.dart';
import '../../../core/theme/app_theme.dart';
import '../../../core/utils/formatters.dart';
import '../../../core/widgets/app_widgets.dart';
import '../models/json_read.dart';
import '../models/signal.dart';
import '../providers/signals_providers.dart';

/// Motifs de refus proposés, l'utilisateur peut toujours écrire le sien.
const List<String> _presetReasons = <String>[
  'Signal peu clair',
  'Instrument non souhaité',
  'Risque trop élevé',
  'Prix déjà dépassé',
  'Contexte de marché défavorable',
];

/// Rappel du lot et du risque avant confirmation (CDC section 51).
String _riskRecap(Signal signal) {
  final StringBuffer buffer = StringBuffer()
    ..writeln('${signal.displaySymbol ?? '--'} · ${signal.direction ?? '--'}')
    ..writeln('Entrée : ${_entryText(signal)}')
    ..writeln('Stop loss : ${Fmt.price(signal.stopLoss)}')
    ..writeln(
      'Take profit : ${signal.takeProfits.isEmpty ? '--' : signal.takeProfits.map(Fmt.price).join(' / ')}',
    )
    ..writeln('Lot calculé : ${Fmt.lots(signal.computedLot)}')
    ..writeln('Risque estimé : ${Fmt.money(signal.riskAmount)}');
  return buffer.toString().trimRight();
}

String _entryText(Signal signal) {
  if (signal.entryPrice != null) return Fmt.price(signal.entryPrice);
  if (signal.entryMin != null || signal.entryMax != null) {
    return '${Fmt.price(signal.entryMin)} – ${Fmt.price(signal.entryMax)}';
  }
  return '--';
}

/// Exécute un signal en attente après confirmation explicite.
Future<void> approveSignal(BuildContext context, WidgetRef ref, Signal signal) async {
  if (signal.expired) {
    showToast(context, 'Délai de validation dépassé : ce signal n\'est plus exécutable.',
        error: true);
    return;
  }
  final bool confirmed = await confirmAction(
    context,
    title: 'Exécuter ce signal ?',
    message: '${_riskRecap(signal)}\n\n'
        'Le Bridge applique toutes les protections avant d\'envoyer l\'ordre.',
    confirmLabel: 'EXÉCUTER',
  );
  if (!confirmed || !context.mounted) return;

  try {
    final Map<String, dynamic> outcome = await ref.read(signalActionsProvider).approve(signal.id);
    if (!context.mounted) return;
    _reportOutcome(context, outcome);
  } on ApiException catch (error) {
    if (!context.mounted) return;
    showToast(context, error.message, error: true);
  }
}

/// Refuse un signal en attente, avec un motif conservé dans l'historique.
Future<void> rejectSignal(BuildContext context, WidgetRef ref, Signal signal) async {
  final String? reason = await _askReason(context);
  if (reason == null || !context.mounted) return;

  try {
    await ref.read(signalActionsProvider).reject(signal.id, reason);
    if (!context.mounted) return;
    showToast(context, 'Signal refusé. Aucun ordre n\'a été envoyé.');
  } on ApiException catch (error) {
    if (!context.mounted) return;
    showToast(context, error.message, error: true);
  }
}

/// Traduit la réponse du moteur de trading en message compréhensible.
void _reportOutcome(BuildContext context, Map<String, dynamic> outcome) {
  final bool executed = readBool(outcome['executed']);
  final bool rejected = readBool(outcome['rejected']);
  final String? reason = readText(outcome['reason']);
  final String? detail = readText(outcome['detail']);

  if (executed) {
    showToast(context, detail ?? 'Ordre envoyé au broker.');
    return;
  }
  if (rejected) {
    showToast(
      context,
      'Non exécuté : ${Fmt.rejectionReason(reason)}${detail == null ? '' : ' — $detail'}',
      error: true,
    );
    return;
  }
  showToast(context, detail ?? 'Décision enregistrée par le Bridge.');
}

/// Demande le motif du refus : choix rapide ou texte libre.
Future<String?> _askReason(BuildContext context) async {
  final TextEditingController controller = TextEditingController();
  final String? reason = await showDialog<String>(
    context: context,
    builder: (BuildContext dialogContext) {
      return StatefulBuilder(
        builder: (BuildContext context, StateSetter setState) {
          final bool ready = controller.text.trim().isNotEmpty;
          return AlertDialog(
            title: const Text('Refuser ce signal'),
            content: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: <Widget>[
                Text(
                  'Le motif est conservé dans l\'historique du signal. '
                  'Aucun ordre ne sera envoyé.',
                  style: Theme.of(context).textTheme.bodySmall,
                ),
                const SizedBox(height: AppSpacing.md),
                Wrap(
                  spacing: AppSpacing.sm,
                  runSpacing: AppSpacing.sm,
                  children: <Widget>[
                    for (final String preset in _presetReasons)
                      ActionChip(
                        label: Text(preset),
                        onPressed: () => setState(() {
                          controller.text = preset;
                        }),
                      ),
                  ],
                ),
                const SizedBox(height: AppSpacing.md),
                TextField(
                  controller: controller,
                  maxLength: 255,
                  minLines: 1,
                  maxLines: 3,
                  onChanged: (_) => setState(() {}),
                  decoration: const InputDecoration(hintText: 'Motif du refus'),
                ),
              ],
            ),
            actions: <Widget>[
              TextButton(
                onPressed: () => Navigator.of(dialogContext).pop(),
                style: TextButton.styleFrom(foregroundColor: AppColors.textSecondary),
                child: const Text('Annuler'),
              ),
              FilledButton(
                onPressed:
                    ready ? () => Navigator.of(dialogContext).pop(controller.text.trim()) : null,
                style: FilledButton.styleFrom(backgroundColor: AppColors.loss),
                child: const Text('REFUSER'),
              ),
            ],
          );
        },
      );
    },
  );
  controller.dispose();
  return reason;
}

/// Paire de boutons REFUSER / EXÉCUTER utilisée dans la liste et le détail.
class SignalDecisionButtons extends ConsumerWidget {
  const SignalDecisionButtons({super.key, required this.signal, this.dense = false});

  final Signal signal;
  final bool dense;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    if (signal.expired) {
      return Row(
        children: <Widget>[
          const Icon(Icons.timer_off_outlined, size: 16, color: AppColors.warning),
          const SizedBox(width: AppSpacing.sm),
          Expanded(
            child: Text(
              'Délai dépassé : signal invalide, plus aucune exécution possible.',
              style: Theme.of(context)
                  .textTheme
                  .bodySmall
                  ?.copyWith(color: AppColors.warning, fontWeight: FontWeight.w600),
            ),
          ),
        ],
      );
    }

    final Size minimum = Size(0, dense ? 40 : 48);
    return Row(
      children: <Widget>[
        Expanded(
          child: OutlinedButton(
            onPressed: () => rejectSignal(context, ref, signal),
            style: OutlinedButton.styleFrom(
              foregroundColor: AppColors.loss,
              minimumSize: minimum,
              side: const BorderSide(color: AppColors.loss),
            ),
            child: const Text('REFUSER'),
          ),
        ),
        const SizedBox(width: AppSpacing.md),
        Expanded(
          child: FilledButton(
            onPressed: () => approveSignal(context, ref, signal),
            style: FilledButton.styleFrom(minimumSize: minimum),
            child: const Text('EXÉCUTER'),
          ),
        ),
      ],
    );
  }
}
