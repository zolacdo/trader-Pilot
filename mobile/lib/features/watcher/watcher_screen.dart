import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api/api_exception.dart';
import '../../core/widgets/app_widgets.dart';
import 'watcher_providers.dart';

/// Comparaison des deux bandes du Market Watcher.
///
/// Le watcher publie un signal au-dessus de son seuil de score. En dessous, il
/// suit quand même ce qu'il aurait publié si le seuil avait été plus bas —
/// même bougies, même comptabilité — sans rien publier ni exécuter.
///
/// Cet écran ne sert qu'à une question : **la bande écartée valait-elle la
/// peine d'être prise ?** C'est pourquoi les deux colonnes portent les mêmes
/// mesures, dans le même ordre : l'œil compare ligne par ligne.
///
/// Aucune mesure n'est recalculée ici. Une valeur que le Bridge n'a pas pu
/// calculer reste absente et s'affiche `--`.
class WatcherBandScreen extends ConsumerWidget {
  const WatcherBandScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final AsyncValue<Map<String, dynamic>> bands = ref.watch(watcherBandsProvider);

    return Scaffold(
      appBar: AppBar(
        title: const Text('Bande mesurée'),
        actions: <Widget>[
          IconButton(
            tooltip: 'Actualiser',
            onPressed: () {
              ref.invalidate(watcherBandsProvider);
              ref.invalidate(watcherThresholdsProvider);
            },
            icon: const Icon(Icons.refresh),
          ),
        ],
      ),
      body: bands.when(
        loading: () => const LoadingView(label: 'Lecture des deux bandes…'),
        error: (Object error, StackTrace stack) => ErrorView(
          message: error is ApiException
              ? error.message
              : 'Bilan du watcher indisponible.',
          onRetry: () => ref.invalidate(watcherBandsProvider),
        ),
        data: (Map<String, dynamic> payload) => _Body(payload: payload),
      ),
    );
  }
}

class _Body extends ConsumerWidget {
  const _Body({required this.payload});

  final Map<String, dynamic> payload;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    // Le repli maximal se lit sur la courbe cumulée de toute la bande : il vit
    // donc au niveau du rapport, pas dans le bloc `overall` qui n'agrège que
    // des totaux insensibles à la chronologie.
    final Map<String, dynamic> rapportPublie = bandMap(payload, 'report');
    final Map<String, dynamic> rapportMesure = bandMap(payload, 'shadowBand');
    final Map<String, dynamic> publiee = bandMap(rapportPublie, 'overall');
    final Map<String, dynamic> mesuree = bandMap(rapportMesure, 'overall');
    final num? minimumSample = bandNum(rapportPublie, 'minimumSample');

    return ListView(
      padding: const EdgeInsets.all(16),
      children: <Widget>[
        const _PeriodSelector(),
        const SizedBox(height: 12),
        const _ThresholdPivot(),
        const SizedBox(height: 12),
        _Comparison(
          publiee: publiee,
          mesuree: mesuree,
          repliPublie: bandNum(rapportPublie, 'maxDrawdownR'),
          repliMesure: bandNum(rapportMesure, 'maxDrawdownR'),
        ),
        const SizedBox(height: 12),
        _Verdict(
          publiee: publiee,
          mesuree: mesuree,
          minimumSample: minimumSample,
        ),
      ],
    );
  }
}

/// Fenêtre observée. Les deux bandes changent ensemble : les comparer sur des
/// périodes différentes ne voudrait rien dire.
class _PeriodSelector extends ConsumerWidget {
  const _PeriodSelector();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final int selected = ref.watch(watcherBandDaysProvider);
    return Wrap(
      spacing: 8,
      children: watcherBandPeriods.map((int days) {
        return ChoiceChip(
          label: Text('$days jours'),
          selected: days == selected,
          onSelected: (bool _) =>
              ref.read(watcherBandDaysProvider.notifier).state = days,
        );
      }).toList(growable: false),
    );
  }
}

/// Le seuil est le pivot : il sépare ce qui part de ce qui est seulement suivi.
class _ThresholdPivot extends ConsumerWidget {
  const _ThresholdPivot();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final AsyncValue<Map<String, dynamic>> settings = ref.watch(watcherThresholdsProvider);
    final ThemeData theme = Theme.of(context);

    return AppCard(
      child: settings.when(
        loading: () => const Text('Lecture des seuils…'),
        error: (Object error, StackTrace stack) =>
            const Text('Seuils indisponibles : la comparaison reste lisible.'),
        data: (Map<String, dynamic> payload) {
          final Map<String, dynamic> config = bandMap(payload, 'settings');
          final num? seuil = bandNum(config, 'minimumScore');
          final num? plancher = bandNum(config, 'shadowScore');
          final String seuilTexte = seuil == null ? '--' : seuil.toStringAsFixed(0);
          final String plancherTexte = plancher == null ? '--' : plancher.toStringAsFixed(0);

          return Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: <Widget>[
              Row(
                children: <Widget>[
                  Expanded(
                    child: MetricTile(
                      label: 'Seuil de publication',
                      value: seuilTexte,
                      caption: 'au-dessus, le signal part',
                    ),
                  ),
                  Expanded(
                    child: MetricTile(
                      label: 'Plancher mesuré',
                      value: plancherTexte,
                      caption: 'en dessous, rien n\'est suivi',
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 12),
              Text(
                'Entre $plancherTexte et $seuilTexte, le watcher suit sans publier : '
                'ni message, ni ordre. C\'est cette bande que vous comparez ci-dessous.',
                style: theme.textTheme.bodySmall,
              ),
            ],
          );
        },
      ),
    );
  }
}

/// Les mêmes mesures des deux côtés, dans le même ordre.
class _Comparison extends StatelessWidget {
  const _Comparison({
    required this.publiee,
    required this.mesuree,
    required this.repliPublie,
    required this.repliMesure,
  });

