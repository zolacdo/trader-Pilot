import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_exception.dart';
import '../../../core/providers/bridge_data.dart';
import '../../../core/theme/app_theme.dart';
import '../../../core/utils/formatters.dart';
import '../../../core/widgets/app_widgets.dart';
import '../trades_models.dart';
import '../trades_providers.dart';
import 'position_dialogs.dart';

/// Menu des actions manuelles disponibles sur une position ouverte.
///
/// Chaque action passe par une confirmation explicite : rien n'est envoyé au
/// broker sur un simple appui (CDC section 35).
Future<void> showPositionActions(
  BuildContext context,
  WidgetRef ref,
  OpenPosition position,
) async {
  final _PositionAction? choice = await showModalBottomSheet<_PositionAction>(
    context: context,
    showDragHandle: true,
    builder: (BuildContext sheetContext) {
      return SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: <Widget>[
            Padding(
              padding: const EdgeInsets.fromLTRB(AppSpacing.lg, 0, AppSpacing.lg, AppSpacing.sm),
              child: Row(
                children: <Widget>[
                  Expanded(
                    child: Text(
                      '${position.symbol} · ticket ${position.ticket}',
                      style: Theme.of(sheetContext).textTheme.titleMedium,
                    ),
                  ),
                  StatusChip.direction(position.direction),
                ],
              ),
            ),
            const Divider(height: 1),
            _actionTile(sheetContext, Icons.close_rounded, 'Fermer entièrement',
                'Réalise immédiatement le résultat de la position.', _PositionAction.closeAll),
            _actionTile(
                sheetContext,
                Icons.pie_chart_outline,
                'Fermer partiellement',
                'Sécurise une partie du volume et laisse courir le reste.',
                _PositionAction.closePartial),
            _actionTile(sheetContext, Icons.shield_outlined, 'Modifier le stop loss',
                'Déplace le niveau de perte maximale acceptée.', _PositionAction.stopLoss),
            _actionTile(sheetContext, Icons.flag_outlined, 'Modifier le take profit',
                'Déplace l\'objectif de sortie en gain.', _PositionAction.takeProfit),
            _actionTile(
                sheetContext,
                Icons.horizontal_rule_rounded,
                'Mettre à break even',
                'Remonte le stop au prix d\'entrée : la position ne peut plus perdre.',
                _PositionAction.breakEven),
            const SizedBox(height: AppSpacing.sm),
          ],
        ),
      );
    },
  );

  if (choice == null || !context.mounted) return;

  switch (choice) {
    case _PositionAction.closeAll:
      await _closeAll(context, ref, position);
    case _PositionAction.closePartial:
      await _closePartial(context, ref, position);
    case _PositionAction.stopLoss:
      await _modifyPrice(context, ref, position, stopLoss: true);
    case _PositionAction.takeProfit:
      await _modifyPrice(context, ref, position, stopLoss: false);
    case _PositionAction.breakEven:
      await _breakEven(context, ref, position);
  }
}

enum _PositionAction { closeAll, closePartial, stopLoss, takeProfit, breakEven }

Widget _actionTile(
  BuildContext context,
  IconData icon,
  String title,
  String subtitle,
  _PositionAction action,
) {
  return ListTile(
    leading: Icon(icon),
    title: Text(title),
    subtitle: Text(subtitle),
    onTap: () => Navigator.of(context).pop(action),
  );
}

// ---------------------------------------------------------------------------
// Fermetures
// ---------------------------------------------------------------------------

Future<void> _closeAll(BuildContext context, WidgetRef ref, OpenPosition position) async {
  final bool ok = await confirmAction(
    context,
    title: 'Fermer la position',
    message: 'La position ${position.symbol} (${Fmt.lots(position.volume)} lot) sera fermée au prix '
        'du marché. Le résultat en cours, ${Fmt.signedMoney(position.profit)}, devient définitif.',
    confirmLabel: 'Fermer',
    destructive: true,
  );
  if (!ok || !context.mounted) return;
  await runTradeAction(
    context,
    ref,
    () => ref.read(tradeActionsProvider).closeFully(position.ticket),
    'Position ${position.ticket} fermée.',
  );
}

