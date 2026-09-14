import 'package:flutter/material.dart';

import '../../../core/theme/app_colors.dart';
import '../../../core/theme/app_theme.dart';
import '../../../core/utils/formatters.dart';
import '../../../core/widgets/app_widgets.dart';
import '../journal_controller.dart';

/// Couleur d'un niveau : rouge réservé à ERROR et CRITICAL, orange à WARNING.
Color journalLevelColor(String? level) {
  return switch (level) {
    'CRITICAL' || 'ERROR' => AppColors.loss,
    'WARNING' => AppColors.warning,
    _ => AppColors.textTertiary,
  };
}

/// Une entrée du journal.
class JournalTile extends StatelessWidget {
  const JournalTile({super.key, required this.entry, this.onOpenSignal});

  final Map<String, dynamic> entry;
  final void Function(int signalId)? onOpenSignal;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    final String? level = entry['level']?.toString();
    final Object? rawSignalId = entry['signalId'];
    final int? signalId = rawSignalId is int ? rawSignalId : int.tryParse('${rawSignalId ?? ''}');

    return AppCard(
      padding: const EdgeInsets.symmetric(horizontal: AppSpacing.lg, vertical: AppSpacing.md),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Row(
            crossAxisAlignment: CrossAxisAlignment.center,
            children: <Widget>[
              Container(
                width: 8,
                height: 8,
                margin: const EdgeInsets.only(right: AppSpacing.sm),
                decoration: BoxDecoration(
                  color: journalLevelColor(level),
                  shape: BoxShape.circle,
                ),
              ),
              Expanded(
                child: Text(
                  (entry['event'] ?? '--').toString(),
                  style: theme.textTheme.titleMedium,
                  overflow: TextOverflow.ellipsis,
                ),
              ),
              Text(Fmt.dayTime(entry['createdAt']), style: theme.textTheme.bodySmall),
            ],
          ),
          const SizedBox(height: AppSpacing.xs),
          Text((entry['message'] ?? '').toString(), style: theme.textTheme.bodyMedium),
          const SizedBox(height: AppSpacing.sm),
          Row(
            children: <Widget>[
              Expanded(
                child: Text(
                  '${level ?? '--'} · ${journalCategoryLabel(entry['category']?.toString())}',
                  style: theme.textTheme.labelSmall,
                  overflow: TextOverflow.ellipsis,
                ),
              ),
              if (signalId != null && onOpenSignal != null)
                TextButton(
                  onPressed: () => onOpenSignal!(signalId),
                  style: TextButton.styleFrom(
                    padding: const EdgeInsets.symmetric(horizontal: AppSpacing.sm),
                    minimumSize: const Size(0, 32),
                    visualDensity: VisualDensity.compact,
                  ),
                  child: Text('Signal n° $signalId'),
                ),
            ],
          ),
        ],
      ),
    );
  }
}

/// Une action sensible du journal d'audit.
class AuditTile extends StatelessWidget {
  const AuditTile({super.key, required this.entry, this.onOpenSignal});

  final Map<String, dynamic> entry;
  final void Function(int signalId)? onOpenSignal;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    final Object? rawSignalId = entry['signalId'];
    final int? signalId = rawSignalId is int ? rawSignalId : int.tryParse('${rawSignalId ?? ''}');
    final Object? details = entry['details'];

    return AppCard(
      padding: const EdgeInsets.symmetric(horizontal: AppSpacing.lg, vertical: AppSpacing.md),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Row(
            children: <Widget>[
              Expanded(
                child: Text(
                  auditActionLabel(entry['action']?.toString()),
                  style: theme.textTheme.titleMedium,
                ),
              ),
              Text(Fmt.dayTime(entry['createdAt']), style: theme.textTheme.bodySmall),
            ],
          ),
          const SizedBox(height: AppSpacing.xs),
          DetailRow(label: 'Auteur', value: (entry['actor'] ?? '--').toString()),
          DetailRow(label: 'Cible', value: (entry['target'] ?? '--').toString()),
          if (details is Map && details.isNotEmpty)
            for (final MapEntry<dynamic, dynamic> detail in details.entries)
              DetailRow(
                label: _humanKey(detail.key.toString()),
                value: _humanValue(detail.value),
              ),
          if (signalId != null && onOpenSignal != null)
            Align(
              alignment: Alignment.centerRight,
              child: TextButton(
                onPressed: () => onOpenSignal!(signalId),
                child: Text('Signal n° $signalId'),
              ),
            ),
        ],
      ),
    );
  }
}

/// Libellé français d'une action auditée.
String auditActionLabel(String? action) {
  return switch (action) {
    'order_sent' => 'Ordre envoyé',
    'order_cancelled' => 'Ordre annulé',
    'position_closed' => 'Position fermée',
    'position_modified' => 'Position modifiée',
    'execution_mode_changed' => 'Changement de mode d\'exécution',
    'live_unlocked' => 'Déverrouillage du mode réel',
    'live_locked' => 'Verrouillage du mode réel',
    'emergency_stop' => 'Arrêt d\'urgence',
    'emergency_close_all' => 'Fermeture d\'urgence de toutes les positions',
    'emergency_cancel_pending' => 'Annulation d\'urgence des ordres en attente',
    'auto_trading_changed' => 'Trading automatique modifié',
    'signal_approved' => 'Signal approuvé manuellement',
    'signal_rejected' => 'Signal refusé manuellement',
    null => '--',
    _ => action.replaceAll('_', ' '),
  };
}

/// Rend une clé technique lisible : `execution_mode` devient « execution mode ».
String _humanKey(String key) {
  final String spaced = key.replaceAll('_', ' ').trim();
  if (spaced.isEmpty) return key;
  return spaced[0].toUpperCase() + spaced.substring(1);
}

/// Rend une valeur JSON lisible sans jamais l'interpréter.
String _humanValue(Object? value) {
  if (value == null) return '--';
  if (value is bool) return value ? 'oui' : 'non';
  if (value is List) return value.isEmpty ? '--' : value.join(', ');
  if (value is Map) {
    return value.entries
        .map((MapEntry<dynamic, dynamic> entry) => '${entry.key} : ${entry.value}')
        .join(' · ');
  }
  return value.toString();
}
