import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../../core/routing/app_router.dart';
import '../../../core/theme/app_colors.dart';
import '../../../core/theme/app_theme.dart';
import '../../../core/utils/formatters.dart';
import '../../../core/widgets/app_widgets.dart';
import '../../bridge/models/bridge_json.dart';
import '../../bridge/models/bridge_labels.dart';

/// Positions actuellement ouvertes sur le mode d'exécution courant.
class OpenPositionsSection extends StatelessWidget {
  const OpenPositionsSection({super.key, required this.positions, required this.currency});

  final List<Map<String, dynamic>> positions;
  final String currency;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        SectionHeader(
          title: 'Positions ouvertes',
          subtitle: positions.isEmpty ? null : '${positions.length} position(s) suivie(s)',
          action: positions.isEmpty
              ? null
              : TextButton(
                  onPressed: () => context.go(Routes.trades),
                  child: const Text('Tout voir'),
                ),
        ),
        if (positions.isEmpty)
          const AppCard(
            child: EmptyState(
              title: 'Aucune position ouverte',
              message: 'Les positions apparaîtront ici dès qu\'un signal sera exécuté.',
              icon: Icons.trending_flat,
            ),
          )
        else
          AppCard(
            padding: EdgeInsets.zero,
            child: Column(
              children: <Widget>[
                for (int i = 0; i < positions.length; i++) ...<Widget>[
                  if (i > 0) const Divider(height: 1),
                  _PositionRow(position: positions[i], currency: currency),
                ],
              ],
            ),
          ),
      ],
    );
  }
}

class _PositionRow extends StatelessWidget {
  const _PositionRow({required this.position, required this.currency});

  final Map<String, dynamic> position;
  final String currency;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    final num? profit = Json.number(position['profit']);

    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: AppSpacing.lg, vertical: AppSpacing.md),
      child: Row(
        children: <Widget>[
          StatusChip.direction(Json.text(position['direction'])),
          const SizedBox(width: AppSpacing.md),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: <Widget>[
                Text(Json.text(position['symbol']) ?? '--', style: theme.textTheme.titleMedium),
                const SizedBox(height: 2),
                Text(
                  '${Fmt.lots(Json.number(position['volume']))} lot · '
                  'entrée ${Fmt.price(Json.number(position['openPrice']))} · '
                  '${Fmt.relative(position['openedAt'])}',
                  style: theme.textTheme.bodySmall,
                ),
              ],
            ),
          ),
          const SizedBox(width: AppSpacing.sm),
          Text(
            profit == null ? '--' : Fmt.signedMoney(profit, currency: currency),
            style: theme.textTheme.titleMedium?.copyWith(
              color: profit == null ? null : AppColors.forAmount(profit),
              fontFeatures: const <FontFeature>[FontFeature.tabularFigures()],
            ),
          ),
        ],
      ),
    );
  }
}

/// Derniers signaux reçus, quel que soit leur sort (exécuté, refusé, observé).
class RecentSignalsSection extends StatelessWidget {
  const RecentSignalsSection({super.key, required this.signals});

  final List<Map<String, dynamic>> signals;

  static const int _maxShown = 5;

  @override
  Widget build(BuildContext context) {
    final List<Map<String, dynamic>> shown =
        signals.length > _maxShown ? signals.sublist(0, _maxShown) : signals;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        SectionHeader(
          title: 'Derniers signaux',
          action: signals.isEmpty
              ? null
              : TextButton(
                  onPressed: () => context.go(Routes.signals),
                  child: const Text('Tout voir'),
                ),
        ),
        if (shown.isEmpty)
          const AppCard(
            child: EmptyState(
              title: 'Aucun signal reçu',
              message: 'Ajoutez un canal Telegram pour commencer à recevoir des signaux.',
              icon: Icons.podcasts_outlined,
            ),
          )
        else
          AppCard(
            padding: EdgeInsets.zero,
            child: Column(
              children: <Widget>[
                for (int i = 0; i < shown.length; i++) ...<Widget>[
                  if (i > 0) const Divider(height: 1),
                  _SignalRow(signal: shown[i]),
                ],
              ],
            ),
          ),
      ],
    );
  }
}

class _SignalRow extends StatelessWidget {
  const _SignalRow({required this.signal});

  final Map<String, dynamic> signal;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    final int? id = Json.integer(signal['id']);
    final String? rejection = Json.text(signal['rejectionReason']);

    return InkWell(
      onTap: id == null ? null : () => context.push(Routes.signalDetail(id)),
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: AppSpacing.lg, vertical: AppSpacing.md),
        child: Row(
          children: <Widget>[
            StatusChip.direction(Json.text(signal['direction'])),
            const SizedBox(width: AppSpacing.md),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: <Widget>[
                  Text(Json.text(signal['symbol']) ?? '--', style: theme.textTheme.titleMedium),
                  const SizedBox(height: 2),
                  Text(
                    rejection == null
                        ? '${Fmt.signalStatus(Json.text(signal['status']))} · '
                            '${Fmt.relative(signal['receivedAt'])}'
                        : '${Fmt.rejectionReason(rejection)} · '
                            '${Fmt.relative(signal['receivedAt'])}',
                    style: theme.textTheme.bodySmall,
                  ),
                ],
              ),
            ),
            const Icon(Icons.chevron_right, size: 20, color: AppColors.textTertiary),
          ],
        ),
      ),
    );
  }
}

/// Derniers événements journalisés par le Bridge.
class RecentEventsSection extends StatelessWidget {
  const RecentEventsSection({super.key, required this.events});

  final List<Map<String, dynamic>> events;

  static const int _maxShown = 6;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    final List<Map<String, dynamic>> shown =
        events.length > _maxShown ? events.sublist(0, _maxShown) : events;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        SectionHeader(
          title: 'Derniers événements',
          action: events.isEmpty
              ? null
              : TextButton(
                  onPressed: () => context.push(Routes.journal),
                  child: const Text('Journal'),
                ),
        ),
        if (shown.isEmpty)
          const AppCard(
            child: EmptyState(
              title: 'Aucun événement',
              message: 'Le Bridge n\'a encore rien journalisé.',
              icon: Icons.history,
            ),
          )
        else
          AppCard(
            child: Column(
              children: <Widget>[
                for (int i = 0; i < shown.length; i++) ...<Widget>[
                  if (i > 0) const SizedBox(height: AppSpacing.md),
                  Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: <Widget>[
                      StatusChip(
                        label: Fmt.time(shown[i]['createdAt']),
                        tone: BridgeLabels.eventTone(Json.text(shown[i]['level'])),
                        dense: true,
                      ),
                      const SizedBox(width: AppSpacing.md),
                      Expanded(
                        child: Text(
                          Json.text(shown[i]['message']) ?? '--',
                          style: theme.textTheme.bodyMedium,
                        ),
                      ),
                    ],
                  ),
                ],
              ],
            ),
          ),
      ],
    );
  }
}
