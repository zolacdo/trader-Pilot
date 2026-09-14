import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api/api_client.dart';
import '../../core/api/api_exception.dart';
import '../../core/api/endpoints.dart';
import '../../core/connection/connection_controller.dart';

/// Filtres de l'écran Statistiques : période observée et mode d'exécution.
///
/// Le mode par défaut est `PAPER` : c'est le mode obligatoire au démarrage de
/// l'application, jamais une supposition sur la configuration du Bridge.
@immutable
class StatisticsFilter {
  const StatisticsFilter({this.days = 30, this.executionMode = 'PAPER'});

  final int days;
  final String executionMode;

  StatisticsFilter copyWith({int? days, String? executionMode}) {
    return StatisticsFilter(
      days: days ?? this.days,
      executionMode: executionMode ?? this.executionMode,
    );
  }

  @override
  bool operator ==(Object other) =>
      other is StatisticsFilter && other.days == days && other.executionMode == executionMode;

  @override
  int get hashCode => Object.hash(days, executionMode);
}

/// Périodes proposées (CDC section 36).
const List<int> statisticsPeriods = <int>[7, 30, 90];

/// Modes d'exécution sélectionnables, dans l'ordre de risque croissant.
const List<String> statisticsExecutionModes = <String>['PAPER', 'MT5_DEMO', 'MT5_LIVE'];

/// Libellé accentué d'un mode d'exécution.
String executionModeLabel(String? code) {
  return switch (code) {
    'PAPER' => 'Paper Trading',
    'MT5_DEMO' => 'MT5 Démo',
    'MT5_LIVE' => 'MT5 Réel',
    _ => code ?? '--',
  };
}

final StateProvider<StatisticsFilter> statisticsFilterProvider =
    StateProvider<StatisticsFilter>((Ref ref) => const StatisticsFilter());

/// `GET /api/v1/statistics` : bloc global et ventilations.
final AutoDisposeFutureProvider<Map<String, dynamic>> statisticsProvider =
    FutureProvider.autoDispose<Map<String, dynamic>>((Ref ref) {
  final StatisticsFilter filter = ref.watch(statisticsFilterProvider);
  return ref.watch(apiClientProvider).getJson(
    Endpoints.statistics,
    query: <String, dynamic>{'days': filter.days, 'executionMode': filter.executionMode},
  );
});

/// `GET /api/v1/statistics/today` : résumé de la journée en cours.
final AutoDisposeFutureProvider<Map<String, dynamic>> statisticsTodayProvider =
    FutureProvider.autoDispose<Map<String, dynamic>>((Ref ref) {
  return ref.watch(apiClientProvider).getJson(Endpoints.statisticsToday);
});

/// Noms des canaux, pour rendre la ventilation « Par canal » lisible.
///
/// Si la liste des canaux n'est pas joignable, la ventilation reste affichée
/// avec l'identifiant brut : aucune donnée n'est inventée.
final AutoDisposeFutureProvider<Map<int, String>> channelNamesProvider =
    FutureProvider.autoDispose<Map<int, String>>((Ref ref) async {
  final ApiClient api = ref.watch(apiClientProvider);
  try {
    final List<dynamic> rows = await api.getList(Endpoints.channels);
    final Map<int, String> names = <int, String>{};
    for (final dynamic row in rows) {
      if (row is! Map) continue;
      final Object? id = row['id'];
      final Object? title = row['title'];
      if (id is int && title is String && title.trim().isNotEmpty) {
        names[id] = title.trim();
      }
    }
    return names;
  } on ApiException {
    return const <int, String>{};
  }
});

// ---------------------------------------------------------------------------
// Lecture tolérante des réponses
// ---------------------------------------------------------------------------

/// Nombre lu dans une réponse. `null` reste `null` : une mesure non calculable
/// s'affiche `--` et n'est jamais remplacée par zéro.
num? statNum(Map<String, dynamic> source, String key) {
  final Object? value = source[key];
  if (value is num) return value;
  if (value is String) return num.tryParse(value);
  return null;
}

/// Liste de lignes de ventilation (`bySymbol`, `byDay`, `byHour`, `byChannel`).
List<Map<String, dynamic>> statRows(Map<String, dynamic> source, String key) {
  final Object? value = source[key];
  if (value is! List) return const <Map<String, dynamic>>[];
  return value
      .whereType<Map<dynamic, dynamic>>()
      .map((Map<dynamic, dynamic> row) => Map<String, dynamic>.from(row))
      .toList(growable: false);
}

/// Sous-objet d'une réponse (`global`).
Map<String, dynamic> statMap(Map<String, dynamic> source, String key) {
  final Object? value = source[key];
  if (value is Map) return Map<String, dynamic>.from(value);
  return const <String, dynamic>{};
}
