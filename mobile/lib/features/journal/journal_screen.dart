import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/api/api_exception.dart';
import '../../core/api/endpoints.dart';
import '../../core/connection/connection_controller.dart';
import '../../core/routing/app_router.dart';
import '../../core/theme/app_theme.dart';
import '../../core/widgets/app_widgets.dart';
import 'journal_controller.dart';
import 'widgets/journal_tiles.dart';

/// Journal des événements et journal d'audit (CDC sections 37 et 61).
class JournalScreen extends ConsumerWidget {
  const JournalScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return DefaultTabController(
      length: 2,
      child: Scaffold(
        appBar: AppBar(
          title: const Text('Journal'),
          actions: <Widget>[
            IconButton(
              tooltip: 'Copier le diagnostic',
              onPressed: () => _exportDiagnostics(context, ref),
              icon: const Icon(Icons.copy_all_outlined),
            ),
          ],
          bottom: const TabBar(
            tabs: <Widget>[
              Tab(text: 'Événements'),
              Tab(text: 'Audit'),
            ],
          ),
        ),
        body: const TabBarView(
          children: <Widget>[
            _JournalTab(),
            _AuditTab(),
          ],
        ),
      ),
    );
  }

  /// Copie l'export de diagnostic dans le presse-papiers (CDC section 61).
  Future<void> _exportDiagnostics(BuildContext context, WidgetRef ref) async {
    try {
      final Map<String, dynamic> payload =
          await ref.read(apiClientProvider).getJson(Endpoints.diagnosticsExport);
      await Clipboard.setData(
        ClipboardData(text: const JsonEncoder.withIndent('  ').convert(payload)),
      );
      if (!context.mounted) return;
      showToast(
        context,
        'Diagnostic copié dans le presse-papiers. Les secrets y sont déjà masqués par le Bridge.',
      );
    } on ApiException catch (error) {
      if (!context.mounted) return;
      showToast(context, error.message, error: true);
    }
  }
}

/// Onglet « Événements » : liste filtrée et paginée, complétée en temps réel.
class _JournalTab extends ConsumerStatefulWidget {
  const _JournalTab();

  @override
  ConsumerState<_JournalTab> createState() => _JournalTabState();
}

class _JournalTabState extends ConsumerState<_JournalTab> {
  final ScrollController _scroll = ScrollController();

  @override
  void initState() {
    super.initState();
    _scroll.addListener(_onScroll);
  }

  @override
  void dispose() {
    _scroll
      ..removeListener(_onScroll)
      ..dispose();
    super.dispose();
  }

  void _onScroll() {
    if (!_scroll.hasClients) return;
    final double remaining = _scroll.position.maxScrollExtent - _scroll.position.pixels;
    if (remaining < 400) {
      ref.read(journalProvider.notifier).loadMore();
    }
  }

  @override
  Widget build(BuildContext context) {
    final JournalState state = ref.watch(journalProvider);

    return Column(
      children: <Widget>[
        const _JournalFilters(),
        const Divider(height: 1),
        Expanded(child: _buildBody(state)),
      ],
    );
  }

  Widget _buildBody(JournalState state) {
    if (state.loading) {
      return const LoadingView(label: 'Chargement du journal…');
    }
    if (state.items.isEmpty && state.errorMessage != null) {
      return ErrorView(
        message: state.errorMessage!,
        technical: state.errorTechnical,
        onRetry: () => ref.read(journalProvider.notifier).refresh(),
      );
    }
    if (state.isEmpty) {
      return EmptyState(
        title: 'Aucun événement',
        message: 'Aucune entrée ne correspond à ces filtres.',
        icon: Icons.receipt_long_outlined,
        action: OutlinedButton(
          onPressed: () =>
              ref.read(journalFilterProvider.notifier).state = const JournalFilter(),
          child: const Text('Réinitialiser les filtres'),
        ),
      );
    }

    return RefreshIndicator(
      onRefresh: () => ref.read(journalProvider.notifier).refresh(),
      child: ListView.separated(
        controller: _scroll,
        padding: AppSpacing.page,
        itemCount: state.items.length + 1,
        separatorBuilder: (BuildContext context, int index) => const SizedBox(height: AppSpacing.sm),
        itemBuilder: (BuildContext context, int index) {
          if (index == state.items.length) {
            return _ListFooter(state: state);
          }
          return JournalTile(
            entry: state.items[index],
            onOpenSignal: (int signalId) => context.push(Routes.signalDetail(signalId)),
          );
        },
      ),
    );
  }
}

/// Pied de liste : chargement de la page suivante, fin de liste ou erreur.
class _ListFooter extends StatelessWidget {
  const _ListFooter({required this.state});

