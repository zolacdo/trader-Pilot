import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/api/api_exception.dart';
import '../../../core/routing/app_router.dart';
import '../../../core/theme/app_theme.dart';
import '../../../core/utils/formatters.dart';
import '../../../core/widgets/app_widgets.dart';
import '../models/channel.dart';
import '../providers/channels_providers.dart';
import 'channel_mode_selector.dart';

/// Carte d'un canal surveillé (CDC section 15).
class ChannelCard extends ConsumerWidget {
  const ChannelCard({super.key, required this.channel});

  final Channel channel;

  Future<void> _setEnabled(BuildContext context, WidgetRef ref, bool value) async {
    try {
      await ref
          .read(channelActionsProvider)
          .updateSettings(channel.id, <String, dynamic>{'enabled': value});
      if (!context.mounted) return;
      showToast(
        context,
        value
            ? '« ${channel.title} » est actif.'
            : '« ${channel.title} » est désactivé : ses signaux ne seront plus traités.',
      );
    } on ApiException catch (error) {
      if (!context.mounted) return;
      showToast(context, error.message, error: true);
    }
  }

  Future<void> _setMonitoring(BuildContext context, WidgetRef ref, bool value) async {
    try {
      await ref.read(channelActionsProvider).setMonitoring(channel.id, value);
      if (!context.mounted) return;
      showToast(
        context,
        value
            ? 'Écoute Telegram activée.'
            : 'Écoute Telegram suspendue : plus aucun message n\'est lu.',
      );
    } on ApiException catch (error) {
      if (!context.mounted) return;
      showToast(context, error.message, error: true);
    }
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final ThemeData theme = Theme.of(context);
    return AppCard(
      onTap: () => context.push(Routes.channelDetail(channel.id)),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: <Widget>[
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: <Widget>[
                    Text(
                      channel.title,
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: theme.textTheme.titleMedium,
                    ),
                    const SizedBox(height: 2),
                    Text(channel.handle, style: theme.textTheme.bodySmall),
                  ],
                ),
              ),
              Switch(
                value: channel.enabled,
                onChanged: (bool value) => _setEnabled(context, ref, value),
              ),
            ],
          ),
          const SizedBox(height: AppSpacing.sm),
          Wrap(
            spacing: AppSpacing.lg,
            runSpacing: AppSpacing.xs,
            children: <Widget>[
              _Fact(label: 'Membres', value: formatCount(channel.membersCount)),
              _Fact(label: 'Signaux', value: formatCount(channel.signalsCount)),
              _Fact(label: 'Dernier message', value: Fmt.relative(channel.lastMessageAt)),
            ],
          ),
          const SizedBox(height: AppSpacing.lg),
          ChannelModeSelector(
            channelId: channel.id,
            channelTitle: channel.title,
            mode: channel.mode,
          ),
          const SizedBox(height: AppSpacing.md),
          Wrap(
            spacing: AppSpacing.md,
            runSpacing: AppSpacing.sm,
            crossAxisAlignment: WrapCrossAlignment.center,
            children: <Widget>[
              StatusChip(
                label: channel.monitored ? 'Écoute active' : 'Écoute suspendue',
                tone: channel.monitored ? StatusTone.good : StatusTone.neutral,
                icon: channel.monitored ? Icons.hearing : Icons.hearing_disabled,
                dense: true,
              ),
              TextButton(
                onPressed: () => _setMonitoring(context, ref, !channel.monitored),
                child: Text(channel.monitored ? 'Suspendre l\'écoute' : 'Reprendre l\'écoute'),
              ),
            ],
          ),
        ],
      ),
    );
  }
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
