import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api/api_exception.dart';
import '../../core/theme/app_theme.dart';
import '../../core/utils/formatters.dart';
import '../../core/widgets/app_widgets.dart';
import 'symbol_mapping_providers.dart';
import 'widgets/symbol_mapping_editor.dart';

/// Correspondance des symboles (CDC section 54).
///
/// Un canal écrit « GOLD », TradePilot travaille avec « XAUUSD », et le broker
/// expose peut-être « XAUUSDm » ou « XAUUSD.r ». Cette page relie les trois.
class SymbolMappingScreen extends ConsumerWidget {
  const SymbolMappingScreen({super.key});

  Future<void> _openEditor(BuildContext context, WidgetRef ref, {SymbolMapping? existing}) async {
    final bool saved = await showSymbolMappingEditor(context, existing: existing);
    if (saved) {
      ref.invalidate(symbolMappingsProvider);
      if (context.mounted) showToast(context, 'Correspondance enregistrée.');
    }
  }

  Future<void> _delete(BuildContext context, WidgetRef ref, SymbolMapping mapping) async {
    final int? id = mapping.id;
    if (id == null) return;
    final bool ok = await confirmAction(
      context,
      title: 'Supprimer la correspondance',
      message: '« ${mapping.alias} » ne sera plus relié à ${mapping.canonical}. Les signaux qui '
          'utilisent ce nom risquent d\'être refusés faute d\'instrument reconnu.',
      confirmLabel: 'Supprimer',
      destructive: true,
    );
    if (!ok) return;
    try {
      await ref.read(symbolMappingActionsProvider).delete(id);
    } on ApiException catch (error) {
      if (context.mounted) showToast(context, error.message, error: true);
      return;
    }
    ref.invalidate(symbolMappingsProvider);
    if (context.mounted) showToast(context, 'Correspondance supprimée.');
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final AsyncValue<List<SymbolMapping>> mappings = ref.watch(symbolMappingsProvider);

    return Scaffold(
      appBar: AppBar(title: const Text('Correspondance des symboles')),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: () => _openEditor(context, ref),
        icon: const Icon(Icons.add),
        label: const Text('Ajouter'),
      ),
      body: RefreshIndicator(
        onRefresh: () async {
          ref.invalidate(symbolMappingsProvider);
          await ref.read(symbolMappingsProvider.future);
        },
        child: mappings.when(
          loading: () => const LoadingView(label: 'Lecture des correspondances…'),
          error: (Object error, StackTrace stack) => ErrorView(
            message: error is ApiException ? error.message : 'Correspondances indisponibles.',
            technical: error is ApiException ? error.technical : error.toString(),
            onRetry: () => ref.invalidate(symbolMappingsProvider),
          ),
          data: (List<SymbolMapping> items) => ListView(
            padding: const EdgeInsets.fromLTRB(
                AppSpacing.lg, AppSpacing.lg, AppSpacing.lg, AppSpacing.xxl * 2),
            physics: const AlwaysScrollableScrollPhysics(),
            children: <Widget>[
              const _WhyCard(),
              const SizedBox(height: AppSpacing.lg),
              if (items.isEmpty)
                const EmptyState(
                  title: 'Aucune correspondance enregistrée',
                  message: 'Le Bridge tente de reconnaître les instruments tout seul. Ajoutez une '
                      'correspondance dès qu\'un nom de signal n\'est pas retrouvé chez le broker.',
                  icon: Icons.swap_horiz,
                )
              else
                for (final SymbolMapping mapping in items) ...<Widget>[
                  _MappingCard(
                    mapping: mapping,
                    onEdit: () => _openEditor(context, ref, existing: mapping),
                    onDelete: () => _delete(context, ref, mapping),
                  ),
                  const SizedBox(height: AppSpacing.md),
                ],
            ],
          ),
        ),
      ),
    );
  }
}

class _WhyCard extends StatelessWidget {
  const _WhyCard();

  @override
  Widget build(BuildContext context) {
    return const AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          SectionHeader(
            title: 'Pourquoi cette page existe',
            subtitle: 'Les brokers ne nomment pas les instruments de la même façon.',
          ),
          Text(
            'Un canal annonce « GOLD ». TradePilot ramène ce nom au standard « XAUUSD ». Mais chez '
            'Exness, l\'instrument peut s\'appeler « XAUUSDm » ou « XAUUSD.r » selon le type de '
            'compte. Sans correspondance exacte, l\'ordre est refusé : le symbole demandé n\'existe '
            'tout simplement pas.\n\n'
            'TradePilot ne devine jamais à l\'aveugle : les propositions ci-dessous viennent de la '
            'liste réelle des symboles du compte connecté.',
          ),
        ],
      ),
    );
  }
}

class _MappingCard extends StatelessWidget {
  const _MappingCard({required this.mapping, required this.onEdit, required this.onDelete});

  final SymbolMapping mapping;
  final VoidCallback onEdit;
  final VoidCallback onDelete;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Row(
            children: <Widget>[
              Expanded(
                child: Text(mapping.alias, style: theme.textTheme.titleMedium),
              ),
              if (mapping.autoDetected)
                const StatusChip(
                  label: 'Détecté automatiquement',
                  tone: StatusTone.accent,
                  dense: true,
                )
              else
                const StatusChip(label: 'Défini manuellement', tone: StatusTone.neutral, dense: true),
            ],
          ),
          const SizedBox(height: AppSpacing.sm),
          Row(
            children: <Widget>[
              Expanded(child: Text('Nom du signal', style: theme.textTheme.bodySmall)),
              const Icon(Icons.arrow_forward, size: 15),
              Expanded(
                child: Text(
                  'Nom standard',
                  textAlign: TextAlign.center,
                  style: theme.textTheme.bodySmall,
                ),
              ),
              const Icon(Icons.arrow_forward, size: 15),
              Expanded(
                child: Text(
                  'Symbole broker',
                  textAlign: TextAlign.right,
                  style: theme.textTheme.bodySmall,
                ),
              ),
            ],
          ),
          const SizedBox(height: 2),
          Row(
            children: <Widget>[
              Expanded(child: Text(mapping.alias, style: theme.textTheme.bodyMedium)),
              const SizedBox(width: 15),
              Expanded(
                child: Text(
                  mapping.canonical,
                  textAlign: TextAlign.center,
                  style: theme.textTheme.bodyMedium,
                ),
              ),
              const SizedBox(width: 15),
              Expanded(
                child: Text(
                  mapping.brokerSymbol ?? '--',
                  textAlign: TextAlign.right,
                  style: theme.textTheme.bodyMedium?.copyWith(fontWeight: FontWeight.w600),
                ),
              ),
            ],
          ),
          const SizedBox(height: AppSpacing.sm),
          const Divider(height: 1),
          DetailRow(label: 'Correspondance active', value: mapping.enabled ? 'Oui' : 'Non'),
          DetailRow(label: 'Mise à jour', value: Fmt.dayTime(mapping.updatedAt)),
          const SizedBox(height: AppSpacing.sm),
          Row(
            children: <Widget>[
              Expanded(
                child: OutlinedButton.icon(
                  onPressed: onEdit,
                  icon: const Icon(Icons.edit_outlined, size: 18),
                  label: const Text('Modifier'),
                ),
              ),
              const SizedBox(width: AppSpacing.md),
              Expanded(
                child: OutlinedButton.icon(
                  onPressed: mapping.id == null ? null : onDelete,
                  icon: const Icon(Icons.delete_outline, size: 18),
                  label: const Text('Supprimer'),
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}
