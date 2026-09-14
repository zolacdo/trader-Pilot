import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api/api_exception.dart';
import '../../core/theme/app_theme.dart';
import '../../core/widgets/app_widgets.dart';
import '../channels/models/channel.dart';
import '../channels/providers/channels_providers.dart';
import 'models/signal.dart';
import 'providers/signals_providers.dart';
import 'widgets/pending_review_banner.dart';
import 'widgets/signal_card.dart';
import 'widgets/signal_filters_bar.dart';

/// Page Signaux (CDC section 33) : filtres, validation manuelle, pagination.
class SignalsScreen extends ConsumerWidget {
  const SignalsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    // Abonnement temps réel : signal.new, signal.updated, signal.rejected,
    // signal.needs_review rechargent la liste.
    ref.watch(signalsLiveProvider);

    final AsyncValue<SignalsPage> feed = ref.watch(signalsFeedProvider);
    final SignalsPage? page = feed.valueOrNull;

    return Scaffold(
      appBar: AppBar(title: const Text('Signaux')),
      body: Column(
        children: <Widget>[
          const SizedBox(height: AppSpacing.xs),
          SignalFiltersBar(symbols: _symbolsOf(page)),
          const SizedBox(height: AppSpacing.md),
          Expanded(
            child: switch (feed) {
              AsyncError(:final Object error) when page == null => ErrorView(
                  message: error is ApiException ? error.message : 'Signaux indisponibles.',
                  technical: error is ApiException ? error.technical : error.toString(),
                  onRetry: () => ref.invalidate(signalsFeedProvider),
                ),
              AsyncLoading<SignalsPage>() when page == null =>
                const LoadingView(label: 'Chargement des signaux…'),
              _ => _SignalsList(page: page!),
            },
          ),
        ],
      ),
    );
  }

  /// Instruments réellement présents dans les signaux chargés.
  static List<String> _symbolsOf(SignalsPage? page) {
    if (page == null) return const <String>[];
    final Set<String> symbols = <String>{
      for (final Signal signal in page.items)
        if (signal.displaySymbol != null) signal.displaySymbol!,
    };
    return symbols.toList()..sort();
  }
}

class _SignalsList extends ConsumerWidget {
  const _SignalsList({required this.page});

  final SignalsPage page;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final Map<int, String> titles = _channelTitles(ref);
    final List<Signal> items = page.items;

    return RefreshIndicator(
      onRefresh: () async {
        ref.invalidate(pendingSignalsProvider);
        ref.invalidate(signalsFeedProvider);
        await ref.read(signalsFeedProvider.future);
      },
      child: NotificationListener<ScrollNotification>(
        onNotification: (ScrollNotification notification) {
          // Pagination par défilement : la suite arrive avant d'atteindre le bas.
          if (page.hasMore && !page.loadingMore && notification.metrics.extentAfter < 400) {
            ref.read(signalsFeedProvider.notifier).loadMore();
          }
          return false;
        },
        child: ListView.separated(
          physics: const AlwaysScrollableScrollPhysics(),
          padding: const EdgeInsets.only(bottom: AppSpacing.xxl),
          itemCount: items.length + 2,
          separatorBuilder: (BuildContext context, int index) =>
              const SizedBox(height: AppSpacing.md),
          itemBuilder: (BuildContext context, int index) {
            if (index == 0) return const PendingReviewBanner();
            if (index == items.length + 1) return _Footer(page: page);
            final Signal signal = items[index - 1];
            return Padding(
              padding: const EdgeInsets.symmetric(horizontal: AppSpacing.lg),
              child: SignalCard(
                signal: signal,
                channelTitle: signal.channelId == null ? null : titles[signal.channelId],
              ),
            );
          },
        ),
      ),
    );
  }

  static Map<int, String> _channelTitles(WidgetRef ref) {
    final List<Channel> channels = ref.watch(channelsProvider).valueOrNull ?? const <Channel>[];
    return <int, String>{for (final Channel channel in channels) channel.id: channel.title};
  }
}

/// Bas de liste : chargement de la suite, erreur de pagination ou état vide.
class _Footer extends ConsumerWidget {
  const _Footer({required this.page});

  final SignalsPage page;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final ThemeData theme = Theme.of(context);

    if (page.items.isEmpty) {
      return SizedBox(
        height: 320,
        child: EmptyState(
          title: 'Aucun signal',
          message: ref.watch(signalFiltersProvider).isDefault
              ? 'Les signaux reçus de vos canaux surveillés apparaîtront ici.'
              : 'Aucun signal ne correspond aux filtres sélectionnés.',
          icon: Icons.podcasts_outlined,
        ),
      );
    }

    if (page.loadMoreError != null) {
      return Padding(
        padding: const EdgeInsets.all(AppSpacing.lg),
        child: Column(
          children: <Widget>[
            Text(page.loadMoreError!, textAlign: TextAlign.center, style: theme.textTheme.bodySmall),
            const SizedBox(height: AppSpacing.sm),
            OutlinedButton(
              onPressed: () => ref.read(signalsFeedProvider.notifier).loadMore(),
              child: const Text('Réessayer'),
            ),
          ],
        ),
      );
    }

    if (page.loadingMore) {
      return const Padding(
        padding: EdgeInsets.all(AppSpacing.lg),
        child: Center(
          child: SizedBox(width: 22, height: 22, child: CircularProgressIndicator(strokeWidth: 2.2)),
        ),
      );
    }

    return Padding(
      padding: const EdgeInsets.all(AppSpacing.lg),
      child: Center(
        child: Text(
          page.hasMore ? 'Défilez pour charger la suite' : 'Fin de la liste',
          style: theme.textTheme.bodySmall,
        ),
      ),
    );
  }
}
