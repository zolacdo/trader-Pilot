import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_exception.dart';
import '../../../core/providers/bridge_data.dart';
import '../../../core/theme/app_colors.dart';
import '../../../core/theme/app_theme.dart';
import '../../../core/widgets/app_widgets.dart';
import '../settings_providers.dart';
import 'settings_shell.dart';

/// Section Trading : interrupteur d'automatisation et mode d'exécution.
///
/// Le passage en compte réel suit une procédure en deux temps imposée par le
/// Bridge : déverrouiller, puis seulement activer (CDC section 10).
class TradingSection extends ConsumerWidget {
  const TradingSection({super.key});

  static const List<SettingsOption<String>> _modes = <SettingsOption<String>>[
    SettingsOption<String>(
      value: 'PAPER',
      label: 'Paper trading',
      description: 'Les signaux sont simulés sur un capital fictif. Aucun ordre ne quitte le '
          'Bridge. C\'est le mode d\'apprentissage.',
    ),
    SettingsOption<String>(
      value: 'MT5_DEMO',
      label: 'MetaTrader 5 — compte démo',
      description: 'Les ordres partent réellement vers MetaTrader, sur un compte de '
          'démonstration. Aucun argent réel n\'est engagé.',
    ),
    SettingsOption<String>(
      value: 'MT5_LIVE',
      label: 'MetaTrader 5 — compte réel',
      description: 'Les ordres engagent de l\'argent réel. Chaque perte est définitive.',
      warning: true,
    ),
  ];

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final AsyncValue<Map<String, dynamic>> state = ref.watch(tradingStateProvider);

    return state.when(
      loading: () => const SettingsSection(
        title: 'Trading',
        subtitle: 'Automatisation et destination des ordres.',
        children: <Widget>[SizedBox(height: 96, child: LoadingView())],
      ),
      error: (Object error, StackTrace stack) => SettingsSection(
        title: 'Trading',
        subtitle: 'Automatisation et destination des ordres.',
        children: <Widget>[
          ErrorView(
            message: error is ApiException ? error.message : 'État du trading indisponible.',
            technical: error is ApiException ? error.technical : error.toString(),
            onRetry: () => ref.invalidate(tradingStateProvider),
          ),
        ],
      ),
      data: (Map<String, dynamic> data) => _TradingBody(state: data),
    );
  }
}

class _TradingBody extends ConsumerWidget {
  const _TradingBody({required this.state});

  final Map<String, dynamic> state;

  bool get _auto => state['autoTradingEnabled'] == true;

  String? get _mode => state['executionMode']?.toString();

  bool get _liveUnlocked => state['liveUnlocked'] == true;

  Future<void> _run(BuildContext context, WidgetRef ref, Future<void> Function() action,
      String success) async {
    try {
      await action();
    } on ApiException catch (error) {
      // Le Bridge refuse (403, 400, 409) : son message est affiché tel quel.
      if (context.mounted) showToast(context, error.message, error: true);
      return;
    }
    refreshBridgeData(ref);
    if (context.mounted) showToast(context, success);
  }

  Future<void> _toggleAuto(BuildContext context, WidgetRef ref, bool enabled) async {
    if (enabled) {
      final bool ok = await confirmAction(
        context,
        title: 'Activer le trading automatique',
        message: _mode == 'MT5_LIVE'
            ? 'Le Bridge exécutera les signaux validés SANS vous demander confirmation, sur un '
                'compte réel. Les limites du moteur de risque restent la seule barrière.'
            : 'Le Bridge exécutera les signaux validés sans vous demander confirmation, en '
                '${executionModeLabel(_mode)}.',
        confirmLabel: 'Activer',
      );
      if (!ok || !context.mounted) return;
    }
    await _run(
      context,
      ref,
      () => ref.read(settingsActionsProvider).setAutoTrading(enabled),
      enabled ? 'Trading automatique activé.' : 'Trading automatique désactivé.',
    );
  }

