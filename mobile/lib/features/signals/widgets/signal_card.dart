import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/routing/app_router.dart';
import '../../../core/theme/app_colors.dart';
import '../../../core/theme/app_theme.dart';
import '../../../core/utils/formatters.dart';
import '../../../core/widgets/app_widgets.dart';
import '../models/signal.dart';
import 'signal_decision.dart';

/// Pastille d'état d'un signal : le vert et le rouge gardent leur sens.
StatusChip signalStatusChip(String status) {
  final StatusTone tone = switch (status) {
    'SENT' || 'OPEN' || 'CLOSED' || 'PARTIALLY_CLOSED' || 'APPROVED' || 'ORDER_CHECKED' =>
      StatusTone.good,
    'REJECTED' || 'FAILED' => StatusTone.bad,
    'NEEDS_REVIEW' || 'EXPIRED' => StatusTone.warning,
    'OBSERVED' => StatusTone.accent,
    _ => StatusTone.neutral,
  };
  return StatusChip(label: Fmt.signalStatus(status), tone: tone, dense: true);
}

/// Zone d'entrée : prix unique ou fourchette, `--` si le parser n'a rien lu.
String signalEntryText(Signal signal) {
  if (signal.entryPrice != null) return Fmt.price(signal.entryPrice);
  if (signal.entryMin != null || signal.entryMax != null) {
    return '${Fmt.price(signal.entryMin)} – ${Fmt.price(signal.entryMax)}';
  }
  return '--';
}

String signalTakeProfitsText(Signal signal) =>
    signal.takeProfits.isEmpty ? '--' : signal.takeProfits.map(Fmt.price).join(' / ');

/// Carte de signal de la liste (CDC section 33).
class SignalCard extends ConsumerWidget {
  const SignalCard({super.key, required this.signal, this.channelTitle, this.showDecision = false});

  final Signal signal;

  /// Titre du canal quand il a pu être résolu, sinon `--`.
  final String? channelTitle;

  /// Affiche REFUSER / EXÉCUTER pour un signal en attente de validation.
  final bool showDecision;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final ThemeData theme = Theme.of(context);
    return AppCard(
      accent: signal.needsReview && !signal.expired,
      onTap: () => context.push(Routes.signalDetail(signal.id)),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Row(
            children: <Widget>[
              Expanded(
                child: Text(
                  channelTitle ?? '--',
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: theme.textTheme.bodySmall,
                ),
              ),
              const SizedBox(width: AppSpacing.sm),
              Text(Fmt.dayTime(signal.receivedAt), style: theme.textTheme.bodySmall),
            ],
          ),
          const SizedBox(height: AppSpacing.sm),
          Row(
            children: <Widget>[
              Flexible(
                child: Text(
                  signal.displaySymbol ?? '--',
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: theme.textTheme.titleMedium?.copyWith(fontSize: 16),
                ),
              ),
              if (signal.direction != null) ...<Widget>[
                const SizedBox(width: AppSpacing.sm),
                StatusChip.direction(signal.direction),
              ],
              const Spacer(),
              signalStatusChip(signal.status),
            ],
          ),
          const SizedBox(height: AppSpacing.md),
          Wrap(
            spacing: AppSpacing.lg,
            runSpacing: AppSpacing.sm,
            children: <Widget>[
              _Metric(label: 'Entrée', value: signalEntryText(signal)),
              _Metric(label: 'SL', value: Fmt.price(signal.stopLoss)),
              _Metric(label: 'TP', value: signalTakeProfitsText(signal)),
              _Metric(label: 'Confiance', value: Fmt.confidence(signal.confidence)),
            ],
          ),
          if (signal.rejectionReason != null) ...<Widget>[
            const SizedBox(height: AppSpacing.md),
            _RejectionNote(signal: signal),
          ],
          if (showDecision) ...<Widget>[
            const SizedBox(height: AppSpacing.md),
            SignalDecisionButtons(signal: signal, dense: true),
          ],
        ],
      ),
    );
  }
}

class _Metric extends StatelessWidget {
  const _Metric({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: <Widget>[
        Text(label.toUpperCase(), style: theme.textTheme.labelSmall),
        const SizedBox(height: 2),
        Text(
          value,
          style: theme.textTheme.bodyMedium?.copyWith(
            fontWeight: FontWeight.w600,
            fontFeatures: const <FontFeature>[FontFeature.tabularFigures()],
          ),
        ),
      ],
    );
  }
}

/// Motif de refus : affiché systématiquement quand le Bridge en a fourni un.
class _RejectionNote extends StatelessWidget {
  const _RejectionNote({required this.signal});

  final Signal signal;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    final bool dark = theme.brightness == Brightness.dark;
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.symmetric(horizontal: AppSpacing.md, vertical: AppSpacing.sm),
      decoration: BoxDecoration(
        color: dark ? AppColors.loss.withValues(alpha: 0.12) : AppColors.lossSurface,
        borderRadius: BorderRadius.circular(AppSpacing.radiusSmall),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Text(
            'Motif : ${Fmt.rejectionReason(signal.rejectionReason)}',
            style: theme.textTheme.bodySmall?.copyWith(
              color: dark ? const Color(0xFFF87171) : AppColors.loss,
              fontWeight: FontWeight.w600,
            ),
          ),
          if (signal.rejectionDetail != null) ...<Widget>[
            const SizedBox(height: 2),
            Text(signal.rejectionDetail!, style: theme.textTheme.bodySmall),
          ],
        ],
      ),
    );
  }
}
