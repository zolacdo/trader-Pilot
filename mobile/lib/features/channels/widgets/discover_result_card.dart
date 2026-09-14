import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/api/api_exception.dart';
import '../../../core/routing/app_router.dart';
import '../../../core/theme/app_colors.dart';
import '../../../core/theme/app_theme.dart';
import '../../../core/utils/formatters.dart';
import '../../../core/widgets/app_widgets.dart';
import '../models/channel.dart';
import '../models/discovery.dart';
import '../providers/channels_providers.dart';
import 'analyze_dialog.dart';

/// Résultat de recherche avec ses trois actions (CDC section 69).
class DiscoverResultCard extends ConsumerWidget {
  const DiscoverResultCard({super.key, required this.result});

  final DiscoveredChannel result;

  /// Canal déjà suivi correspondant à ce résultat, s'il existe.
  Channel? _tracked(WidgetRef ref) {
    final List<Channel> channels = ref.watch(channelsProvider).valueOrNull ?? const <Channel>[];
    for (final Channel channel in channels) {
      if (channel.telegramId == result.id) return channel;
    }
    return null;
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final ThemeData theme = Theme.of(context);
    final Channel? tracked = _tracked(ref);

    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Text(result.title, style: theme.textTheme.titleMedium),
          const SizedBox(height: 2),
          Text(result.handle, style: theme.textTheme.bodySmall),
          const SizedBox(height: AppSpacing.sm),
          Wrap(
            spacing: AppSpacing.sm,
            runSpacing: AppSpacing.sm,
            children: <Widget>[
              StatusChip(
                label: result.isPublic ? 'Public' : 'Privé',
                icon: result.isPublic ? Icons.public : Icons.lock_outline,
                dense: true,
              ),
              StatusChip(
                label: result.alreadyJoined ? 'Déjà rejoint' : 'Non rejoint',
                dense: true,
              ),
              if (tracked != null)
                StatusChip(
                  label: 'Déjà surveillé · ${Fmt.channelMode(tracked.mode)}',
                  tone: StatusTone.accent,
                  dense: true,
                ),
            ],
          ),
          if (result.description != null) ...<Widget>[
            const SizedBox(height: AppSpacing.md),
            Text(
              result.description!,
              maxLines: 3,
              overflow: TextOverflow.ellipsis,
              style: theme.textTheme.bodySmall,
            ),
          ],
          const SizedBox(height: AppSpacing.md),
          Wrap(
            spacing: AppSpacing.lg,
            runSpacing: AppSpacing.sm,
            children: <Widget>[
              _Fact(label: 'Membres', value: formatCount(result.membersCount)),
              _Fact(label: 'Dernière activité', value: Fmt.relative(result.lastMessageAt)),
              _Fact(
                label: 'Signaux détectés',
                value: result.analysableLabel,
              ),
            ],
          ),
          if (result.previewAvailable) ...<Widget>[
            const SizedBox(height: AppSpacing.sm),
            Text(
              'Sur les ${result.sampleSize} derniers messages, '
              '${result.signalLikeCount} sont interprétables comme signaux.',
              style: theme.textTheme.bodySmall,
            ),
          ] else if (result.previewReason != null) ...<Widget>[
            const SizedBox(height: AppSpacing.sm),
            Text(
              result.previewReason!,
              style: theme.textTheme.bodySmall?.copyWith(color: AppColors.warning),
            ),
          ],
          const SizedBox(height: AppSpacing.lg),
          Wrap(
            spacing: AppSpacing.sm,
            runSpacing: AppSpacing.sm,
            children: <Widget>[
              OutlinedButton(
                onPressed: () => _showDetails(context, result, tracked),
                style: OutlinedButton.styleFrom(minimumSize: const Size(0, 40)),
                child: const Text('Voir'),
              ),
              OutlinedButton(
                onPressed: () => _analyse(context, ref, tracked),
                style: OutlinedButton.styleFrom(minimumSize: const Size(0, 40)),
                child: const Text('Analyser'),
              ),
              if (tracked == null)
                FilledButton(
                  onPressed: () => addToWatchlist(context, ref),
                  style: FilledButton.styleFrom(minimumSize: const Size(0, 40)),
                  child: const Text('Ajouter à ma surveillance'),
                )
              else
                FilledButton(
                  onPressed: () => context.push(Routes.channelDetail(tracked.id)),
                  style: FilledButton.styleFrom(minimumSize: const Size(0, 40)),
                  child: const Text('Ouvrir le canal'),
                ),
            ],
          ),
        ],
      ),
    );
  }

  /// L'analyse porte sur un canal enregistré : on l'ajoute d'abord si besoin.
  Future<void> _analyse(BuildContext context, WidgetRef ref, Channel? tracked) async {
    Channel? channel = tracked;
    if (channel == null) {
      final bool accepted = await confirmAction(
        context,
        title: 'Analyser « ${result.title} »',
        message: 'Pour relire son historique, le canal doit d\'abord être ajouté à '
            'votre surveillance. Il démarrera en mode observation et votre compte '
            'Telegram ne rejoindra pas le canal.',
        confirmLabel: 'Ajouter et analyser',
      );
      if (!accepted || !context.mounted) return;
      channel = await _add(context, ref, join: false);
      if (channel == null || !context.mounted) return;
    }
    await runChannelAnalysis(context, ref, channelId: channel.id, title: channel.title);
  }

  Future<Channel?> _add(BuildContext context, WidgetRef ref, {required bool join}) async {
    try {
      return await ref
          .read(channelActionsProvider)
          .addChannel(telegramId: result.id, username: result.username, join: join);
    } on ApiException catch (error) {
      if (!context.mounted) return null;
      showToast(context, error.message, error: true);
      return null;
    }
  }

  /// Ajout à la surveillance : le canal démarre en mode OBSERVATION.
  Future<void> addToWatchlist(BuildContext context, WidgetRef ref) async {
    final bool? join = await _askJoin(context, result);
    if (join == null || !context.mounted) return;
    final Channel? channel = await _add(context, ref, join: join);
    if (channel == null || !context.mounted) return;
    showToast(
      context,
      '« ${channel.title} » est ajouté en mode observation : aucun ordre ne sera envoyé.',
    );
  }
}

