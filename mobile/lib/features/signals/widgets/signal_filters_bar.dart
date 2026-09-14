import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/theme/app_colors.dart';
import '../../../core/theme/app_theme.dart';
import '../../channels/models/channel.dart';
import '../../channels/providers/channels_providers.dart';
import '../providers/signals_providers.dart';

/// Filtres de la page Signaux (CDC section 33).
class SignalFiltersBar extends ConsumerWidget {
  const SignalFiltersBar({super.key, required this.symbols});

  /// Instruments réellement observés dans les signaux chargés.
  final List<String> symbols;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final SignalFilters filters = ref.watch(signalFiltersProvider);
    final List<Channel> channels = ref.watch(channelsProvider).valueOrNull ?? const <Channel>[];

    void update(SignalFilters value) => ref.read(signalFiltersProvider.notifier).state = value;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        SingleChildScrollView(
          scrollDirection: Axis.horizontal,
          padding: const EdgeInsets.symmetric(horizontal: AppSpacing.lg),
          child: Row(
            children: <Widget>[
              _Chip(
                label: 'Tous',
                selected: filters.group == null && !filters.today,
                onSelected: () => update(
                  filters.copyWith(clearGroup: true, today: false),
                ),
              ),
              _Chip(
                label: 'Aujourd\'hui',
                selected: filters.today,
                onSelected: () => update(filters.copyWith(today: !filters.today)),
              ),
              _GroupChip(label: 'À valider', group: SignalGroups.review, filters: filters),
              _GroupChip(label: 'Exécutés', group: SignalGroups.executed, filters: filters),
              _GroupChip(label: 'Acceptés', group: SignalGroups.accepted, filters: filters),
              _GroupChip(label: 'Refusés', group: SignalGroups.rejected, filters: filters),
              _GroupChip(label: 'Erreur', group: SignalGroups.error, filters: filters),
              _GroupChip(label: 'Observés', group: SignalGroups.observed, filters: filters),
            ],
          ),
        ),
        const SizedBox(height: AppSpacing.sm),
        SingleChildScrollView(
          scrollDirection: Axis.horizontal,
          padding: const EdgeInsets.symmetric(horizontal: AppSpacing.lg),
          child: Row(
            children: <Widget>[
              _MenuChip<int?>(
                icon: Icons.forum_outlined,
                label: filters.channelId == null
                    ? 'Tous les canaux'
                    : _channelTitle(channels, filters.channelId!),
                selected: filters.channelId != null,
                value: filters.channelId,
                entries: <({int? value, String label})>[
                  (value: null, label: 'Tous les canaux'),
                  for (final Channel channel in channels)
                    (value: channel.id, label: channel.title),
                ],
                onSelected: (int? value) => update(
                  value == null
                      ? filters.copyWith(clearChannel: true)
                      : filters.copyWith(channelId: value),
                ),
              ),
              _MenuChip<String?>(
                icon: Icons.show_chart,
                label: filters.symbol ?? 'Tous les instruments',
                selected: filters.symbol != null,
                value: filters.symbol,
                entries: <({String? value, String label})>[
                  (value: null, label: 'Tous les instruments'),
                  for (final String symbol in symbols) (value: symbol, label: symbol),
                ],
                onSelected: (String? value) => update(
                  value == null
                      ? filters.copyWith(clearSymbol: true)
                      : filters.copyWith(symbol: value),
                ),
              ),
              _DirectionChip(direction: 'BUY', filters: filters),
              _DirectionChip(direction: 'SELL', filters: filters),
              if (!filters.isDefault)
                Padding(
                  padding: const EdgeInsets.only(left: AppSpacing.sm),
                  child: TextButton.icon(
                    onPressed: () => update(const SignalFilters()),
                    icon: const Icon(Icons.close, size: 16),
                    label: const Text('Réinitialiser'),
                  ),
                ),
            ],
          ),
        ),
      ],
    );
  }

  static String _channelTitle(List<Channel> channels, int id) {
    for (final Channel channel in channels) {
      if (channel.id == id) return channel.title;
    }
    return 'Canal $id';
  }
}

class _GroupChip extends ConsumerWidget {
  const _GroupChip({required this.label, required this.group, required this.filters});

  final String label;
  final String group;
  final SignalFilters filters;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final bool selected = filters.group == group;
    return _Chip(
      label: label,
      selected: selected,
      onSelected: () => ref.read(signalFiltersProvider.notifier).state =
          selected ? filters.copyWith(clearGroup: true) : filters.copyWith(group: group),
    );
  }
}

class _DirectionChip extends ConsumerWidget {
  const _DirectionChip({required this.direction, required this.filters});

  final String direction;
  final SignalFilters filters;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final bool selected = filters.direction == direction;
    return _Chip(
      label: direction,
      selected: selected,
      onSelected: () => ref.read(signalFiltersProvider.notifier).state = selected
          ? filters.copyWith(clearDirection: true)
          : filters.copyWith(direction: direction),
    );
  }
}

class _Chip extends StatelessWidget {
  const _Chip({required this.label, required this.selected, required this.onSelected});

  final String label;
  final bool selected;
  final VoidCallback onSelected;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(right: AppSpacing.sm),
      child: ChoiceChip(
        label: Text(label),
        selected: selected,
        showCheckmark: false,
        onSelected: (_) => onSelected(),
        selectedColor: AppColors.primarySurface,
        labelStyle: TextStyle(
          fontSize: 12.5,
          fontWeight: selected ? FontWeight.w600 : FontWeight.w500,
          color: selected ? AppColors.primaryDark : Theme.of(context).textTheme.bodySmall?.color,
        ),
        side: BorderSide(
          color: selected ? AppColors.primary : Theme.of(context).colorScheme.outline,
        ),
      ),
    );
  }
}

/// Chip ouvrant un menu de choix (canal, instrument).
class _MenuChip<T> extends StatelessWidget {
  const _MenuChip({
    required this.icon,
    required this.label,
    required this.selected,
    required this.value,
    required this.entries,
    required this.onSelected,
  });

  final IconData icon;
  final String label;
  final bool selected;
  final T value;
  final List<({T value, String label})> entries;
  final ValueChanged<T> onSelected;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.only(right: AppSpacing.sm),
      child: PopupMenuButton<T>(
        initialValue: value,
        onSelected: onSelected,
        position: PopupMenuPosition.under,
        itemBuilder: (BuildContext context) => <PopupMenuEntry<T>>[
          for (final ({T value, String label}) entry in entries)
            PopupMenuItem<T>(value: entry.value, child: Text(entry.label)),
        ],
        child: Container(
          constraints: const BoxConstraints(maxWidth: 220),
          padding: const EdgeInsets.symmetric(horizontal: AppSpacing.md, vertical: 7),
          decoration: BoxDecoration(
            color: selected ? AppColors.primarySurface : Colors.transparent,
            borderRadius: BorderRadius.circular(AppSpacing.radiusSmall),
            border: Border.all(
              color: selected ? AppColors.primary : theme.colorScheme.outline,
            ),
          ),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: <Widget>[
              Icon(
                icon,
                size: 15,
                color: selected ? AppColors.primaryDark : theme.textTheme.bodySmall?.color,
              ),
              const SizedBox(width: 6),
              Flexible(
                child: Text(
                  label,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(
                    fontSize: 12.5,
                    fontWeight: selected ? FontWeight.w600 : FontWeight.w500,
                    color:
                        selected ? AppColors.primaryDark : theme.textTheme.bodySmall?.color,
                  ),
                ),
              ),
              const Icon(Icons.expand_more, size: 16),
            ],
          ),
        ),
      ),
    );
  }
}
