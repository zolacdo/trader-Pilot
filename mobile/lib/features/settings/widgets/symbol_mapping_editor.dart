import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_exception.dart';
import '../../../core/theme/app_colors.dart';
import '../../../core/theme/app_theme.dart';
import '../../../core/widgets/app_widgets.dart';
import '../symbol_mapping_providers.dart';

/// Ouvre l'éditeur d'une correspondance (création ou modification).
///
/// Retourne `true` si quelque chose a été enregistré.
Future<bool> showSymbolMappingEditor(
  BuildContext context, {
  SymbolMapping? existing,
}) async {
  final bool? saved = await showModalBottomSheet<bool>(
    context: context,
    isScrollControlled: true,
    showDragHandle: true,
    builder: (BuildContext sheetContext) => Padding(
      padding: EdgeInsets.only(bottom: MediaQuery.of(sheetContext).viewInsets.bottom),
      child: _SymbolMappingEditor(existing: existing),
    ),
  );
  return saved ?? false;
}

class _SymbolMappingEditor extends ConsumerStatefulWidget {
  const _SymbolMappingEditor({this.existing});

  final SymbolMapping? existing;

  @override
  ConsumerState<_SymbolMappingEditor> createState() => _SymbolMappingEditorState();
}

class _SymbolMappingEditorState extends ConsumerState<_SymbolMappingEditor> {
  late final TextEditingController _alias =
      TextEditingController(text: widget.existing?.alias ?? '');
  late final TextEditingController _canonical =
      TextEditingController(text: widget.existing?.canonical ?? '');
  late final TextEditingController _broker =
      TextEditingController(text: widget.existing?.brokerSymbol ?? '');

  String _lookup = '';
  bool _saving = false;

  @override
  void initState() {
    super.initState();
    _lookup = widget.existing?.canonical ?? '';
  }

  @override
  void dispose() {
    _alias.dispose();
    _canonical.dispose();
    _broker.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    final String alias = _alias.text.trim().toUpperCase();
    final String canonical = _canonical.text.trim().toUpperCase();
    final String broker = _broker.text.trim();
    if (alias.isEmpty || canonical.isEmpty) return;

    setState(() => _saving = true);
    try {
      await ref.read(symbolMappingActionsProvider).upsert(
            alias: alias,
            canonical: canonical,
            brokerSymbol: broker.isEmpty ? null : broker,
          );
    } on ApiException catch (error) {
      if (mounted) {
        setState(() => _saving = false);
        showToast(context, error.message, error: true);
      }
      return;
    }
    if (mounted) Navigator.of(context).pop(true);
  }

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    final AsyncValue<List<String>> suggestions = _lookup.trim().isEmpty
        ? const AsyncValue<List<String>>.data(<String>[])
        : ref.watch(symbolSuggestionsProvider(_lookup.trim().toUpperCase()));

    return SafeArea(
      child: SingleChildScrollView(
        padding: const EdgeInsets.fromLTRB(AppSpacing.lg, 0, AppSpacing.lg, AppSpacing.lg),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisSize: MainAxisSize.min,
          children: <Widget>[
            SectionHeader(
              title: widget.existing == null
                  ? 'Nouvelle correspondance'
                  : 'Modifier la correspondance',
              subtitle: 'Trois noms pour un même instrument : celui du signal, le nom standard, '
                  'et celui du broker.',
            ),
            _field(
              controller: _alias,
              label: 'Nom vu dans les signaux',
              hint: 'GOLD',
              helper: 'Ce que le canal Telegram écrit réellement.',
            ),
            _field(
              controller: _canonical,
              label: 'Nom standard',
              hint: 'XAUUSD',
              helper: 'Le nom de référence utilisé par TradePilot.',
              onChanged: (String value) => setState(() => _lookup = value),
            ),
            _field(
              controller: _broker,
              label: 'Symbole chez le broker',
              hint: 'XAUUSDm',
              helper: 'Laisser vide pour laisser le Bridge le détecter automatiquement.',
              uppercase: false,
            ),
            const SizedBox(height: AppSpacing.md),
            Text('Symboles proposés par le broker', style: theme.textTheme.titleMedium),
            const SizedBox(height: AppSpacing.xs),
            Text(
              'Ces symboles existent réellement sur le compte connecté. Appuyez pour en choisir un.',
              style: theme.textTheme.bodySmall,
            ),
            const SizedBox(height: AppSpacing.sm),
            suggestions.when(
              loading: () => const Padding(
                padding: EdgeInsets.symmetric(vertical: AppSpacing.lg),
                child: LoadingView(),
              ),
              error: (Object error, StackTrace stack) => Text(
                error is ApiException ? error.message : 'Suggestions indisponibles.',
                style: theme.textTheme.bodySmall?.copyWith(color: AppColors.warning),
              ),
              data: (List<String> items) {
                if (_lookup.trim().isEmpty) {
                  return Text('Saisissez d\'abord le nom standard.',
                      style: theme.textTheme.bodySmall);
                }
                if (items.isEmpty) {
                  return Text(
                    'Aucun symbole correspondant chez le broker. Vérifiez le nom standard ou '
                    'saisissez le symbole manuellement.',
                    style: theme.textTheme.bodySmall,
                  );
                }
                return Wrap(
                  spacing: AppSpacing.sm,
                  runSpacing: AppSpacing.sm,
                  children: <Widget>[
                    for (final String symbol in items)
                      ChoiceChip(
                        label: Text(symbol),
                        selected: _broker.text.trim() == symbol,
                        onSelected: (bool selected) => setState(() {
                          _broker.text = selected ? symbol : '';
                        }),
                      ),
                  ],
                );
              },
            ),
            const SizedBox(height: AppSpacing.xl),
            SizedBox(
              width: double.infinity,
              child: FilledButton(
                onPressed: _saving ? null : _save,
                child: Text(_saving ? 'Enregistrement…' : 'Enregistrer'),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _field({
    required TextEditingController controller,
    required String label,
    required String hint,
    required String helper,
    ValueChanged<String>? onChanged,
    bool uppercase = true,
  }) {
    return Padding(
      padding: const EdgeInsets.only(bottom: AppSpacing.md),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Text(label, style: Theme.of(context).textTheme.titleMedium),
          const SizedBox(height: 2),
          Text(helper, style: Theme.of(context).textTheme.bodySmall),
          const SizedBox(height: AppSpacing.sm),
          TextField(
            controller: controller,
            autocorrect: false,
            textCapitalization:
                uppercase ? TextCapitalization.characters : TextCapitalization.none,
            decoration: InputDecoration(hintText: hint),
            onChanged: onChanged,
          ),
        ],
      ),
    );
  }
}