/// Confirmation d'ajout, avec l'option « rejoindre » décochée par défaut.
Future<bool?> _askJoin(BuildContext context, DiscoveredChannel result) {
  return showDialog<bool>(
    context: context,
    builder: (BuildContext dialogContext) {
      bool join = false;
      return StatefulBuilder(
        builder: (BuildContext context, StateSetter setState) {
          final ThemeData theme = Theme.of(context);
          return AlertDialog(
            title: Text('Ajouter « ${result.title} »'),
            content: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: <Widget>[
                Text(
                  'Le canal démarre en MODE OBSERVATION : ses messages sont reçus, '
                  'interprétés et simulés, mais aucun ordre n\'est jamais envoyé. '
                  'Vous pourrez passer en manuel ou en automatique plus tard.',
                  style: theme.textTheme.bodySmall,
                ),
                const SizedBox(height: AppSpacing.md),
                CheckboxListTile(
                  value: join,
                  onChanged: result.alreadyJoined
                      ? null
                      : (bool? value) => setState(() => join = value ?? false),
                  contentPadding: EdgeInsets.zero,
                  controlAffinity: ListTileControlAffinity.leading,
                  title: const Text('Rejoindre le canal'),
                  subtitle: Text(
                    result.alreadyJoined
                        ? 'Votre compte Telegram suit déjà ce canal.'
                        : 'Votre compte Telegram rejoindra ce canal, comme si vous '
                            'cliquiez sur « Rejoindre » dans Telegram. Nécessaire '
                            'uniquement pour lire un canal privé.',
                    style: theme.textTheme.bodySmall,
                  ),
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
                onPressed: () => Navigator.of(dialogContext).pop(join),
                child: const Text('Ajouter'),
              ),
            ],
          );
        },
      );
    },
  );
}

/// Fiche détaillée d'un résultat de recherche.
Future<void> _showDetails(BuildContext context, DiscoveredChannel result, Channel? tracked) {
  return showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    showDragHandle: true,
    builder: (BuildContext context) {
      final ThemeData theme = Theme.of(context);
      return SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(AppSpacing.lg, 0, AppSpacing.lg, AppSpacing.xl),
          child: SingleChildScrollView(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisSize: MainAxisSize.min,
              children: <Widget>[
                Text(result.title, style: theme.textTheme.titleLarge),
                const SizedBox(height: 2),
                Text(result.handle, style: theme.textTheme.bodySmall),
                const SizedBox(height: AppSpacing.lg),
                if (result.description != null) ...<Widget>[
                  Text(result.description!, style: theme.textTheme.bodyMedium),
                  const SizedBox(height: AppSpacing.lg),
                ],
                DetailRow(label: 'Identifiant Telegram', value: result.id.toString()),
                DetailRow(label: 'Membres', value: formatCount(result.membersCount)),
                DetailRow(label: 'Visibilité', value: result.isPublic ? 'Public' : 'Privé'),
                DetailRow(
                  label: 'Compte Telegram',
                  value: result.alreadyJoined ? 'Canal déjà rejoint' : 'Canal non rejoint',
                ),
                DetailRow(label: 'Dernière activité', value: Fmt.dayTime(result.lastMessageAt)),
                DetailRow(
                  label: 'Messages examinés',
                  value: result.sampleSize == null ? '--' : result.sampleSize.toString(),
                ),
                DetailRow(
                  label: 'Signaux détectés',
                  value: result.previewAvailable
                      ? '${result.signalLikeCount} '
                          '(${Fmt.percent((result.signalRate ?? 0) * 100)})'
                      : '--',
                ),
                if (!result.previewAvailable && result.previewReason != null)
                  Padding(
                    padding: const EdgeInsets.only(top: AppSpacing.sm),
                    child: Text(
                      result.previewReason!,
                      style: theme.textTheme.bodySmall?.copyWith(color: AppColors.warning),
                    ),
                  ),
                DetailRow(
                  label: 'Surveillance',
                  value: tracked == null
                      ? 'Canal non surveillé'
                      : 'Surveillé en mode ${Fmt.channelMode(tracked.mode)}',
                ),
                const SizedBox(height: AppSpacing.lg),
                Text(
                  'Ces informations viennent de Telegram. L\'application ne porte aucun '
                  'jugement sur la qualité d\'un canal : lancez une analyse pour obtenir '
                  'des mesures factuelles.',
                  style: theme.textTheme.bodySmall,
                ),
              ],
            ),
          ),
        ),
      );
    },
  );
}

class _Fact extends StatelessWidget {
  const _Fact({required this.label, required this.value});

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
        Text(value, style: theme.textTheme.bodyMedium?.copyWith(fontWeight: FontWeight.w600)),
      ],
    );
  }
}
