import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/api/api_exception.dart';
import '../../core/routing/app_router.dart';
import '../../core/theme/app_colors.dart';
import '../../core/theme/app_theme.dart';
import '../../core/widgets/app_widgets.dart';
import 'models/discovery.dart';
import 'providers/channels_providers.dart';
import 'widgets/discover_result_card.dart';

/// Découvrir des canaux Telegram (CDC section 69).
///
/// Aucun canal n'est jamais rejoint par la recherche : elle ne fait que lire
/// des informations publiques.
class DiscoverScreen extends ConsumerStatefulWidget {
  const DiscoverScreen({super.key});

  @override
  ConsumerState<DiscoverScreen> createState() => _DiscoverScreenState();
}

class _DiscoverScreenState extends ConsumerState<DiscoverScreen> {
  final TextEditingController _controller = TextEditingController();

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  void _search(String query) {
    final String cleaned = query.trim();
    _controller.text = cleaned;
    _controller.selection = TextSelection.collapsed(offset: cleaned.length);
    ref.read(discoverQueryProvider.notifier).state = cleaned;
    FocusScope.of(context).unfocus();
  }

  @override
  Widget build(BuildContext context) {
    final AsyncValue<DiscoveryResults?> results = ref.watch(discoverResultsProvider);

    return Scaffold(
      appBar: AppBar(title: const Text('Découvrir des canaux')),
      body: Column(
        children: <Widget>[
          Padding(
            padding: const EdgeInsets.fromLTRB(AppSpacing.lg, AppSpacing.sm, AppSpacing.lg, 0),
            child: TextField(
              controller: _controller,
              textInputAction: TextInputAction.search,
              onSubmitted: _search,
              decoration: InputDecoration(
                hintText: 'Rechercher : gold signals, XAUUSD, forex…',
                prefixIcon: const Icon(Icons.search, size: 20),
                suffixIcon: IconButton(
                  icon: const Icon(Icons.arrow_forward, size: 20),
                  tooltip: 'Rechercher',
                  onPressed: () => _search(_controller.text),
                ),
              ),
            ),
          ),
          _Suggestions(onSelected: _search),
          Expanded(
            child: switch (results) {
              AsyncError(:final Object error) => _DiscoveryError(
                  error: error,
                  onRetry: () => ref.invalidate(discoverResultsProvider),
                ),
              AsyncLoading<DiscoveryResults?>() =>
                const LoadingView(label: 'Recherche sur Telegram…'),
              AsyncData<DiscoveryResults?>(value: final DiscoveryResults results) =>
                _ResultsList(results: results),
              _ => const _Introduction(),
            },
          ),
        ],
      ),
    );
  }
}

/// Suggestions de recherche renvoyées par le Bridge.
class _Suggestions extends ConsumerWidget {
  const _Suggestions({required this.onSelected});

  final ValueChanged<String> onSelected;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final List<String> suggestions =
        ref.watch(discoverSuggestionsProvider).valueOrNull ?? const <String>[];
    if (suggestions.isEmpty) return const SizedBox(height: AppSpacing.md);

    final String current = ref.watch(discoverQueryProvider);
    return SizedBox(
      height: 56,
      child: ListView(
        scrollDirection: Axis.horizontal,
        padding: const EdgeInsets.symmetric(horizontal: AppSpacing.lg, vertical: AppSpacing.sm),
        children: <Widget>[
          for (final String suggestion in suggestions)
            Padding(
              padding: const EdgeInsets.only(right: AppSpacing.sm),
              child: ChoiceChip(
                label: Text(suggestion),
                selected: current == suggestion,
                showCheckmark: false,
                selectedColor: AppColors.primarySurface,
                onSelected: (_) => onSelected(suggestion),
              ),
            ),
        ],
      ),
    );
  }
}

