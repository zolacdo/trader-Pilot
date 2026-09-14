import 'package:flutter/material.dart';

import '../../../core/theme/app_colors.dart';
import '../../../core/theme/app_theme.dart';
import '../../../core/utils/formatters.dart';
import '../../../core/widgets/app_widgets.dart';
import '../models/json_read.dart';
import '../models/signal.dart';
import 'signal_card.dart';

/// Libellé français de la source d'interprétation.
String parserSourceLabel(String? source, String? aiModel) {
  final String base = switch (source) {
    'deterministic' => 'Parser local (déterministe)',
    'template' => 'Modèle appris du canal',
    'ai' => 'Intelligence artificielle',
    'manual' => 'Saisie manuelle',
    _ => source ?? '--',
  };
  if (source == 'ai' && aiModel != null) return '$base · $aiModel';
  return base;
}

/// Libellé français d'un type d'ordre MetaTrader.
String orderTypeLabel(String? code) {
  return switch (code) {
    'MARKET' => 'Ordre au marché',
    'BUY_LIMIT' => 'Achat limite',
    'SELL_LIMIT' => 'Vente limite',
    'BUY_STOP' => 'Achat stop',
    'SELL_STOP' => 'Vente stop',
    'BUY_STOP_LIMIT' => 'Achat stop limite',
    'SELL_STOP_LIMIT' => 'Vente stop limite',
    _ => code ?? '--',
  };
}

/// Carte de section avec titre, utilisée par tout le détail du signal.
class DetailSection extends StatelessWidget {
  const DetailSection({super.key, required this.title, required this.child, this.subtitle});

  final String title;
  final String? subtitle;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: AppSpacing.md),
      child: AppCard(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: <Widget>[
            SectionHeader(title: title, subtitle: subtitle),
            child,
          ],
        ),
      ),
    );
  }
}

/// 1. Message Telegram original, tel qu'il a été reçu.
class RawMessageSection extends StatelessWidget {
  const RawMessageSection({super.key, required this.signal});

  final Signal signal;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    final bool dark = theme.brightness == Brightness.dark;
    return DetailSection(
      title: 'Message Telegram original',
      subtitle: signal.channelTitle == null
          ? 'Reçu le ${Fmt.full(signal.receivedAt)}'
          : '${signal.channelTitle} · reçu le ${Fmt.full(signal.receivedAt)}',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Container(
            width: double.infinity,
            padding: const EdgeInsets.all(AppSpacing.md),
            decoration: BoxDecoration(
              color: dark ? AppColors.surfaceMutedDark : AppColors.surfaceMuted,
              borderRadius: BorderRadius.circular(AppSpacing.radiusSmall),
              border: Border.all(color: theme.colorScheme.outline),
            ),
            child: SelectableText(
              signal.rawText ?? '--',
              style: theme.textTheme.bodyMedium?.copyWith(fontFamily: 'monospace', height: 1.5),
            ),
          ),
          if (signal.telegramMessageId != null) ...<Widget>[
            const SizedBox(height: AppSpacing.sm),
            Text(
              'Message Telegram n° ${signal.telegramMessageId}'
              '${signal.messageDate == null ? '' : ' · publié le ${Fmt.full(signal.messageDate)}'}',
              style: theme.textTheme.bodySmall,
            ),
          ],
        ],
      ),
    );
  }
}

/// 2. Interprétation produite par le parser.
class InterpretationSection extends StatelessWidget {
  const InterpretationSection({super.key, required this.signal});

  final Signal signal;

