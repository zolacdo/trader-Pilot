import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/theme/app_colors.dart';
import '../../core/theme/app_theme.dart';
import '../../core/utils/formatters.dart';
import '../../core/widgets/app_widgets.dart';
import 'ai_analysis_controller.dart';
import 'widgets/ai_result_card.dart';

/// Analyse IA d'une capture d'écran de graphique (CDC section 22).
///
/// Écran strictement informatif : il ne comporte volontairement aucun bouton
/// permettant de trader, de copier ou d'exécuter le scénario décrit.
class AiAnalysisScreen extends ConsumerStatefulWidget {
  const AiAnalysisScreen({super.key});

  @override
  ConsumerState<AiAnalysisScreen> createState() => _AiAnalysisScreenState();
}

class _AiAnalysisScreenState extends ConsumerState<AiAnalysisScreen> {
  final TextEditingController _instrument = TextEditingController();
  final TextEditingController _question = TextEditingController();

  @override
  void dispose() {
    _instrument.dispose();
    _question.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final AiAnalysisState state = ref.watch(aiAnalysisProvider);
    final AiAnalysisController controller = ref.read(aiAnalysisProvider.notifier);

    return Scaffold(
      appBar: AppBar(
        title: const Text('Analyse IA'),
        actions: <Widget>[
          IconButton(
            tooltip: 'Historique de la session',
            onPressed: () => _openHistory(context, state, controller),
            icon: const Icon(Icons.history),
          ),
        ],
      ),
      body: ListView(
        padding: AppSpacing.page,
        children: <Widget>[
          const _InformativeNotice(),
          const SizedBox(height: AppSpacing.lg),
          _ImagePickerCard(state: state, controller: controller),
          const SizedBox(height: AppSpacing.lg),
          AppCard(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: <Widget>[
                const SectionHeader(
                  title: 'Contexte facultatif',
                  subtitle: 'Ces champs aident le modèle, ils ne sont pas obligatoires.',
                ),
                TextField(
                  controller: _instrument,
                  textCapitalization: TextCapitalization.characters,
                  decoration: const InputDecoration(
                    labelText: 'Instrument',
                    hintText: 'XAUUSD, EURUSD, US30…',
                  ),
                ),
                const SizedBox(height: AppSpacing.md),
                TextField(
                  controller: _question,
                  maxLines: 3,
                  maxLength: 400,
                  decoration: const InputDecoration(
                    labelText: 'Question libre',
                    hintText: 'Quelle structure est visible sur cette unité de temps ?',
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(height: AppSpacing.lg),
          FilledButton.icon(
            onPressed: state.canSend
                ? () => controller.analyze(
                      instrument: _instrument.text,
                      question: _question.text,
                    )
                : null,
            icon: state.sending
                ? const SizedBox(
                    width: 18,
                    height: 18,
                    child: CircularProgressIndicator(strokeWidth: 2.2, color: Colors.white),
                  )
                : const Icon(Icons.auto_awesome_outlined, size: 18),
            label: Text(state.sending ? 'Analyse en cours…' : 'Analyser l\'image'),
          ),
          if (state.errorMessage != null) ...<Widget>[
            const SizedBox(height: AppSpacing.lg),
            AppCard(
              child: ErrorView(
                message: state.errorMessage!,
                technical: state.errorTechnical,
              ),
            ),
          ],
          if (state.result != null) ...<Widget>[
            const SizedBox(height: AppSpacing.xl),
            AiResultCard(result: state.result!),
          ],
          const SizedBox(height: AppSpacing.xl),
        ],
      ),
    );
  }

  Future<void> _openHistory(
    BuildContext context,
    AiAnalysisState state,
    AiAnalysisController controller,
  ) {
    return showModalBottomSheet<void>(
      context: context,
      showDragHandle: true,
      builder: (BuildContext sheetContext) {
        if (state.history.isEmpty) {
          return const Padding(
            padding: EdgeInsets.symmetric(vertical: AppSpacing.xl),
            child: EmptyState(
              title: 'Aucune analyse',
              message: 'L\'historique ne contient que les analyses de la session en cours, '
                  'conservées en mémoire sur le téléphone.',
              icon: Icons.history,
            ),
          );
        }
        return ListView.separated(
          shrinkWrap: true,
          padding: const EdgeInsets.only(bottom: AppSpacing.xl),
          itemCount: state.history.length,
          separatorBuilder: (BuildContext context, int index) => const Divider(height: 1),
          itemBuilder: (BuildContext context, int index) {
            final AiAnalysisEntry entry = state.history[index];
            final Object? instrument = entry.result['instrument'] ?? entry.instrument;
            return ListTile(
              leading: const Icon(Icons.insights_outlined),
              title: Text('${instrument ?? 'Instrument non identifié'} · '
                  '${trendLabel(entry.result['trend']?.toString())}'),
              subtitle: Text(Fmt.full(entry.at)),
              onTap: () {
                controller.showFromHistory(entry);
                Navigator.of(sheetContext).pop();
              },
            );
          },
        );
      },
    );
  }
}

/// Rappel permanent : cet écran n'exécute rien.
class _InformativeNotice extends StatelessWidget {
  const _InformativeNotice();

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(AppSpacing.lg),
      decoration: BoxDecoration(
        color: theme.brightness == Brightness.dark
            ? AppColors.surfaceMutedDark
            : AppColors.surfaceMuted,
        borderRadius: BorderRadius.circular(AppSpacing.radius),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          const Icon(Icons.info_outline, size: 18, color: AppColors.textSecondary),
          const SizedBox(width: AppSpacing.sm),
          Expanded(
            child: Text(
              'L\'analyse d\'une capture d\'écran est informative. Elle ne déclenche aucun ordre '
              'et ne peut pas être exécutée depuis cette page.',
              style: theme.textTheme.bodySmall,
            ),
          ),
        ],
      ),
    );
  }
}

/// Import depuis la galerie ou prise de photo, avec aperçu et taille du fichier.
class _ImagePickerCard extends StatelessWidget {
  const _ImagePickerCard({required this.state, required this.controller});

