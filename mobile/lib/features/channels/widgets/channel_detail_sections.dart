import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../../core/routing/app_router.dart';
import '../../../core/theme/app_colors.dart';
import '../../../core/theme/app_theme.dart';
import '../../../core/utils/formatters.dart';
import '../../../core/widgets/app_widgets.dart';
import '../models/channel.dart';
import 'channel_mode_selector.dart';

/// Identité du canal et mode de fonctionnement.
class ChannelInfoCard extends StatelessWidget {
  const ChannelInfoCard({super.key, required this.channel});

  final Channel channel;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Text(channel.title, style: theme.textTheme.titleLarge),
          const SizedBox(height: 2),
          Text(channel.handle, style: theme.textTheme.bodySmall),
          const SizedBox(height: AppSpacing.md),
          Wrap(
            spacing: AppSpacing.sm,
            runSpacing: AppSpacing.sm,
            children: <Widget>[
              StatusChip(
                label: channel.isPublic ? 'Canal public' : 'Canal privé',
                dense: true,
                icon: channel.isPublic ? Icons.public : Icons.lock_outline,
              ),
              StatusChip(
                label: channel.joined ? 'Rejoint' : 'Non rejoint',
                dense: true,
                icon: channel.joined ? Icons.how_to_reg_outlined : Icons.person_outline,
              ),
              StatusChip(
                label: channel.monitored ? 'Écoute active' : 'Écoute suspendue',
                tone: channel.monitored ? StatusTone.good : StatusTone.neutral,
                dense: true,
              ),
              StatusChip(
                label: channel.enabled ? 'Canal actif' : 'Canal désactivé',
                tone: channel.enabled ? StatusTone.good : StatusTone.neutral,
                dense: true,
              ),
            ],
          ),
          if (channel.description != null) ...<Widget>[
            const SizedBox(height: AppSpacing.md),
            Text(channel.description!, style: theme.textTheme.bodySmall),
          ],
          const Divider(height: AppSpacing.xl),
          DetailRow(label: 'Membres', value: formatCount(channel.membersCount)),
          DetailRow(label: 'Signaux reçus', value: formatCount(channel.signalsCount)),
          DetailRow(label: 'Dernier message', value: Fmt.relative(channel.lastMessageAt)),
          DetailRow(label: 'Dernier signal', value: Fmt.relative(channel.lastSignalAt)),
          DetailRow(label: 'Identifiant Telegram', value: channel.telegramId?.toString() ?? '--'),
          const SizedBox(height: AppSpacing.lg),
          Text('Mode de fonctionnement', style: theme.textTheme.labelSmall),
          const SizedBox(height: AppSpacing.sm),
          ChannelModeSelector(
            channelId: channel.id,
            channelTitle: channel.title,
            mode: channel.mode,
          ),
        ],
      ),
    );
  }
}

/// Profil de parsing appris par le Bridge (CDC section 53).
class ParserProfileCard extends StatelessWidget {
  const ParserProfileCard({super.key, required this.profile});

  final ParserProfile profile;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          const SectionHeader(
            title: 'Profil de parsing appris',
            subtitle: 'Ce que le Bridge a retenu de la mise en forme de ce canal.',
          ),
          DetailRow(
            label: 'Interprétations locales réussies',
            value: formatCount(profile.deterministicSuccess),
          ),
          DetailRow(
            label: 'Replis sur l\'IA',
            value: formatCount(profile.aiFallbackCount),
          ),
          DetailRow(label: 'Confiance du profil', value: Fmt.confidence(profile.confidence)),
          DetailRow(
            label: 'Dernier format reconnu',
            value: profile.lastSuccessfulFormat ?? '--',
          ),
          const SizedBox(height: AppSpacing.md),
          Text('Formats connus', style: theme.textTheme.labelSmall),
          const SizedBox(height: AppSpacing.sm),
          if (profile.knownFormats.isEmpty)
            Text('Aucun format mémorisé pour l\'instant.', style: theme.textTheme.bodySmall)
          else
            // Une signature de format peut être longue : elle passe à la ligne
            // plutôt que de déborder de la carte.
            for (final String format in profile.knownFormats)
              Container(
                width: double.infinity,
                margin: const EdgeInsets.only(bottom: AppSpacing.sm),
                padding: const EdgeInsets.symmetric(
                  horizontal: AppSpacing.md,
                  vertical: AppSpacing.sm,
                ),
                decoration: BoxDecoration(
                  color: theme.brightness == Brightness.dark
                      ? AppColors.surfaceMutedDark
                      : AppColors.surfaceMuted,
                  borderRadius: BorderRadius.circular(AppSpacing.radiusSmall),
                ),
                child: Text(
                  format,
                  style: theme.textTheme.bodySmall?.copyWith(fontFamily: 'monospace'),
                ),
              ),
          const SizedBox(height: AppSpacing.md),
          Text('Alias d\'instruments appris', style: theme.textTheme.labelSmall),
          const SizedBox(height: AppSpacing.sm),
          if (profile.symbolAliases.isEmpty)
            Text('Aucun alias appris.', style: theme.textTheme.bodySmall)
          else
            for (final MapEntry<String, String> alias in profile.symbolAliases.entries)
              DetailRow(label: alias.key, value: alias.value),
        ],
      ),
    );
  }
}

/// Derniers signaux reçus de ce canal.
class RecentSignalsCard extends StatelessWidget {
  const RecentSignalsCard({super.key, required this.signals});

  final List<ChannelRecentSignal> signals;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          const SectionHeader(title: 'Derniers signaux'),
          if (signals.isEmpty)
            Text('Aucun signal reçu de ce canal.', style: theme.textTheme.bodySmall)
          else
            for (final ChannelRecentSignal signal in signals)
              InkWell(
                onTap: () => context.push(Routes.signalDetail(signal.id)),
                borderRadius: BorderRadius.circular(AppSpacing.radiusSmall),
                child: Padding(
                  padding: const EdgeInsets.symmetric(vertical: AppSpacing.sm),
                  child: Row(
                    children: <Widget>[
                      SizedBox(
                        width: 96,
                        child: Text(
                          signal.symbol ?? '--',
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: theme.textTheme.bodyMedium
                              ?.copyWith(fontWeight: FontWeight.w600),
                        ),
                      ),
                      if (signal.direction != null) StatusChip.direction(signal.direction),
                      const Spacer(),
                      Flexible(
                        child: Text(
                          Fmt.signalStatus(signal.status),
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          textAlign: TextAlign.right,
                          style: theme.textTheme.bodySmall,
                        ),
                      ),
                      const SizedBox(width: AppSpacing.sm),
                      Text(Fmt.time(signal.receivedAt), style: theme.textTheme.bodySmall),
                      const Icon(Icons.chevron_right, size: 18),
                    ],
                  ),
                ),
              ),
        ],
      ),
    );
  }
}