/// Écran d'accueil de la recherche, avant toute requête.
class _Introduction extends StatelessWidget {
  const _Introduction();

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    return ListView(
      padding: AppSpacing.page,
      children: <Widget>[
        AppCard(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: <Widget>[
              const SectionHeader(
                title: 'Trouver un canal de signaux',
                subtitle: 'Saisissez un thème, ou choisissez une suggestion.',
              ),
              const _Step(
                number: '1',
                text: 'Cherchez un canal public : gold, XAUUSD, forex, scalping, indices…',
              ),
              const _Step(
                number: '2',
                text: 'Analysez son historique pour connaître la part de messages '
                    'interprétables, la présence de SL et de TP, et la fréquence.',
              ),
              const _Step(
                number: '3',
                text: 'Ajoutez-le à votre surveillance. Il démarre toujours en mode '
                    'observation : aucun ordre n\'est envoyé.',
              ),
              const SizedBox(height: AppSpacing.md),
              Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: <Widget>[
                  const Icon(Icons.shield_outlined, size: 16, color: AppColors.primary),
                  const SizedBox(width: AppSpacing.sm),
                  Expanded(
                    child: Text(
                      'La recherche ne rejoint jamais un canal avec votre compte '
                      'Telegram : cette action reste toujours explicite.',
                      style: theme.textTheme.bodySmall,
                    ),
                  ),
                ],
              ),
            ],
          ),
        ),
      ],
    );
  }
}

class _Step extends StatelessWidget {
  const _Step({required this.number, required this.text});

  final String number;
  final String text;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.only(bottom: AppSpacing.md),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Container(
            width: 22,
            height: 22,
            alignment: Alignment.center,
            decoration: const BoxDecoration(
              color: AppColors.primarySurface,
              shape: BoxShape.circle,
            ),
            child: Text(
              number,
              style: const TextStyle(
                fontSize: 12,
                fontWeight: FontWeight.w700,
                color: AppColors.primaryDark,
              ),
            ),
          ),
          const SizedBox(width: AppSpacing.md),
          Expanded(child: Text(text, style: theme.textTheme.bodySmall)),
        ],
      ),
    );
  }
}

class _ResultsList extends StatelessWidget {
  const _ResultsList({required this.results});

  final DiscoveryResults results;

  @override
  Widget build(BuildContext context) {
    if (results.results.isEmpty) {
      return EmptyState(
        title: 'Aucun canal trouvé',
        message: 'Aucun canal public ne correspond à « ${results.query} ». '
            'Essayez un autre terme, ou le nom exact du canal.',
        icon: Icons.search_off_outlined,
      );
    }
    return ListView.separated(
      padding: AppSpacing.page,
      itemCount: results.results.length + 1,
      separatorBuilder: (BuildContext context, int index) => const SizedBox(height: AppSpacing.md),
      itemBuilder: (BuildContext context, int index) {
        if (index == 0) {
          return Text(
            '${results.results.length} canal(aux) trouvé(s) pour « ${results.query} ».',
            style: Theme.of(context).textTheme.bodySmall,
          );
        }
        return DiscoverResultCard(result: results.results[index - 1]);
      },
    );
  }
}

/// Erreurs propres à Telegram : limite de requêtes, compte non connecté.
class _DiscoveryError extends StatelessWidget {
  const _DiscoveryError({required this.error, required this.onRetry});

  final Object error;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    if (error is! ApiException) {
      return ErrorView(message: 'Recherche impossible.', onRetry: onRetry);
    }
    final ApiException exception = error as ApiException;

    if (exception.kind == ApiErrorKind.rateLimited) {
      return EmptyState(
        title: 'Telegram limite les recherches',
        message: '${exception.message}\n\nCette limite vient de Telegram : patientez '
            'le délai indiqué avant de relancer une recherche.',
        icon: Icons.hourglass_top_outlined,
        action: OutlinedButton(onPressed: onRetry, child: const Text('Réessayer')),
      );
    }

    if (exception.kind == ApiErrorKind.conflict) {
      return EmptyState(
        title: 'Compte Telegram non connecté',
        message: '${exception.message}\n\nConnectez votre compte Telegram depuis les '
            'Connexions pour rechercher des canaux.',
        icon: Icons.link_off,
        action: FilledButton(
          onPressed: () => context.push(Routes.connections),
          child: const Text('Ouvrir les Connexions'),
        ),
      );
    }

    return ErrorView(
      message: exception.message,
      technical: exception.technical,
      onRetry: onRetry,
    );
  }
}
