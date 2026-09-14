import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_exception.dart';
import '../../../core/theme/app_colors.dart';
import '../../../core/theme/app_theme.dart';
import '../../../core/utils/formatters.dart';
import '../../../core/widgets/app_widgets.dart';
import '../settings_providers.dart';
import 'settings_shell.dart';

/// Section OpenRouter : clé, modèles gratuits, test de connexion (CDC §19).
class OpenRouterSection extends ConsumerWidget {
  const OpenRouterSection({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final AsyncValue<Map<String, dynamic>> status = ref.watch(openrouterStatusProvider);

    return status.when(
      loading: () => const SettingsSection(
        title: 'OpenRouter',
        subtitle: 'Interprétation des signaux et analyse de graphiques.',
        children: <Widget>[SizedBox(height: 96, child: LoadingView())],
      ),
      error: (Object error, StackTrace stack) => SettingsSection(
        title: 'OpenRouter',
        subtitle: 'Interprétation des signaux et analyse de graphiques.',
        children: <Widget>[
          ErrorView(
            message: error is ApiException ? error.message : 'État OpenRouter indisponible.',
            technical: error is ApiException ? error.technical : error.toString(),
            onRetry: () => ref.invalidate(openrouterStatusProvider),
          ),
        ],
      ),
      data: (Map<String, dynamic> data) => _OpenRouterBody(status: data),
    );
  }
}

class _OpenRouterBody extends ConsumerWidget {
  const _OpenRouterBody({required this.status});

  final Map<String, dynamic> status;

  void _reload(WidgetRef ref) {
    ref.invalidate(openrouterStatusProvider);
    ref.invalidate(openrouterModelsProvider);
  }

  Future<void> _editKey(BuildContext context, WidgetRef ref) async {
    final String? key = await showDialog<String>(
      context: context,
      builder: (BuildContext dialogContext) => const _ApiKeyDialog(),
    );
    if (key == null || !context.mounted) return;
    try {
      await ref.read(settingsActionsProvider).setOpenRouterKey(key);
    } on ApiException catch (error) {
      if (context.mounted) showToast(context, error.message, error: true);
      return;
    }
    _reload(ref);
    if (context.mounted) showToast(context, 'Clé OpenRouter enregistrée.');
  }

  Future<void> _removeKey(BuildContext context, WidgetRef ref) async {
    final bool ok = await confirmAction(
      context,
      title: 'Supprimer la clé OpenRouter',
      message: 'Sans clé, les signaux ne peuvent plus être interprétés par l\'IA et l\'analyse '
          'de graphiques est indisponible.',
      confirmLabel: 'Supprimer',
      destructive: true,
    );
    if (!ok || !context.mounted) return;
    try {
      await ref.read(settingsActionsProvider).setOpenRouterKey(null);
    } on ApiException catch (error) {
      if (context.mounted) showToast(context, error.message, error: true);
      return;
    }
    _reload(ref);
    if (context.mounted) showToast(context, 'Clé supprimée.');
  }

  Future<void> _setAutoMode(BuildContext context, WidgetRef ref, bool auto) async {
    try {
      await ref.read(settingsActionsProvider).setOpenRouterModels(
            autoMode: auto,
            textModel: auto ? null : status['textModel']?.toString(),
            visionModel: auto ? null : status['visionModel']?.toString(),
          );
    } on ApiException catch (error) {
      if (context.mounted) showToast(context, error.message, error: true);
      return;
    }
    _reload(ref);
    if (context.mounted) {
      showToast(
        context,
        auto ? 'Sélection automatique activée.' : 'Sélection manuelle activée.',
      );
    }
  }

