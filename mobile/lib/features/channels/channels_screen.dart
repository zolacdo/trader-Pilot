import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/api/api_exception.dart';
import '../../core/routing/app_router.dart';
import '../../core/theme/app_theme.dart';
import '../../core/widgets/app_widgets.dart';
import 'models/channel.dart';
import 'providers/channels_providers.dart';
import 'widgets/channel_card.dart';
import 'widgets/channel_mode_selector.dart';

/// Mes canaux (CDC section 15).
class ChannelsScreen extends ConsumerWidget {
  const ChannelsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    // Recharge la liste quand le Bridge signale une modification de canal.
    ref.watch(channelsLiveProvider);
    final AsyncValue<List<Channel>> channels = ref.watch(channelsProvider);

    return Scaffold(
      appBar: AppBar(title: const Text('Mes canaux')),
      body: switch (channels) {
        AsyncError(:final Object error) => ErrorView(
            message: error is ApiException ? error.message : 'Canaux indisponibles.',
            technical: error is ApiException ? error.technical : error.toString(),
            onRetry: () => ref.invalidate(channelsProvider),
          ),
        AsyncData(:final List<Channel> value) => _ChannelsBody(channels: value),
        _ => const LoadingView(label: 'Chargement des canaux…'),
      },
    );
  }
}

class _ChannelsBody extends ConsumerWidget {
  const _ChannelsBody({required this.channels});

  final List<Channel> channels;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return RefreshIndicator(
      onRefresh: () async {
        ref.invalidate(channelsProvider);
        await ref.read(channelsProvider.future);
      },
      child: ListView(
        physics: const AlwaysScrollableScrollPhysics(),
        padding: AppSpacing.page,
        children: <Widget>[
          const _TopActions(),
          const SizedBox(height: AppSpacing.lg),
          if (channels.isEmpty)
            const _NoChannelYet()
          else ...<Widget>[
            for (final Channel channel in channels) ...<Widget>[
              ChannelCard(channel: channel),
              const SizedBox(height: AppSpacing.md),
            ],
            const SizedBox(height: AppSpacing.sm),
            const ChannelModeLegend(),
          ],
          const SizedBox(height: AppSpacing.xl),
        ],
      ),
    );
  }
}

class _TopActions extends StatelessWidget {
  const _TopActions();

  @override
  Widget build(BuildContext context) {
    return Row(
      children: <Widget>[
        Expanded(
          child: FilledButton.icon(
            onPressed: () => context.push(Routes.discover),
            icon: const Icon(Icons.travel_explore_outlined, size: 18),
            label: const Text('Découvrir'),
          ),
        ),
        const SizedBox(width: AppSpacing.md),
        Expanded(
          child: OutlinedButton.icon(
            onPressed: () => context.push(Routes.compare),
            icon: const Icon(Icons.table_chart_outlined, size: 18),
            label: const Text('Comparer'),
          ),
        ),
      ],
    );
  }
}

/// Premier lancement : aucun canal suivi, on explique la marche à suivre.
class _NoChannelYet extends StatelessWidget {
  const _NoChannelYet();

  @override
  Widget build(BuildContext context) {
    return Column(
      children: <Widget>[
        const SizedBox(height: AppSpacing.xl),
        EmptyState(
          title: 'Aucun canal surveillé',
          message: 'Recherchez un canal Telegram de signaux, analysez son historique, '
              'puis ajoutez-le à votre surveillance. Il démarrera toujours en mode '
              'observation : aucun ordre ne sera envoyé.',
          icon: Icons.forum_outlined,
          action: FilledButton.icon(
            onPressed: () => context.push(Routes.discover),
            icon: const Icon(Icons.travel_explore_outlined, size: 18),
            label: const Text('Découvrir des canaux'),
          ),
        ),
        const SizedBox(height: AppSpacing.xl),
        const ChannelModeLegend(),
      ],
    );
  }
}
