import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/api/api_exception.dart';
import '../../../core/providers/bridge_data.dart';
import '../../../core/routing/app_router.dart';
import '../../../core/theme/app_colors.dart';
import '../../../core/theme/app_theme.dart';
import '../../../core/widgets/app_widgets.dart';
import '../settings_providers.dart';
import 'settings_shell.dart';

/// Section Données : export et import des réglages non sensibles (CDC §75).
class DataSection extends ConsumerWidget {
  const DataSection({super.key});

  Future<void> _export(BuildContext context, WidgetRef ref) async {
    Map<String, dynamic> payload;
    try {
      payload = await ref.read(settingsActionsProvider).exportSettings();
    } on ApiException catch (error) {
      if (context.mounted) showToast(context, error.message, error: true);
      return;
    }
    if (!context.mounted) return;

    final String json = const JsonEncoder.withIndent('  ').convert(payload);
    final bool? copy = await showDialog<bool>(
      context: context,
      builder: (BuildContext dialogContext) => AlertDialog(
        title: const Text('Export des réglages'),
        content: SizedBox(
          width: double.maxFinite,
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: <Widget>[
              Text(
                'Cet export ne contient aucun secret : ni clé OpenRouter, ni session Telegram, '
                'ni jeton d\'appairage.',
                style: Theme.of(dialogContext).textTheme.bodySmall,
              ),
              const SizedBox(height: AppSpacing.md),
              Flexible(
                child: SingleChildScrollView(
                  child: SelectableText(
                    json,
                    style: const TextStyle(fontFamily: 'monospace', fontSize: 12),
                  ),
                ),
              ),
            ],
          ),
        ),
        actions: <Widget>[
          TextButton(
            onPressed: () => Navigator.of(dialogContext).pop(false),
            style: TextButton.styleFrom(foregroundColor: AppColors.textSecondary),
            child: const Text('Fermer'),
          ),
          FilledButton(
            onPressed: () => Navigator.of(dialogContext).pop(true),
            child: const Text('Copier'),
          ),
        ],
      ),
    );

    if (copy == true) {
      await Clipboard.setData(ClipboardData(text: json));
      if (context.mounted) showToast(context, 'Export copié dans le presse-papiers.');
    }
  }

  Future<void> _import(BuildContext context, WidgetRef ref) async {
    final String? raw = await showDialog<String>(
      context: context,
      builder: (BuildContext dialogContext) => const _ImportDialog(),
    );
    if (raw == null || !context.mounted) return;

    Map<String, dynamic> payload;
    try {
      final Object? decoded = jsonDecode(raw);
      if (decoded is! Map) throw const FormatException();
      payload = Map<String, dynamic>.from(decoded);
    } on FormatException {
      showToast(context, 'Le texte collé n\'est pas un export valide.', error: true);
      return;
    }

    final bool ok = await confirmAction(
      context,
      title: 'Importer ces réglages',
      message: 'Les réglages de risque et les correspondances de symboles seront remplacés par '
          'ceux de l\'export. Le trading automatique et le mode d\'exécution ne sont jamais '
          'restaurés.',
      confirmLabel: 'Importer',
    );
    if (!ok || !context.mounted) return;

    Map<String, dynamic> result;
    try {
      result = await ref.read(settingsActionsProvider).importSettings(payload);
    } on ApiException catch (error) {
      if (context.mounted) showToast(context, error.message, error: true);
      return;
    }
    refreshBridgeData(ref);
    ref.invalidate(riskSettingsProvider);
    if (context.mounted) {
      showToast(
        context,
        '${result['importedSettings'] ?? 0} réglage(s) et '
        '${result['importedMappings'] ?? 0} correspondance(s) importés.',
      );
    }
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return SettingsSection(
      title: 'Données',
      subtitle: 'Sauvegarder ou restaurer la configuration, sans jamais toucher aux secrets.',
      children: <Widget>[
        const SettingsNote(
          text: 'L\'export contient les réglages de risque et les correspondances de symboles. '
              'Il ne contient AUCUN secret : ni clé API, ni session Telegram, ni identifiants '
              'MetaTrader. Un import ne restaure jamais le trading automatique ni le mode '
              'd\'exécution : ces deux réglages restent des décisions manuelles.',
        ),
        Row(
          children: <Widget>[
            Expanded(
              child: OutlinedButton.icon(
                onPressed: () => _export(context, ref),
                icon: const Icon(Icons.download_outlined, size: 18),
                label: const Text('Exporter'),
              ),
            ),
            const SizedBox(width: AppSpacing.md),
            Expanded(
              child: OutlinedButton.icon(
                onPressed: () => _import(context, ref),
                icon: const Icon(Icons.upload_outlined, size: 18),
                label: const Text('Importer'),
              ),
            ),
          ],
        ),
      ],
    );
  }
}