  Future<void> _selectMode(BuildContext context, WidgetRef ref, String mode) async {
    if (mode == _mode) return;
    if (mode == 'MT5_LIVE') {
      await _goLive(context, ref);
      return;
    }
    final bool ok = await confirmAction(
      context,
      title: 'Changer de mode d\'exécution',
      message: 'Les prochains signaux seront exécutés en ${executionModeLabel(mode)}. '
          'Les positions déjà ouvertes ne sont pas déplacées.',
      confirmLabel: 'Changer',
    );
    if (!ok || !context.mounted) return;
    await _run(
      context,
      ref,
      () => ref.read(settingsActionsProvider).setExecutionMode(mode),
      'Mode d\'exécution : ${executionModeLabel(mode)}.',
    );
  }

  /// Parcours protégé vers le compte réel : explication, déverrouillage, puis
  /// activation. Chaque étape exige la phrase exacte.
  Future<void> _goLive(BuildContext context, WidgetRef ref) async {
    if (!_liveUnlocked) {
      final bool acknowledged = await showDialog<bool>(
            context: context,
            builder: (BuildContext dialogContext) => const _LiveRisksDialog(),
          ) ??
          false;
      if (!acknowledged || !context.mounted) return;

      final bool phraseOk = await confirmWithPhrase(
        context,
        title: 'Déverrouiller le mode réel',
        message: 'Le déverrouillage n\'active pas encore le mode réel : il autorise seulement '
            'son activation. Saisissez la phrase pour confirmer que vous avez lu les risques.',
        phrase: liveConfirmationPhrase,
        confirmLabel: 'Déverrouiller',
      );
      if (!phraseOk || !context.mounted) return;

      try {
        await ref.read(settingsActionsProvider).unlockLive();
      } on ApiException catch (error) {
        if (context.mounted) showToast(context, error.message, error: true);
        return;
      }
      refreshBridgeData(ref);
      if (!context.mounted) return;
    }

    final bool activate = await confirmWithPhrase(
      context,
      title: 'Passer en compte réel',
      message: 'À partir de maintenant, chaque signal exécuté engage de l\'argent réel. Une '
          'perte est définitive. Saisissez la phrase pour activer le mode réel.',
      phrase: liveConfirmationPhrase,
      confirmLabel: 'Activer le mode réel',
    );
    if (!activate || !context.mounted) return;

    await _run(
      context,
      ref,
      () => ref
          .read(settingsActionsProvider)
          .setExecutionMode('MT5_LIVE', confirmation: liveConfirmationPhrase),
      'Mode réel activé.',
    );
  }

  Future<void> _lockLive(BuildContext context, WidgetRef ref) async {
    final bool ok = await confirmAction(
      context,
      title: 'Reverrouiller le mode réel',
      message: 'Le mode réel devra être déverrouillé à nouveau, phrase de confirmation comprise, '
          'avant de pouvoir être réactivé. Si le mode réel est actif, le Bridge repasse en '
          'compte démo.',
      confirmLabel: 'Reverrouiller',
    );
    if (!ok || !context.mounted) return;
    await _run(
      context,
      ref,
      ref.read(settingsActionsProvider).lockLive,
      'Mode réel reverrouillé.',
    );
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final bool live = _mode == 'MT5_LIVE';

    return SettingsSection(
      title: 'Trading',
      subtitle: 'Automatisation et destination réelle des ordres.',
      accent: live,
      children: <Widget>[
        SwitchListTile(
          contentPadding: EdgeInsets.zero,
          value: _auto,
          onChanged: (bool value) => _toggleAuto(context, ref, value),
          title: Text('Trading automatique', style: Theme.of(context).textTheme.titleMedium),
          subtitle: Text(
            _auto
                ? 'Les signaux validés sont exécutés sans confirmation de votre part.'
                : 'Aucun signal n\'est exécuté automatiquement : tout passe par une validation '
                    'manuelle.',
            style: Theme.of(context).textTheme.bodySmall,
          ),
        ),
        if (state['paused'] == true)
          SettingsNote(
            text: 'L\'automatisation est actuellement en pause'
                '${state['pauseReason'] == null ? '' : ' : ${state['pauseReason']}'}. '
                'Aucun nouveau trade n\'est ouvert tant que la pause dure.',
            warning: true,
          ),
        const SizedBox(height: AppSpacing.md),
        Text('Mode d\'exécution', style: Theme.of(context).textTheme.titleMedium),
        const SizedBox(height: 2),
        Text(
          'Où partent réellement les ordres. C\'est le réglage le plus important de '
          'l\'application.',
          style: Theme.of(context).textTheme.bodySmall,
        ),
        const SizedBox(height: AppSpacing.sm),
        SettingsChoice<String>(
          options: TradingSection._modes,
          selected: _mode,
          onChanged: (String mode) => _selectMode(context, ref, mode),
        ),
        SettingsNote(
          text: _liveUnlocked
              ? 'Le mode réel est déverrouillé : il peut être activé après saisie de la phrase de '
                  'confirmation.'
              : 'Le mode réel est verrouillé. Le sélectionner ouvre d\'abord l\'explication des '
                  'risques, puis demande la phrase « $liveConfirmationPhrase ».',
          warning: _liveUnlocked,
        ),
        if (_liveUnlocked)
          Align(
            alignment: Alignment.centerLeft,
            child: TextButton.icon(
              onPressed: () => _lockLive(context, ref),
              icon: const Icon(Icons.lock_outline, size: 18),
              label: const Text('Reverrouiller le mode réel'),
              style: TextButton.styleFrom(
                foregroundColor: AppColors.loss,
                padding: EdgeInsets.zero,
              ),
            ),
          ),
      ],
    );
  }
}