  @override
  Widget build(BuildContext context) {
    return DetailSection(
      title: 'Interprétation',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          DetailRow(label: 'Instrument lu', value: signal.symbol ?? '--'),
          DetailRow(label: 'Instrument normalisé', value: signal.normalizedSymbol ?? '--'),
          DetailRow(label: 'Instrument broker', value: signal.brokerSymbol ?? '--'),
          Row(
            children: <Widget>[
              Expanded(
                child: Text('Direction', style: Theme.of(context).textTheme.bodySmall),
              ),
              if (signal.direction == null)
                const Text('--')
              else
                StatusChip.direction(signal.direction),
            ],
          ),
          const SizedBox(height: AppSpacing.sm),
          DetailRow(label: 'Type d\'ordre', value: orderTypeLabel(signal.orderType)),
          DetailRow(label: 'Entrée', value: signalEntryText(signal), monospace: true),
          DetailRow(label: 'Stop loss', value: Fmt.price(signal.stopLoss), monospace: true),
          DetailRow(
            label: 'Take profit',
            value: signalTakeProfitsText(signal),
            monospace: true,
          ),
          DetailRow(label: 'Score de confiance', value: Fmt.confidence(signal.confidence)),
          DetailRow(
            label: 'Interprété par',
            value: parserSourceLabel(signal.parserSource, signal.aiModel),
          ),
        ],
      ),
    );
  }
}

/// 3. Validation du signal.
class ValidationSection extends StatelessWidget {
  const ValidationSection({super.key, required this.signal});

  final Signal signal;

  @override
  Widget build(BuildContext context) {
    return DetailSection(
      title: 'Validation',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Row(
            children: <Widget>[
              Expanded(child: Text('Statut', style: Theme.of(context).textTheme.bodySmall)),
              signalStatusChip(signal.status),
            ],
          ),
          const SizedBox(height: AppSpacing.sm),
          if (signal.expiresAt != null)
            DetailRow(
              label: 'Délai de validation',
              value: signal.expired
                  ? 'Dépassé le ${Fmt.full(signal.expiresAt)} — signal invalide'
                  : 'Jusqu\'au ${Fmt.full(signal.expiresAt)}',
              valueColor: signal.expired ? AppColors.warning : null,
            ),
          if (signal.rejectionReason != null)
            DetailRow(
              label: 'Motif de refus',
              value: Fmt.rejectionReason(signal.rejectionReason),
              valueColor: AppColors.loss,
            ),
          if (signal.rejectionDetail != null)
            DetailRow(label: 'Détail', value: signal.rejectionDetail!),
        ],
      ),
    );
  }
}

/// 4. Calcul du risque appliqué par le Bridge.
class RiskSection extends StatelessWidget {
  const RiskSection({super.key, required this.signal});

  final Signal signal;

  @override
  Widget build(BuildContext context) {
    return DetailSection(
      title: 'Calcul du risque',
      subtitle: 'Valeurs calculées par le Bridge, aucune estimation locale.',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          DetailRow(label: 'Lot calculé', value: Fmt.lots(signal.computedLot), monospace: true),
          DetailRow(label: 'Montant risqué', value: Fmt.money(signal.riskAmount), monospace: true),
          DetailRow(
            label: 'Ratio rendement / risque',
            value: signal.riskReward == null ? '--' : '${formatDecimal(signal.riskReward)} R',
            monospace: true,
          ),
        ],
      ),
    );
  }
}

/// 5. Ordre MT5 : mode d'exécution et ordres en attente.
class OrderSection extends StatelessWidget {
  const OrderSection({super.key, required this.signal, required this.pendingOrders});

  final Signal signal;
  final List<SignalPendingOrder> pendingOrders;

  @override
  Widget build(BuildContext context) {
    return DetailSection(
      title: 'Ordre MetaTrader 5',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          DetailRow(
            label: 'Mode d\'exécution',
            value: Fmt.executionMode(signal.executionMode),
          ),
          if (pendingOrders.isEmpty)
            Text(
              'Aucun ordre en attente rattaché à ce signal.',
              style: Theme.of(context).textTheme.bodySmall,
            )
          else
            for (final SignalPendingOrder order in pendingOrders) ...<Widget>[
              const Divider(height: AppSpacing.xl),
              DetailRow(label: 'Ticket', value: order.ticket?.toString() ?? '--'),
              DetailRow(label: 'Type', value: orderTypeLabel(order.orderType)),
              DetailRow(label: 'Prix', value: Fmt.price(order.price), monospace: true),
              DetailRow(label: 'Volume', value: Fmt.lots(order.volume), monospace: true),
              DetailRow(label: 'État', value: order.state ?? '--'),
            ],
        ],
      ),
    );
  }
}