  Future<void> _pickModel(BuildContext context, WidgetRef ref, {required bool vision}) async {
    final Map<String, dynamic>? models = ref.read(openrouterModelsProvider).valueOrNull;
    final Object? raw = models == null ? null : models[vision ? 'visionModels' : 'freeModels'];
    final List<Map<String, dynamic>> options = raw is List
        ? raw
            .whereType<Map<dynamic, dynamic>>()
            .map(Map<String, dynamic>.from)
            .toList(growable: false)
        : const <Map<String, dynamic>>[];

    if (options.isEmpty) {
      showToast(context, 'Aucun modèle gratuit disponible actuellement.', error: true);
      return;
    }

    final String? chosen = await showModalBottomSheet<String>(
      context: context,
      showDragHandle: true,
      builder: (BuildContext sheetContext) => SafeArea(
        child: ListView(
          shrinkWrap: true,
          children: <Widget>[
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: AppSpacing.lg),
              child: SectionHeader(
                title: vision ? 'Modèle vision' : 'Modèle texte',
                subtitle: 'Uniquement des modèles gratuits : aucun modèle payant n\'est proposé.',
              ),
            ),
            for (final Map<String, dynamic> model in options)
              ListTile(
                title: Text(model['id']?.toString() ?? '--'),
                subtitle: Text(
                  'Contexte ${model['context'] ?? '--'} · score ${model['score'] ?? '--'}'
                  '${model['vision'] == true ? ' · vision' : ''}',
                ),
                onTap: () => Navigator.of(sheetContext).pop(model['id']?.toString()),
              ),
          ],
        ),
      ),
    );
    if (chosen == null || !context.mounted) return;