/// Explication des risques réels, obligatoire avant tout déverrouillage.
class _LiveRisksDialog extends StatefulWidget {
  const _LiveRisksDialog();

  @override
  State<_LiveRisksDialog> createState() => _LiveRisksDialogState();
}

class _LiveRisksDialogState extends State<_LiveRisksDialog> {
  bool _acknowledged = false;

  static const List<String> _risks = <String>[
    'Chaque ordre exécuté engage votre argent. Une perte est définitive, personne ne la rembourse.',
    'Un signal peut être erroné, mal interprété ou publié par un canal peu fiable : TradePilot le '
        'copie, il ne le juge pas à votre place.',
    'Un incident technique (Bridge arrêté, MetaTrader déconnecté, coupure réseau) peut laisser une '
        'position ouverte sans surveillance.',
    'Le moteur de risque limite les dégâts, mais ne les empêche pas : un stop loss peut être '
        'franchi par un mouvement violent ou un écart de cotation.',
    'Le levier amplifie les pertes autant que les gains. Un compte peut être vidé en quelques '
        'minutes.',
  ];

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('Avant de passer en compte réel'),
      content: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: <Widget>[
            Text(
              'Lisez ces points. Ils décrivent ce qui peut réellement arriver.',
              style: Theme.of(context).textTheme.bodySmall,
            ),
            const SizedBox(height: AppSpacing.md),
            for (final String risk in _risks)
              Padding(
                padding: const EdgeInsets.only(bottom: AppSpacing.sm),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: <Widget>[
                    const Icon(Icons.warning_amber_rounded, size: 17, color: AppColors.warning),
                    const SizedBox(width: AppSpacing.sm),
                    Expanded(child: Text(risk, style: Theme.of(context).textTheme.bodyMedium)),
                  ],
                ),
              ),
            const SizedBox(height: AppSpacing.sm),
            CheckboxListTile(
              contentPadding: EdgeInsets.zero,
              value: _acknowledged,
              onChanged: (bool? value) => setState(() => _acknowledged = value ?? false),
              controlAffinity: ListTileControlAffinity.leading,
              title: const Text('J\'ai lu et j\'accepte ces risques.'),
            ),
          ],
        ),
      ),
      actions: <Widget>[
        TextButton(
          onPressed: () => Navigator.of(context).pop(false),
          style: TextButton.styleFrom(foregroundColor: AppColors.textSecondary),
          child: const Text('Annuler'),
        ),
        FilledButton(
          onPressed: _acknowledged ? () => Navigator.of(context).pop(true) : null,
          child: const Text('Continuer'),
        ),
      ],
    );
  }
}
