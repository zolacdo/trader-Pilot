import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_exception.dart';
import '../../../core/theme/app_colors.dart';
import '../../../core/theme/app_theme.dart';
import '../../../core/widgets/app_widgets.dart';
import '../models/channel.dart';
import '../providers/channels_providers.dart';

/// Options d'analyse choisies par l'utilisateur.
typedef AnalysisOptions = ({int messages, bool backtest});

const List<int> _messageChoices = <int>[100, 250, 500];

/// Demande le nombre de messages à analyser et l'option de simulation.
Future<AnalysisOptions?> askAnalysisOptions(BuildContext context, {required String title}) {
  return showDialog<AnalysisOptions>(
    context: context,
    builder: (BuildContext dialogContext) {
      int messages = 250;
      bool backtest = false;
      return StatefulBuilder(
        builder: (BuildContext context, StateSetter setState) {
          final ThemeData theme = Theme.of(context);
          return AlertDialog(
            title: const Text('Analyser le canal'),
            content: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: <Widget>[
                Text(
                  'Les derniers messages accessibles de « $title » sont relus pour '
                  'mesurer la qualité de ses signaux. Aucun ordre n\'est envoyé.',
                  style: theme.textTheme.bodySmall,
                ),
                const SizedBox(height: AppSpacing.lg),
                Text('Messages à analyser', style: theme.textTheme.labelSmall),
                const SizedBox(height: AppSpacing.sm),
                Wrap(
                  spacing: AppSpacing.sm,
                  children: <Widget>[
                    for (final int choice in _messageChoices)
                      ChoiceChip(
                        label: Text('$choice'),
                        selected: messages == choice,
                        showCheckmark: false,
                        selectedColor: AppColors.primarySurface,
                        onSelected: (_) => setState(() => messages = choice),
                      ),
                  ],
                ),
                const SizedBox(height: AppSpacing.sm),
                CheckboxListTile(
                  value: backtest,
                  onChanged: (bool? value) => setState(() => backtest = value ?? false),
                  contentPadding: EdgeInsets.zero,
                  controlAffinity: ListTileControlAffinity.leading,
                  title: const Text('Inclure la simulation historique'),
                  subtitle: Text(
                    'Rejoue les signaux passés sur les cours MetaTrader disponibles. '
                    'Plus long, et indicatif seulement.',
                    style: theme.textTheme.bodySmall,
                  ),
                ),
              ],
            ),
            actions: <Widget>[
              TextButton(
                onPressed: () => Navigator.of(dialogContext).pop(),
                style: TextButton.styleFrom(foregroundColor: AppColors.textSecondary),
                child: const Text('Annuler'),
              ),
              FilledButton(
                onPressed: () => Navigator.of(dialogContext)
                    .pop((messages: messages, backtest: backtest)),
                child: const Text('Analyser'),
              ),
            ],
          );
        },
      );
    },
  );
}

/// Lance l'analyse d'un canal déjà suivi et rend compte du résultat.
Future<ChannelAnalysis?> runChannelAnalysis(
  BuildContext context,
  WidgetRef ref, {
  required int channelId,
  required String title,
}) async {
  final AnalysisOptions? options = await askAnalysisOptions(context, title: title);
  if (options == null || !context.mounted) return null;

  showDialog<void>(
    context: context,
    barrierDismissible: false,
    builder: (BuildContext context) => const PopScope(
      canPop: false,
      child: AlertDialog(
        content: SizedBox(
          height: 96,
          child: LoadingView(label: 'Analyse en cours, cela peut prendre un moment…'),
        ),
      ),
    ),
  );

  try {
    final ChannelAnalysis analysis = await ref.read(channelActionsProvider).analyze(
          channelId,
          messages: options.messages,
          backtest: options.backtest,
        );
    if (!context.mounted) return analysis;
    Navigator.of(context, rootNavigator: true).pop();
    showToast(context, '${analysis.messagesScanned ?? 0} messages analysés.');
    return analysis;
  } on ApiException catch (error) {
    if (!context.mounted) return null;
    Navigator.of(context, rootNavigator: true).pop();
    showToast(context, error.message, error: true);
    return null;
  }
}