class _ImportDialog extends StatefulWidget {
  const _ImportDialog();

  @override
  State<_ImportDialog> createState() => _ImportDialogState();
}

class _ImportDialogState extends State<_ImportDialog> {
  final TextEditingController _controller = TextEditingController();

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('Importer des réglages'),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Text(
            'Collez ici le contenu d\'un export TradePilot.',
            style: Theme.of(context).textTheme.bodySmall,
          ),
          const SizedBox(height: AppSpacing.md),
          TextField(
            controller: _controller,
            maxLines: 8,
            minLines: 4,
            autocorrect: false,
            decoration: const InputDecoration(hintText: '{ "risk": { ... } }'),
            onChanged: (_) => setState(() {}),
          ),
        ],
      ),
      actions: <Widget>[
        TextButton(
          onPressed: () => Navigator.of(context).pop(),
          style: TextButton.styleFrom(foregroundColor: AppColors.textSecondary),
          child: const Text('Annuler'),
        ),
        FilledButton(
          onPressed: _controller.text.trim().isEmpty
              ? null
              : () => Navigator.of(context).pop(_controller.text.trim()),
          child: const Text('Continuer'),
        ),
      ],
    );
  }
}

/// Section Logs : consultation du journal et purge des anciennes entrées.
class LogsSection extends ConsumerWidget {
  const LogsSection({super.key});

  Future<void> _purge(BuildContext context, WidgetRef ref) async {
    final bool ok = await confirmAction(
      context,
      title: 'Purger le journal',
      message: 'Les entrées les plus anciennes seront supprimées définitivement. Les 5 000 '
          'entrées les plus récentes sont conservées. Le journal d\'audit n\'est pas touché.',
      confirmLabel: 'Purger',
      destructive: true,
    );
    if (!ok || !context.mounted) return;

    Map<String, dynamic> result;
    try {
      result = await ref.read(settingsActionsProvider).purgeJournal();
    } on ApiException catch (error) {
      if (context.mounted) showToast(context, error.message, error: true);
      return;
    }
    if (context.mounted) {
      showToast(context, '${result['removed'] ?? 0} entrée(s) supprimée(s).');
    }
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return SettingsSection(
      title: 'Logs',
      subtitle: 'Tout ce que le Bridge a fait, dans l\'ordre.',
      children: <Widget>[
        ListTile(
          contentPadding: EdgeInsets.zero,
          leading: const Icon(Icons.receipt_long_outlined),
          title: const Text('Ouvrir le journal'),
          subtitle: const Text('Signaux, ordres, erreurs et décisions du moteur de risque.'),
          trailing: const Icon(Icons.chevron_right, size: 20),
          onTap: () => context.push(Routes.journal),
        ),
        const SettingsNote(
          text: 'Purger le journal libère de l\'espace sur le PC, mais efface l\'historique des '
              'événements les plus anciens. Le journal d\'audit des actions sensibles est '
              'conservé.',
        ),
        SizedBox(
          width: double.infinity,
          child: OutlinedButton.icon(
            onPressed: () => _purge(context, ref),
            icon: const Icon(Icons.delete_sweep_outlined, size: 18),
            label: const Text('Purger les anciennes entrées'),
          ),
        ),
      ],
    );
  }
}
