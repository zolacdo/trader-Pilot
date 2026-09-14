import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api/api_exception.dart';
import '../../core/api/endpoints.dart';
import '../../core/connection/connection_controller.dart';
import '../../core/theme/app_theme.dart';
import '../../core/widgets/app_widgets.dart';
import '../intelligence/labels.dart';

final FutureProviderFamily<Map<String, dynamic>, int> newsDetailProvider =
    FutureProvider.family<Map<String, dynamic>, int>((Ref ref, int id) {
  return ref.watch(apiClientProvider).getJson(Endpoints.newsDetail(id));
});

/// Détail d'une actualité : qualification, instruments touchés, doublons.
class NewsDetailScreen extends ConsumerWidget {
  const NewsDetailScreen({super.key, required this.newsId});

  final int newsId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final AsyncValue<Map<String, dynamic>> detail = ref.watch(newsDetailProvider(newsId));

    return Scaffold(
      appBar: AppBar(title: const Text('Actualité')),
      body: detail.when(
        loading: () => const LoadingView(label: 'Chargement…'),
        error: (Object error, StackTrace stack) => ErrorView(
          message: error is ApiException ? error.message : 'Actualité introuvable.',
          technical: error is ApiException ? error.technical : error.toString(),
          onRetry: () => ref.invalidate(newsDetailProvider(newsId)),
        ),
        data: (Map<String, dynamic> payload) => _Body(payload: payload),
      ),
    );
  }
}

class _Body extends StatelessWidget {
  const _Body({required this.payload});

  final Map<String, dynamic> payload;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    final Map<String, dynamic> news = Map<String, dynamic>.from(
      (payload['news'] as Map<dynamic, dynamic>?) ?? payload,
    );
    final String impact = '${news['impactLevel'] ?? ''}';
    final List<String> assets = <String>[
      ...?(news['affectedAssets'] as List<dynamic>?)?.map((dynamic e) => '$e'),
    ];
    final List<String> currencies = <String>[
      ...?(news['affectedCurrencies'] as List<dynamic>?)?.map((dynamic e) => '$e'),
    ];
    final List<Map<String, dynamic>> duplicates = <Map<String, dynamic>>[
      ...?(payload['duplicates'] as List<dynamic>?)
          ?.map((dynamic e) => Map<String, dynamic>.from(e as Map)),
    ];

    return ListView(
      padding: AppSpacing.page,
      children: <Widget>[
        AppCard(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: <Widget>[
              Text('${news['title'] ?? ''}', style: theme.textTheme.titleMedium),
              const SizedBox(height: AppSpacing.sm),
              Text(
                '${news['source'] ?? ''} · ${shortMoment('${news['publishedAt'] ?? news['receivedAt']}')}',
                style: theme.textTheme.labelSmall,
              ),
              const SizedBox(height: AppSpacing.md),
              Wrap(
                spacing: AppSpacing.sm,
                runSpacing: AppSpacing.xs,
                children: <Widget>[
                  StatusChip(
                    label: 'Impact ${labelFor(kImpactLabels, impact).toLowerCase()}',
                    tone: impactTone(impact),
                    dense: true,
                  ),
                  StatusChip(
                    label: labelFor(kSentimentLabels, '${news['sentiment']}'),
                    tone: sentimentTone('${news['sentiment']}'),
                    dense: true,
                  ),
                  StatusChip(
                    label: labelFor(kVerificationLabels, '${news['verification']}'),
                    dense: true,
                  ),
                ],
              ),
              if (news['summary'] != null) ...<Widget>[
                const SizedBox(height: AppSpacing.md),
                Text('${news['summary']}', style: theme.textTheme.bodyMedium),
              ],
            ],
          ),
        ),
        const SizedBox(height: AppSpacing.md),
        AppCard(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: <Widget>[
              const SectionHeader(title: 'Qualification'),
              DetailRow(
                label: 'Confiance de l’analyse',
                value: percentFromRatio(news['confidence']),
              ),
              DetailRow(label: 'Catégorie', value: '${news['category'] ?? '—'}'),
              DetailRow(label: 'Confirmations', value: '${news['confirmations'] ?? 1}'),
              // Ces deux lignes ne s'affichent que si la dépêche touche
              // vraiment quelque chose. Un tiret laissait croire à une donnée
              // manquante, alors que « Motif retenu » explique juste en
              // dessous qu'aucun instrument suivi n'est cité : c'est une
              // absence mesurée, pas un trou.
              if (assets.isNotEmpty)
                DetailRow(
                  label: 'Instruments touchés',
                  value: assets.join(', '),
                ),
              if (currencies.isNotEmpty)
                DetailRow(
                  label: 'Devises touchées',
                  value: currencies.join(', '),
                ),
              if (news['reason'] != null)
                DetailRow(label: 'Motif retenu', value: '${news['reason']}'),
              // Quand aucun moteur d'IA n'est intervenu, on le dit : la
              // qualification vient alors du seul vocabulaire déterministe.
              DetailRow(
                label: 'Analysé par',
                value: news['aiModel'] != null
                    ? '${news['aiProvider'] ?? 'IA'} · ${news['aiModel']}'
                    : 'Analyse déterministe (sans IA)',
              ),
            ],
          ),
        ),
        if (duplicates.isNotEmpty) ...<Widget>[
          const SizedBox(height: AppSpacing.md),
          AppCard(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: <Widget>[
                SectionHeader(
                  title: 'Reprises',
                  subtitle: '${duplicates.length} autre(s) source(s) sur le même fait',
                ),
                for (final Map<String, dynamic> item in duplicates)
                  ListTile(
                    dense: true,
                    contentPadding: EdgeInsets.zero,
                    title: Text('${item['title'] ?? ''}', style: theme.textTheme.bodySmall),
                    subtitle: Text('${item['source'] ?? ''} · ${relativeMoment('${item['receivedAt']}')}'),
                  ),
              ],
            ),
          ),
        ],
        if (news['url'] != null) ...<Widget>[
          const SizedBox(height: AppSpacing.md),
          OutlinedButton.icon(
            onPressed: () async {
              await Clipboard.setData(ClipboardData(text: '${news['url']}'));
              if (!context.mounted) return;
              showToast(context, 'Lien copié dans le presse-papiers.');
            },
            icon: const Icon(Icons.link),
            label: const Text('Copier le lien de la source'),
          ),
        ],
      ],
    );
  }
}