  final AiAnalysisState state;
  final AiAnalysisController controller;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          const SectionHeader(
            title: 'Capture du graphique',
            subtitle: 'Format PNG, JPEG ou WebP, 4 Mo au maximum.',
          ),
          if (state.hasImage) ...<Widget>[
            ClipRRect(
              borderRadius: BorderRadius.circular(AppSpacing.radiusSmall),
              child: Image.file(
                File(state.imagePath!),
                height: 200,
                width: double.infinity,
                fit: BoxFit.contain,
                errorBuilder: (BuildContext context, Object error, StackTrace? stack) => Padding(
                  padding: const EdgeInsets.all(AppSpacing.lg),
                  child: Text('Aperçu indisponible.', style: theme.textTheme.bodySmall),
                ),
              ),
            ),
            const SizedBox(height: AppSpacing.sm),
            Row(
              children: <Widget>[
                Expanded(
                  child: Text(
                    '${state.imageName ?? 'Image sélectionnée'} · ${_readableSize(state.imageBytes)}',
                    style: theme.textTheme.bodySmall,
                    overflow: TextOverflow.ellipsis,
                  ),
                ),
                TextButton(
                  onPressed: state.sending ? null : controller.clearImage,
                  child: const Text('Retirer'),
                ),
              ],
            ),
            if (state.imageTooLarge)
              Text(
                'Cette image dépasse 4 Mo : le Bridge la refusera. Recadrez la capture.',
                style: theme.textTheme.bodySmall?.copyWith(color: AppColors.loss),
              ),
            const SizedBox(height: AppSpacing.md),
          ],
          Row(
            children: <Widget>[
              Expanded(
                child: OutlinedButton.icon(
                  onPressed: state.sending ? null : controller.pickFromGallery,
                  icon: const Icon(Icons.photo_library_outlined, size: 18),
                  label: const Text('Galerie'),
                ),
              ),
              const SizedBox(width: AppSpacing.md),
              Expanded(
                child: OutlinedButton.icon(
                  onPressed: state.sending ? null : controller.takePhoto,
                  icon: const Icon(Icons.photo_camera_outlined, size: 18),
                  label: const Text('Photo'),
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }

  static String _readableSize(int? bytes) {
    if (bytes == null) return 'taille inconnue';
    if (bytes < 1024) return '$bytes o';
    if (bytes < 1024 * 1024) return '${(bytes / 1024).toStringAsFixed(0)} Ko';
    return '${(bytes / (1024 * 1024)).toStringAsFixed(2)} Mo';
  }
}