  final JournalState state;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    if (state.loadingMore) {
      return const Padding(
        padding: EdgeInsets.symmetric(vertical: AppSpacing.lg),
        child: Center(
          child: SizedBox(width: 22, height: 22, child: CircularProgressIndicator(strokeWidth: 2.2)),
        ),
      );
    }
    if (state.errorMessage != null) {
      return Padding(
        padding: const EdgeInsets.symmetric(vertical: AppSpacing.lg),
        child: Text(
          state.errorMessage!,
          textAlign: TextAlign.center,
          style: theme.textTheme.bodySmall,
        ),
      );
    }
    if (!state.hasMore) {
      return Padding(
        padding: const EdgeInsets.symmetric(vertical: AppSpacing.lg),
        child: Text(
          'Fin du journal.',
          textAlign: TextAlign.center,
          style: theme.textTheme.bodySmall,
        ),
      );
    }
    return const SizedBox(height: AppSpacing.lg);
  }
}

/// Sélecteurs de niveau et de catégorie.
class _JournalFilters extends ConsumerWidget {
  const _JournalFilters();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final JournalFilter filter = ref.watch(journalFilterProvider);
    return Padding(
      padding: const EdgeInsets.fromLTRB(AppSpacing.lg, AppSpacing.md, AppSpacing.lg, AppSpacing.md),
      child: Row(
        children: <Widget>[
          Expanded(
            child: _FilterDropdown(
              label: 'Niveau',
              value: filter.level,
              anyLabel: 'Tous les niveaux',
              options: <String, String>{
                for (final String level in journalLevels) level: level,
              },
              onChanged: (String? value) =>
                  ref.read(journalFilterProvider.notifier).state = filter.withLevel(value),
            ),
          ),
          const SizedBox(width: AppSpacing.md),
          Expanded(
            child: _FilterDropdown(
              label: 'Catégorie',
              value: filter.category,
              anyLabel: 'Toutes',
              options: <String, String>{
                for (final String category in journalCategories)
                  category: journalCategoryLabel(category),
              },
              onChanged: (String? value) =>
                  ref.read(journalFilterProvider.notifier).state = filter.withCategory(value),
            ),
          ),
        ],
      ),
    );
  }
}

class _FilterDropdown extends StatelessWidget {
  const _FilterDropdown({
    required this.label,
    required this.value,
    required this.anyLabel,
    required this.options,
    required this.onChanged,
  });

  final String label;
  final String? value;
  final String anyLabel;
  final Map<String, String> options;
  final ValueChanged<String?> onChanged;

  @override
  Widget build(BuildContext context) {
    return InputDecorator(
      decoration: InputDecoration(
        labelText: label,
        isDense: true,
        contentPadding: const EdgeInsets.symmetric(horizontal: AppSpacing.md, vertical: 10),
      ),
      child: DropdownButtonHideUnderline(
        child: DropdownButton<String?>(
          value: value,
          isExpanded: true,
          isDense: true,
          style: Theme.of(context).textTheme.bodyMedium,
          items: <DropdownMenuItem<String?>>[
            DropdownMenuItem<String?>(value: null, child: Text(anyLabel)),
            for (final MapEntry<String, String> option in options.entries)
              DropdownMenuItem<String?>(
                value: option.key,
                child: Text(option.value, overflow: TextOverflow.ellipsis),
              ),
          ],
          onChanged: onChanged,
        ),
      ),
    );
  }
}

/// Onglet « Audit » : uniquement les actions sensibles.
class _AuditTab extends ConsumerWidget {
  const _AuditTab();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final AsyncValue<List<Map<String, dynamic>>> audit = ref.watch(journalAuditProvider);

    return audit.when(
      loading: () => const LoadingView(label: 'Chargement du journal d\'audit…'),
      error: (Object error, StackTrace stack) => ErrorView(
        message: error is ApiException ? error.message : 'Journal d\'audit indisponible.',
        technical: error is ApiException ? error.technical : error.toString(),
        onRetry: () => ref.invalidate(journalAuditProvider),
      ),
      data: (List<Map<String, dynamic>> entries) {
        if (entries.isEmpty) {
          return const EmptyState(
            title: 'Aucune action sensible',
            message: 'Les ordres envoyés, changements de mode, arrêts d\'urgence et '
                'déverrouillages du mode réel apparaîtront ici.',
            icon: Icons.verified_user_outlined,
          );
        }
        return RefreshIndicator(
          onRefresh: () async => ref.invalidate(journalAuditProvider),
          child: ListView.separated(
            padding: AppSpacing.page,
            itemCount: entries.length,
            separatorBuilder: (BuildContext context, int index) =>
                const SizedBox(height: AppSpacing.sm),
            itemBuilder: (BuildContext context, int index) => AuditTile(
              entry: entries[index],
              onOpenSignal: (int signalId) => context.push(Routes.signalDetail(signalId)),
            ),
          ),
        );
      },
    );
  }
}
