import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_exception.dart';
import '../../../core/theme/app_colors.dart';
import '../../../core/theme/app_theme.dart';
import '../../../core/utils/formatters.dart';
import '../../../core/widgets/app_widgets.dart';
import '../models/channel.dart';
import '../providers/channels_providers.dart';

/// Sélecteur à trois segments : OBSERVE / MANUAL / AUTO (CDC section 70).
///
/// Le passage en AUTO demande une confirmation explicite : c'est le seul mode
/// où le Bridge envoie des ordres sans intervention de l'utilisateur.
class ChannelModeSelector extends ConsumerWidget {
  const ChannelModeSelector({
    super.key,
    required this.channelId,
    required this.channelTitle,
    required this.mode,
    this.showExplanation = true,
  });

  final int channelId;
  final String channelTitle;
  final String mode;
  final bool showExplanation;

  Future<void> _change(BuildContext context, WidgetRef ref, String next) async {
    if (next == mode) return;
    if (next == ChannelModes.auto) {
      final bool confirmed = await confirmAction(
        context,
        title: 'Passer « $channelTitle » en automatique ?',
        message: 'En mode automatique, les signaux de ce canal sont exécutés sans '
            'votre confirmation, dès que toutes les protections du Bridge sont '
            'satisfaites.\n\nAucune protection n\'est contournée, mais vous ne '
            'validerez plus chaque trade.',
        confirmLabel: 'Activer l\'automatique',
      );
      if (!confirmed) return;
    }
    if (!context.mounted) return;
    try {
      await ref
          .read(channelActionsProvider)
          .updateSettings(channelId, <String, dynamic>{'mode': next});
      if (!context.mounted) return;
      showToast(context, '« $channelTitle » passe en mode ${Fmt.channelMode(next)}.');
    } on ApiException catch (error) {
      if (!context.mounted) return;
      showToast(context, error.message, error: true);
    }
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final ThemeData theme = Theme.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        SizedBox(
          width: double.infinity,
          child: SegmentedButton<String>(
            segments: const <ButtonSegment<String>>[
              ButtonSegment<String>(value: ChannelModes.observe, label: Text('Observation')),
              ButtonSegment<String>(value: ChannelModes.manual, label: Text('Manuel')),
              ButtonSegment<String>(value: ChannelModes.auto, label: Text('Auto')),
            ],
            selected: <String>{mode},
            showSelectedIcon: false,
            style: SegmentedButton.styleFrom(
              selectedBackgroundColor: AppColors.primarySurface,
              selectedForegroundColor: AppColors.primaryDark,
              textStyle: const TextStyle(fontSize: 12.5, fontWeight: FontWeight.w600),
              side: BorderSide(color: theme.colorScheme.outline),
              padding: const EdgeInsets.symmetric(horizontal: AppSpacing.sm),
            ),
            onSelectionChanged: (Set<String> selection) =>
                _change(context, ref, selection.first),
          ),
        ),
        if (showExplanation) ...<Widget>[
          const SizedBox(height: AppSpacing.sm),
          Text(ChannelModes.explain(mode), style: theme.textTheme.bodySmall),
        ],
      ],
    );
  }
}

/// Rappel de ce que font les trois modes, affiché là où l'utilisateur choisit.
class ChannelModeLegend extends StatelessWidget {
  const ChannelModeLegend({super.key});

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          const SectionHeader(
            title: 'Les trois modes',
            subtitle: 'Chaque canal fonctionne indépendamment des autres.',
          ),
          for (final String mode in ChannelModes.all)
            Padding(
              padding: const EdgeInsets.only(bottom: AppSpacing.sm),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: <Widget>[
                  StatusChip(
                    label: Fmt.channelMode(mode),
                    tone: mode == ChannelModes.auto ? StatusTone.warning : StatusTone.neutral,
                    dense: true,
                  ),
                  const SizedBox(height: AppSpacing.xs),
                  Text(ChannelModes.explain(mode), style: theme.textTheme.bodySmall),
                ],
              ),
            ),
        ],
      ),
    );
  }
}
