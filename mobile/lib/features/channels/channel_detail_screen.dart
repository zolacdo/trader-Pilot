import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api/api_exception.dart';
import '../../core/theme/app_theme.dart';
import '../../core/widgets/app_widgets.dart';
import 'models/channel.dart';
import 'providers/channels_providers.dart';
import 'widgets/analyze_dialog.dart';
import 'widgets/channel_analysis_view.dart';
import 'widgets/channel_detail_sections.dart';
import 'widgets/channel_settings_form.dart';

/// Détail d'un canal : informations, analyse, profil de parsing, réglages.
class ChannelDetailScreen extends ConsumerWidget {
  const ChannelDetailScreen({super.key, required this.channelId});

  final int channelId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    ref.watch(channelsLiveProvider);
    final AsyncValue<ChannelDetail> detail = ref.watch(channelDetailProvider(channelId));

    return Scaffold(
      appBar: AppBar(
        title: Text(detail.valueOrNull?.channel.title ?? 'Canal'),
      ),
      body: switch (detail) {
        AsyncError(:final Object error) => ErrorView(
            message: error is ApiException ? error.message : 'Canal indisponible.',
            technical: error is ApiException ? error.technical : error.toString(),
            onRetry: () => ref.invalidate(channelDetailProvider(channelId)),
          ),
        AsyncData(:final ChannelDetail value) => _ChannelDetailBody(detail: value),
        _ => const LoadingView(label: 'Chargement du canal…'),
      },
    );
  }
}

class _ChannelDetailBody extends ConsumerWidget {
  const _ChannelDetailBody({required this.detail});

  final ChannelDetail detail;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final Channel channel = detail.channel;
    return RefreshIndicator(
      onRefresh: () async {
        ref.invalidate(channelDetailProvider(channel.id));
        await ref.read(channelDetailProvider(channel.id).future);
      },
      child: ListView(
        physics: const AlwaysScrollableScrollPhysics(),
        padding: AppSpacing.page,
        children: <Widget>[
          ChannelInfoCard(channel: channel),
          const SizedBox(height: AppSpacing.md),
          _AnalysisBlock(detail: detail),
          const SizedBox(height: AppSpacing.md),
          ParserProfileCard(profile: detail.parserProfile),
          const SizedBox(height: AppSpacing.md),
          RecentSignalsCard(signals: detail.recentSignals),
          const SizedBox(height: AppSpacing.md),
          ChannelSettingsForm(
            key: ValueKey<int>(channel.id),
            channelId: channel.id,
            channelTitle: channel.title,
            settings: channel.settings ?? const ChannelSettings(),
          ),
          const SizedBox(height: AppSpacing.xl),
        ],
      ),
    );
  }
}

/// Bouton d'analyse et dernier rapport disponible.
class _AnalysisBlock extends ConsumerWidget {
  const _AnalysisBlock({required this.detail});

  final ChannelDetail detail;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final ThemeData theme = Theme.of(context);
    final ChannelAnalysis? analysis = detail.latestAnalysis;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        AppCard(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: <Widget>[
              const SectionHeader(
                title: 'Analyse du canal',
                subtitle: 'Relit les derniers messages accessibles pour mesurer la qualité '
                    'des signaux. Aucun ordre n\'est envoyé.',
              ),
              SizedBox(
                width: double.infinity,
                child: FilledButton.icon(
                  onPressed: () => runChannelAnalysis(
                    context,
                    ref,
                    channelId: detail.channel.id,
                    title: detail.channel.title,
                  ),
                  icon: const Icon(Icons.analytics_outlined, size: 18),
                  label: const Text('Analyser'),
                ),
              ),
              if (analysis == null) ...<Widget>[
                const SizedBox(height: AppSpacing.md),
                Text(
                  'Aucune analyse pour ce canal. Lancez-en une pour connaître la part '
                  'de messages interprétables, la présence de SL et de TP, et la '
                  'fréquence des signaux.',
                  style: theme.textTheme.bodySmall,
                ),
              ],
            ],
          ),
        ),
        if (analysis != null) ...<Widget>[
          const SizedBox(height: AppSpacing.md),
          ChannelAnalysisView(analysis: analysis),
        ],
      ],
    );
  }
}