    try {
      await ref.read(settingsActionsProvider).setOpenRouterModels(
            autoMode: false,
            textModel: vision ? status['textModel']?.toString() : chosen,
            visionModel: vision ? chosen : status['visionModel']?.toString(),
          );
    } on ApiException catch (error) {
      if (context.mounted) showToast(context, error.message, error: true);
      return;
    }
    _reload(ref);
    if (context.mounted) showToast(context, 'Modèle sélectionné.');
  }

  Future<void> _test(BuildContext context, WidgetRef ref) async {
    showToast(context, 'Test en cours…');
    Map<String, dynamic> result;
    try {
      result = await ref.read(settingsActionsProvider).testOpenRouter();
    } on ApiException catch (error) {
      if (context.mounted) showToast(context, error.message, error: true);
      return;
    }
    _reload(ref);
    if (!context.mounted) return;
    final bool ok = result['ok'] == true;
    showToast(
      context,
      ok
          ? 'Modèle ${result['model'] ?? '--'} joignable en ${result['latencyMs'] ?? '--'} ms.'
          : (result['error']?.toString() ?? 'Test échoué.'),
      error: !ok,
    );
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final ThemeData theme = Theme.of(context);
    final bool configured = status['configured'] == true;
    final bool autoMode = status['autoMode'] != false;
    final String? textModel = status['textModel']?.toString();
    final String? visionModel = status['visionModel']?.toString();
    final String? lastError = status['lastError']?.toString();

    return SettingsSection(
      title: 'OpenRouter',
      subtitle: 'Sert à interpréter les signaux et à lire les graphiques.',
      children: <Widget>[
        Row(
          children: <Widget>[
            Expanded(
              child: Text(
                connectionStateLabel(status['state']?.toString()),
                style: theme.textTheme.titleMedium,
              ),
            ),
            StatusChip.connection(
              connected: status['state'] == 'CONNECTED',
              labelOverride: status['state'] == 'CONNECTED' ? 'Opérationnel' : 'Indisponible',
            ),
          ],
        ),
        const SizedBox(height: AppSpacing.sm),
        DetailRow(
          label: 'Clé enregistrée',
          value: configured ? (status['apiKeyHint']?.toString() ?? 'Enregistrée') : 'Aucune',
        ),
        DetailRow(label: 'Modèle texte actif', value: textModel ?? '--'),
        DetailRow(label: 'Modèle vision actif', value: visionModel ?? '--'),
        DetailRow(
          label: 'Tarification',
          value: textModel == null ? '--' : 'Modèle gratuit',
        ),
        DetailRow(label: 'Dernier test', value: Fmt.dayTime(status['lastTestAt'])),
        DetailRow(
          label: 'Latence mesurée',
          value: status['lastLatencyMs'] == null ? '--' : '${status['lastLatencyMs']} ms',
        ),
        if (status['circuitOpen'] == true)
          SettingsNote(
            text: 'Trop d\'échecs consécutifs : les appels sont suspendus pendant '
                '${Fmt.duration(status['circuitResetInSeconds'] is num ? (status['circuitResetInSeconds'] as num).toInt() : null)}.',
            warning: true,
          ),
        if (lastError != null && lastError.isNotEmpty)
          SettingsNote(text: 'Dernière erreur : $lastError', warning: true),
        const SizedBox(height: AppSpacing.sm),
        Row(
          children: <Widget>[
            Expanded(
              child: OutlinedButton(
                onPressed: () => _editKey(context, ref),
                child: Text(configured ? 'Remplacer la clé' : 'Saisir la clé'),
              ),
            ),
            if (configured) ...<Widget>[
              const SizedBox(width: AppSpacing.md),
              Expanded(
                child: OutlinedButton(
                  onPressed: () => _removeKey(context, ref),
                  child: const Text('Supprimer'),
                ),
              ),
            ],
          ],
        ),
        const SizedBox(height: AppSpacing.md),
        SwitchListTile(
          contentPadding: EdgeInsets.zero,
          value: autoMode,
          onChanged: configured ? (bool value) => _setAutoMode(context, ref, value) : null,
          title: Text('Choix automatique du modèle', style: theme.textTheme.titleMedium),
          subtitle: Text(
            'TradePilot teste les modèles gratuits disponibles et retient le plus fiable.',
            style: theme.textTheme.bodySmall,
          ),
        ),
        if (!autoMode) ...<Widget>[
          ListTile(
            contentPadding: EdgeInsets.zero,
            title: const Text('Modèle texte'),
            subtitle: Text(textModel ?? 'Aucun modèle sélectionné'),
            trailing: const Icon(Icons.chevron_right, size: 20),
            onTap: () => _pickModel(context, ref, vision: false),
          ),
          ListTile(
            contentPadding: EdgeInsets.zero,
            title: const Text('Modèle vision'),
            subtitle: Text(visionModel ?? 'Aucun modèle sélectionné'),
            trailing: const Icon(Icons.chevron_right, size: 20),
            onTap: () => _pickModel(context, ref, vision: true),
          ),
        ],
        const SettingsNote(
          text: 'Seuls des modèles gratuits sont listés et sélectionnés. Aucun modèle payant '
              'n\'est jamais choisi automatiquement : TradePilot ne peut pas déclencher de '
              'facturation à votre insu.',
        ),
        if (configured && textModel == null)
          const SettingsNote(
            text: 'Aucun modèle gratuit disponible actuellement. L\'interprétation automatique '
                'des signaux est suspendue : les signaux passent en validation manuelle.',
            warning: true,
          ),
        SizedBox(
          width: double.infinity,
          child: OutlinedButton.icon(
            onPressed: configured ? () => _test(context, ref) : null,
            icon: const Icon(Icons.network_check, size: 18),
            label: const Text('Tester la connexion'),
          ),
        ),
      ],
    );
  }
}

class _ApiKeyDialog extends StatefulWidget {
  const _ApiKeyDialog();

  @override
  State<_ApiKeyDialog> createState() => _ApiKeyDialogState();
}

class _ApiKeyDialogState extends State<_ApiKeyDialog> {
  final TextEditingController _controller = TextEditingController();
  bool _visible = false;

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('Clé OpenRouter'),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Text(
            'La clé est chiffrée par le Bridge et n\'est jamais réaffichée en clair : seuls ses '
            'derniers caractères servent de repère.',
            style: Theme.of(context).textTheme.bodySmall,
          ),
          const SizedBox(height: AppSpacing.lg),
          TextField(
            controller: _controller,
            obscureText: !_visible,
            autocorrect: false,
            decoration: InputDecoration(
              hintText: 'sk-or-...',
              suffixIcon: IconButton(
                icon: Icon(_visible ? Icons.visibility_off_outlined : Icons.visibility_outlined),
                onPressed: () => setState(() => _visible = !_visible),
              ),
            ),
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
          child: const Text('Enregistrer'),
        ),
      ],
    );
  }
}
