import 'package:flutter/material.dart';

import '../../../core/theme/app_colors.dart';
import '../../../core/theme/app_theme.dart';
import '../../../core/utils/formatters.dart';
import '../../../core/widgets/app_widgets.dart';
import '../models/json_read.dart';
import '../models/signal.dart';
import 'signal_detail_sections.dart';

/// 6. Résultat : positions issues du signal.
class ResultSection extends StatelessWidget {
  const ResultSection({super.key, required this.trades});

  final List<SignalTrade> trades;

  @override
  Widget build(BuildContext context) {
    return DetailSection(
      title: 'Résultat',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          if (trades.isEmpty)
            Text(
              'Aucune position ouverte depuis ce signal.',
              style: Theme.of(context).textTheme.bodySmall,
            )
          else
            for (int index = 0; index < trades.length; index++) ...<Widget>[
              if (index > 0) const Divider(height: AppSpacing.xl),
              _TradeBlock(trade: trades[index]),
            ],
        ],
      ),
    );
  }
}

class _TradeBlock extends StatelessWidget {
  const _TradeBlock({required this.trade});

  final SignalTrade trade;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        Row(
          children: <Widget>[
            Expanded(
              child: Text(
                '${trade.symbol ?? '--'} · ticket ${trade.ticket ?? '--'}',
                style: Theme.of(context).textTheme.bodyMedium?.copyWith(fontWeight: FontWeight.w600),
              ),
            ),
            if (trade.direction != null) StatusChip.direction(trade.direction),
          ],
        ),
        const SizedBox(height: AppSpacing.sm),
        DetailRow(label: 'État', value: trade.state ?? '--'),
        DetailRow(label: 'Volume', value: Fmt.lots(trade.volume), monospace: true),
        DetailRow(label: 'Prix d\'entrée', value: Fmt.price(trade.openPrice), monospace: true),
        DetailRow(label: 'Prix de sortie', value: Fmt.price(trade.closePrice), monospace: true),
        DetailRow(label: 'Stop loss', value: Fmt.price(trade.stopLoss), monospace: true),
        DetailRow(label: 'Take profit', value: Fmt.price(trade.takeProfit), monospace: true),
        DetailRow(
          label: 'P&L',
          value: Fmt.signedMoney(trade.realizedPnl ?? trade.profit),
          valueColor: AppColors.forAmount(
            trade.realizedPnl ?? trade.profit ?? 0,
            dark: Theme.of(context).brightness == Brightness.dark,
          ),
          monospace: true,
        ),
        DetailRow(
          label: 'Multiple de R',
          value: trade.rMultiple == null ? '--' : '${formatDecimal(trade.rMultiple)} R',
          monospace: true,
        ),
        DetailRow(label: 'Ouverte le', value: Fmt.full(trade.openedAt)),
        if (trade.closedAt != null) DetailRow(label: 'Fermée le', value: Fmt.full(trade.closedAt)),
        if (trade.closeReason != null)
          DetailRow(label: 'Motif de fermeture', value: trade.closeReason!),
      ],
    );
  }
}

/// Messages de suivi rattachés au signal (modification, fermeture partielle…).
class FollowUpsSection extends StatelessWidget {
  const FollowUpsSection({super.key, required this.followUps});

  final List<Signal> followUps;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    return DetailSection(
      title: 'Messages de suivi',
      subtitle: 'Messages du canal rattachés à ce signal.',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          if (followUps.isEmpty)
            Text('Aucun message de suivi.', style: theme.textTheme.bodySmall)
          else
            for (final Signal followUp in followUps) ...<Widget>[
              DetailRow(
                label: Fmt.dayTime(followUp.receivedAt),
                value: followUp.followUpAction ?? Fmt.signalStatus(followUp.status),
              ),
              if (followUp.rawText != null)
                Padding(
                  padding: const EdgeInsets.only(bottom: AppSpacing.sm),
                  child: Text(
                    followUp.rawText!,
                    style: theme.textTheme.bodySmall?.copyWith(fontFamily: 'monospace'),
                  ),
                ),
            ],
        ],
      ),
    );
  }
}

/// Traces d'audit conservées par le Bridge.
class AuditSection extends StatelessWidget {
  const AuditSection({super.key, required this.audit});

  final List<SignalAuditEntry> audit;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    return DetailSection(
      title: 'Traces d\'audit',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          if (audit.isEmpty)
            Text('Aucune trace enregistrée.', style: theme.textTheme.bodySmall)
          else
            for (final SignalAuditEntry entry in audit) ...<Widget>[
              DetailRow(
                label: Fmt.dayTime(entry.createdAt),
                value: '${entry.action ?? '--'} · ${entry.actor ?? '--'}',
              ),
              if (entry.details != null)
                Padding(
                  padding: const EdgeInsets.only(bottom: AppSpacing.sm),
                  child: Text(
                    entry.details!.entries
                        .map((MapEntry<String, dynamic> e) => '${e.key} : ${e.value}')
                        .join('\n'),
                    style: theme.textTheme.bodySmall?.copyWith(fontFamily: 'monospace'),
                  ),
                ),
            ],
        ],
      ),
    );
  }
}