Future<void> _closePartial(BuildContext context, WidgetRef ref, OpenPosition position) async {
  final PartialChoice? choice = await showDialog<PartialChoice>(
    context: context,
    builder: (BuildContext dialogContext) => PartialCloseDialog(position: position),
  );
  if (choice == null || !context.mounted) return;

  final String description = choice.percentage != null
      ? '${choice.percentage!.toStringAsFixed(0)} % du volume ouvert'
      : '${Fmt.lots(choice.volume)} lot';
  final bool ok = await confirmAction(
    context,
    title: 'Fermeture partielle',
    message: 'Fermer $description sur ${position.symbol} ? Le reste de la position continue de '
        'courir avec son stop loss et son take profit actuels.',
    confirmLabel: 'Fermer partiellement',
    destructive: true,
  );
  if (!ok || !context.mounted) return;

  await runTradeAction(
    context,
    ref,
    () => choice.percentage != null
        ? ref.read(tradeActionsProvider).closePercentage(position.ticket, choice.percentage!)
        : ref.read(tradeActionsProvider).closeVolume(position.ticket, choice.volume!),
    'Fermeture partielle envoyée.',
  );
}

// ---------------------------------------------------------------------------
// Stop loss, take profit, break even
// ---------------------------------------------------------------------------

Future<void> _modifyPrice(
  BuildContext context,
  WidgetRef ref,
  OpenPosition position, {
  required bool stopLoss,
}) async {
  final String label = stopLoss ? 'stop loss' : 'take profit';
  final double? current = stopLoss ? position.stopLoss : position.takeProfit;
  final double? value = await showDialog<double>(
    context: context,
    builder: (BuildContext dialogContext) => PriceDialog(
      title: 'Modifier le $label',
      helper: stopLoss
          ? 'Niveau auquel la position est coupée en perte. Le broker refuse un stop trop proche '
              'du prix actuel.'
          : 'Niveau auquel la position est fermée en gain.',
      current: current,
      openPrice: position.openPrice,
      currentPrice: position.currentPrice,
    ),
  );
  if (value == null || !context.mounted) return;

  final bool ok = await confirmAction(
    context,
    title: 'Modifier le $label',
    message: 'Le $label de ${position.symbol} passera de ${Fmt.price(current)} à '
        '${Fmt.price(value)}.',
    confirmLabel: 'Modifier',
  );
  if (!ok || !context.mounted) return;

  await runTradeAction(
    context,
    ref,
    () => stopLoss
        ? ref.read(tradeActionsProvider).modifyStopLoss(position.ticket, value)
        : ref.read(tradeActionsProvider).modifyTakeProfit(position.ticket, value),
    'Modification envoyée au broker.',
  );
}

Future<void> _breakEven(BuildContext context, WidgetRef ref, OpenPosition position) async {
  final int? offset = await showDialog<int>(
    context: context,
    builder: (BuildContext dialogContext) => const BreakEvenDialog(),
  );
  if (offset == null || !context.mounted) return;

  final bool ok = await confirmAction(
    context,
    title: 'Mettre à break even',
    message: 'Le stop loss de ${position.symbol} sera remonté au prix d\'entrée '
        '${Fmt.price(position.openPrice)}'
        '${offset > 0 ? ', avec une marge de $offset points en votre faveur' : ''}. '
        'La position ne pourra plus se clôturer en perte.',
    confirmLabel: 'Appliquer',
  );
  if (!ok || !context.mounted) return;

  await runTradeAction(
    context,
    ref,
    () => ref.read(tradeActionsProvider).breakEven(position.ticket, offset),
    'Break even appliqué.',
  );
}

// ---------------------------------------------------------------------------
// Annulation d'un ordre en attente
// ---------------------------------------------------------------------------

Future<void> confirmCancelOrder(
  BuildContext context,
  WidgetRef ref,
  PendingOrder order,
) async {
  final bool ok = await confirmAction(
    context,
    title: 'Annuler l\'ordre',
    message: 'L\'ordre ${order.orderTypeLabel} sur ${order.symbol} '
        '(${Fmt.lots(order.volume)} lot à ${Fmt.price(order.price)}) sera retiré du carnet. '
        'Il ne se déclenchera plus.',
    confirmLabel: 'Annuler l\'ordre',
    cancelLabel: 'Conserver',
    destructive: true,
  );
  if (!ok || !context.mounted) return;
  await runTradeAction(
    context,
    ref,
    () => ref.read(tradeActionsProvider).cancelOrder(order.ticket),
    'Ordre ${order.ticket} annulé.',
  );
}

/// Exécute une action de trading, affiche le message du Bridge en cas de refus
/// et rafraîchit les écrans concernés en cas de succès.
Future<void> runTradeAction(
  BuildContext context,
  WidgetRef ref,
  Future<void> Function() action,
  String successMessage,
) async {
  try {
    await action();
  } on ApiException catch (error) {
    if (context.mounted) showToast(context, error.message, error: true);
    return;
  }
  ref.invalidate(openPositionsProvider);
  ref.invalidate(pendingOrdersProvider);
  ref.read(closedTradesProvider.notifier).reload();
  refreshBridgeData(ref);
  if (context.mounted) showToast(context, successMessage);
}
