import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/api/api_exception.dart';
import '../../core/providers/bridge_data.dart';
import '../../core/routing/app_router.dart';
import '../../core/theme/app_theme.dart';
import '../../core/widgets/app_widgets.dart';
import 'risk_form.dart';
import 'widgets/risk_fields.dart';
import 'widgets/risk_limits_sections.dart';
import 'widgets/risk_management_sections.dart';

/// Gestion du risque (CDC section 23).
///
/// Chaque réglage est expliqué en clair : l'écran doit se comprendre sans
/// connaître le vocabulaire du trading.
class RiskScreen extends ConsumerWidget {
  const RiskScreen({super.key});

  static String executionModeLabel(String? mode) {
    return switch (mode) {
      'PAPER' => 'Paper trading',
      'MT5_DEMO' => 'MT5 démo',
      'MT5_LIVE' => 'MT5 réel',
      null => '--',
      _ => mode,
    };
  }

  Future<void> _save(BuildContext context, WidgetRef ref) async {
    final String? error = await ref.read(riskFormProvider.notifier).save();
    if (!context.mounted) return;
    if (error != null) {
      showToast(context, error, error: true);
      return;
    }
    // Les limites influencent l'accueil et l'état du moteur : on rafraîchit.
    refreshBridgeData(ref);
    ref.invalidate(riskSettingsProvider);
    showToast(context, 'Réglages de risque enregistrés.');
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final AsyncValue<RiskDraft> form = ref.watch(riskFormProvider);
    final RiskFormController controller = ref.read(riskFormProvider.notifier);
    final RiskDraft? draft = form.valueOrNull;
    final bool dirty = draft?.dirty ?? false;

    return PopScope<Object?>(
      canPop: !dirty,
      onPopInvokedWithResult: (bool didPop, Object? result) async {
        if (didPop) return;
        final bool leave = await confirmAction(
          context,
          title: 'Abandonner les modifications',
          message: 'Des réglages modifiés n\'ont pas été enregistrés. Quitter cet écran les '
              'perdra.',
          confirmLabel: 'Quitter sans enregistrer',
          cancelLabel: 'Rester',
          destructive: true,
        );
        if (leave && context.mounted) context.pop();
      },
      child: Scaffold(
        appBar: AppBar(
          title: const Text('Gestion du risque'),
          actions: <Widget>[
            IconButton(
              tooltip: 'Recharger depuis le Bridge',
              onPressed: controller.load,
              icon: const Icon(Icons.refresh),
            ),
          ],
        ),
        body: form.when(
          loading: () => const LoadingView(label: 'Lecture des réglages…'),
          error: (Object error, StackTrace stack) => ErrorView(
            message: error is ApiException ? error.message : 'Réglages de risque indisponibles.',
            technical: error is ApiException ? error.technical : error.toString(),
            onRetry: controller.load,
          ),
          data: (RiskDraft data) => _RiskForm(draft: data, controller: controller),
        ),
        bottomNavigationBar: draft == null
            ? null
            : _SaveBar(
                dirty: dirty,
                saving: draft.saving,
                onDiscard: controller.discard,
                onSave: () => _save(context, ref),
              ),
      ),
    );
  }
}

class _RiskForm extends ConsumerWidget {
  const _RiskForm({required this.draft, required this.controller});

  final RiskDraft draft;
  final RiskFormController controller;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return RefreshIndicator(
      onRefresh: controller.load,
      child: ListView(
        key: ValueKey<int>(draft.revision),
        padding: AppSpacing.page,
        physics: const AlwaysScrollableScrollPhysics(),
        children: <Widget>[
          _DelegatedSettingsCard(draft: draft),
          RiskLimitsSections(
            draft: draft,
            controller: controller,
            reference: ref.watch(riskReferenceProvider),
          ),
          RiskManagementSections(draft: draft, controller: controller),
          const RiskNote(
            text: 'Un champ laissé vide n\'efface rien : la valeur enregistrée dans le Bridge est '
                'conservée. Le Bridge vérifie lui-même les bornes de chaque réglage et refuse '
                'une valeur hors limites en expliquant pourquoi.',
          ),
          const SizedBox(height: AppSpacing.xl),
        ],
      ),
    );
  }
}

/// Rappel des trois réglages qui ne se modifient pas depuis cet écran.
class _DelegatedSettingsCard extends StatelessWidget {
  const _DelegatedSettingsCard({required this.draft});

  final RiskDraft draft;

  @override
  Widget build(BuildContext context) {
    final bool live = draft.text('executionMode') == 'MT5_LIVE';
    return Padding(
      padding: const EdgeInsets.only(bottom: AppSpacing.lg),
      child: AppCard(
        accent: live,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: <Widget>[
            const SectionHeader(
              title: 'Pilotage du trading',
              subtitle: 'Trois réglages sensibles, volontairement absents de ce formulaire.',
            ),
            DetailRow(
              label: 'Trading automatique',
              value: draft.boolean('autoTradingEnabled') ? 'Activé' : 'Désactivé',
            ),
            DetailRow(
              label: 'Mode d\'exécution',
              value: RiskScreen.executionModeLabel(draft.text('executionMode')),
            ),
            DetailRow(
              label: 'Mode réel déverrouillé',
              value: draft.boolean('liveUnlocked') ? 'Oui' : 'Non',
            ),
            const RiskNote(
              text: 'Le trading automatique, le mode d\'exécution et le déverrouillage du mode '
                  'réel ne se modifient pas ici. Ils passent par des procédures dédiées, avec '
                  'confirmation, dans les Paramètres.',
              warning: true,
            ),
            Align(
              alignment: Alignment.centerLeft,
              child: TextButton.icon(
                onPressed: () => context.push(Routes.settings),
                icon: const Icon(Icons.settings_outlined, size: 18),
                label: const Text('Ouvrir les Paramètres'),
                style: TextButton.styleFrom(padding: EdgeInsets.zero),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// Barre d'enregistrement, visible seulement quand quelque chose a changé.
class _SaveBar extends StatelessWidget {
  const _SaveBar({
    required this.dirty,
    required this.saving,
    required this.onDiscard,
    required this.onSave,
  });

  final bool dirty;
  final bool saving;
  final VoidCallback onDiscard;
  final VoidCallback onSave;

  @override
  Widget build(BuildContext context) {
    if (!dirty) return const SizedBox.shrink();
    return SafeArea(
      child: Container(
        padding: const EdgeInsets.all(AppSpacing.lg),
        decoration: BoxDecoration(
          color: Theme.of(context).cardTheme.color,
          border: Border(top: BorderSide(color: Theme.of(context).colorScheme.outline)),
        ),
        child: Row(
          children: <Widget>[
            Expanded(
              child: OutlinedButton(
                onPressed: saving ? null : onDiscard,
                child: const Text('Annuler'),
              ),
            ),
            const SizedBox(width: AppSpacing.md),
            Expanded(
              flex: 2,
              child: FilledButton(
                onPressed: saving ? null : onSave,
                child: Text(saving ? 'Enregistrement…' : 'Enregistrer les modifications'),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