  final Map<String, dynamic> publiee;
  final Map<String, dynamic> mesuree;
  final num? repliPublie;
  final num? repliMesure;

  @override
  Widget build(BuildContext context) {
    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: <Widget>[
          const SectionHeader(title: 'Publié contre écarté'),
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: <Widget>[
              Expanded(
                child: _BandColumn(
                  title: 'Publié',
                  band: publiee,
                  drawdown: repliPublie,
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: _BandColumn(
                  title: 'Écarté',
                  band: mesuree,
                  drawdown: repliMesure,
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _BandColumn extends StatelessWidget {
  const _BandColumn({required this.title, required this.band, required this.drawdown});

  final String title;
  final Map<String, dynamic> band;

  /// Repli maximal de la bande, en R. Il vient du rapport et non du bloc
  /// agrégé : seule la chronologie permet de le calculer.
  final num? drawdown;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    final num? trades = bandNum(band, 'trades');
    final num? total = bandNum(band, 'totalR');

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        Text(title, style: theme.textTheme.titleSmall),
        const SizedBox(height: 4),
        DetailRow(
          label: 'Opérations',
          value: trades == null ? '--' : trades.toString(),
          monospace: true,
        ),
        DetailRow(
          label: 'Réussite',
          value: _percent(bandNum(band, 'winRate')),
          monospace: true,
        ),
        DetailRow(
          label: 'R moyen',
          value: _signedR(bandNum(band, 'averageR')),
          valueColor: _colorFor(bandNum(band, 'averageR'), theme),
          monospace: true,
        ),
        DetailRow(
          label: 'R total',
          value: _signedR(total),
          valueColor: _colorFor(total, theme),
          monospace: true,
        ),
        DetailRow(
          label: 'Repli maximal',
          value: drawdown == null ? '--' : '-${drawdown!.toStringAsFixed(2)} R',
          valueColor: (drawdown ?? 0) > 0 ? theme.colorScheme.error : null,
          monospace: true,
        ),
        DetailRow(
          label: 'Facteur de profit',
          value: _plain(bandNum(band, 'profitFactor')),
          monospace: true,
        ),
      ],
    );
  }
}

/// Ce que la comparaison dit, en une phrase.
///
/// C'est le seul endroit de l'écran qui conclut. Sous l'échantillon minimum, il
/// dit combien il manque plutôt que de laisser croire à un verdict.
class _Verdict extends StatelessWidget {
  const _Verdict({
    required this.publiee,
    required this.mesuree,
    required this.minimumSample,
  });

  final Map<String, dynamic> publiee;
  final Map<String, dynamic> mesuree;
  final num? minimumSample;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          const SectionHeader(title: 'Ce que ça dit'),
          Text(_sentence(), style: theme.textTheme.bodyMedium),
        ],
      ),
    );
  }

  String _sentence() {
    final int minimum = minimumSample?.toInt() ?? 10;
    final int operations = bandNum(mesuree, 'trades')?.toInt() ?? 0;

    if (!bandFlag(mesuree, 'significant')) {
      final int manquantes = minimum - operations;
      if (manquantes > 0) {
        return 'Trop tôt pour conclure : $operations opération(s) mesurée(s) sur '
            'les $minimum nécessaires, il en manque $manquantes. Le watcher '
            'attend d\'en avoir assez avant de toucher à son seuil.';
      }
      return 'Trop tôt pour conclure sur la bande écartée.';
    }

    final num? mesureeR = bandNum(mesuree, 'averageR');
    final num? publieeR = bandNum(publiee, 'averageR');
    if (mesureeR == null) {
      return 'La bande écartée n\'a pas de résultat moyen mesurable.';
    }
    if (mesureeR <= 0) {
      return 'La bande écartée perd ${mesureeR.toStringAsFixed(2)} R par opération : '
          'le seuil la retient à juste titre.';
    }
    if (publieeR == null) {
      return 'La bande écartée gagne ${mesureeR.toStringAsFixed(2)} R par opération, '
          'sans comparaison possible avec le publié faute de résultat mesurable.';
    }
    if (mesureeR > publieeR) {
      return 'La bande écartée gagne ${mesureeR.toStringAsFixed(2)} R par opération, '
          'contre ${publieeR.toStringAsFixed(2)} R pour ce qui est publié. Le seuil '
          'écarte mieux que ce qu\'il garde : il va descendre d\'un point.';
    }
    return 'La bande écartée gagne ${mesureeR.toStringAsFixed(2)} R par opération, '
        'sous les ${publieeR.toStringAsFixed(2)} R du publié. Elle est rentable, '
        'mais moins : le seuil descendra prudemment, un point à la fois.';
  }
}

// ---------------------------------------------------------------------------
// Mise en forme. Une valeur absente reste `--`, jamais zéro.
// ---------------------------------------------------------------------------

String _signedR(num? value) {
  if (value == null) return '--';
  final String signe = value > 0 ? '+' : '';
  return '$signe${value.toStringAsFixed(2)} R';
}

String _percent(num? value) {
  if (value == null) return '--';
  return '${value.toStringAsFixed(0)} %';
}

String _plain(num? value) {
  if (value == null) return '--';
  return value.toStringAsFixed(2);
}

Color? _colorFor(num? value, ThemeData theme) {
  if (value == null || value == 0) return null;
  return value > 0 ? theme.colorScheme.primary : theme.colorScheme.error;
}
