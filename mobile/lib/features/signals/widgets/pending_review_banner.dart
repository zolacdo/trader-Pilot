import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/routing/app_router.dart';
import '../../../core/theme/app_colors.dart';
import '../../../core/theme/app_theme.dart';
import '../../../core/utils/formatters.dart';
import '../../../core/widgets/app_widgets.dart';
import '../models/signal.dart';
import '../providers/signals_providers.dart';
import 'signal_card.dart';
import 'signal_decision.dart';

/// Bandeau des signaux en attente de validation manuelle (CDC section 51).
class PendingReviewBanner extends ConsumerWidget {
  const PendingReviewBanner({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final List<Signal> pending =
        ref.watch(pendingSignalsProvider).valueOrNull ?? const <Signal>[];
    if (pending.isEmpty) return const SizedBox.shrink();

    final ThemeData theme = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.fromLTRB(AppSpacing.lg, 0, AppSpacing.lg, AppSpacing.md),
      child: AppCard(
        accent: true,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: <Widget>[
            Row(
              children: <Widget>[
                const Icon(Icons.pending_actions_outlined, size: 18, color: AppColors.primary),
                const SizedBox(width: AppSpacing.sm),
                Expanded(
                  child: Text(
                    pending.length == 1
                        ? '1 signal attend votre validation'
                        : '${pending.length} signaux attendent votre validation',
                    style: theme.textTheme.titleMedium,
                  ),
                ),
              ],
            ),
            const SizedBox(height: AppSpacing.xs),
            Text(
              'Passé le délai indiqué, le signal devient invalide et n\'est plus exécutable.',
              style: theme.textTheme.bodySmall,
            ),
            for (final Signal signal in pending) ...<Widget>[
              const SizedBox(height: AppSpacing.md),
              const Divider(),
              const SizedBox(height: AppSpacing.md),
              _PendingRow(signal: signal),
            ],
          ],
        ),
      ),
    );
  }
}

class _PendingRow extends ConsumerWidget {
  const _PendingRow({required this.signal});

  final Signal signal;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final ThemeData theme = Theme.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        InkWell(
          onTap: () => context.push(Routes.signalDetail(signal.id)),
          borderRadius: BorderRadius.circular(AppSpacing.radiusSmall),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: <Widget>[
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
                  ExpiryCountdown(expiresAt: signal.expiresAt),
                ],
              ),
              const SizedBox(height: AppSpacing.sm),
              DetailRow(label: 'Entrée', value: signalEntryText(signal), monospace: true),
              DetailRow(label: 'Stop loss', value: Fmt.price(signal.stopLoss), monospace: true),
              DetailRow(
                label: 'Take profit',
                value: signalTakeProfitsText(signal),
                monospace: true,
              ),
              DetailRow(label: 'Lot calculé', value: Fmt.lots(signal.computedLot), monospace: true),
              DetailRow(label: 'Risque estimé', value: Fmt.money(signal.riskAmount), monospace: true),
            ],
          ),
        ),
        const SizedBox(height: AppSpacing.md),
        SignalDecisionButtons(signal: signal, dense: true),
      ],
    );
  }
}

/// Compte à rebours jusqu'à l'expiration du délai de validation.
class ExpiryCountdown extends ConsumerWidget {
  const ExpiryCountdown({super.key, required this.expiresAt});

  final DateTime? expiresAt;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    if (expiresAt == null) {
      return const StatusChip(label: 'Sans délai', dense: true);
    }
    // L'horloge partagée rythme l'affichage sans stocker d'état local.
    ref.watch(tickProvider);
    final Duration remaining = expiresAt!.difference(DateTime.now());
    if (remaining.isNegative) {
      return const StatusChip(
        label: 'Délai dépassé — invalide',
        tone: StatusTone.bad,
        icon: Icons.timer_off_outlined,
        dense: true,
      );
    }
    return StatusChip(
      label: _format(remaining),
      tone: remaining.inMinutes < 2 ? StatusTone.warning : StatusTone.accent,
      icon: Icons.timer_outlined,
      dense: true,
    );
  }

  static String _format(Duration remaining) {
    if (remaining.inHours >= 1) {
      final int minutes = remaining.inMinutes.remainder(60);
      return '${remaining.inHours} h ${minutes.toString().padLeft(2, '0')}';
    }
    final int minutes = remaining.inMinutes;
    final int seconds = remaining.inSeconds.remainder(60);
    return '$minutes:${seconds.toString().padLeft(2, '0')}';
  }
}
