import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api/endpoints.dart';
import '../../core/connection/connection_controller.dart';

/// Fenêtre observée pour comparer les deux bandes, en jours.
///
/// Trente jours par défaut, comme les statistiques de trading : c'est la
/// fenêtre sur laquelle le Bridge règle aussi son apprentissage.
final StateProvider<int> watcherBandDaysProvider = StateProvider<int>((Ref ref) => 30);

/// Périodes proposées, identiques à celles de l'écran Statistiques.
const List<int> watcherBandPeriods = <int>[7, 30, 90];

/// `GET /api/v1/watcher/performance` : bande publiée et bande mesurée.
///
/// Les deux viennent de la même requête, précisément parce que c'est leur
/// comparaison qui a du sens — jamais l'une sans l'autre.
final AutoDisposeFutureProvider<Map<String, dynamic>> watcherBandsProvider =
    FutureProvider.autoDispose<Map<String, dynamic>>((Ref ref) {
  final int days = ref.watch(watcherBandDaysProvider);
  return ref.watch(apiClientProvider).getJson(
    Endpoints.watcherPerformance,
    query: <String, dynamic>{'days': days},
  );
});

/// `GET /api/v1/watcher/settings` : le seuil de publication et son plancher.
final AutoDisposeFutureProvider<Map<String, dynamic>> watcherThresholdsProvider =
    FutureProvider.autoDispose<Map<String, dynamic>>((Ref ref) {
  return ref.watch(apiClientProvider).getJson(Endpoints.watcherSettings);
});

// ---------------------------------------------------------------------------
// Lecture tolérante des réponses
// ---------------------------------------------------------------------------
// Même contrat que les lecteurs de l'écran Statistiques : une mesure que le
// Bridge n'a pas pu calculer reste `null` et s'affiche `--`. Elle n'est jamais
// remplacée par zéro, qui voudrait dire « mesuré, et nul ».

/// Nombre lu dans une réponse, ou `null` s'il est absent ou illisible.
num? bandNum(Map<String, dynamic> source, String key) {
  final Object? value = source[key];
  if (value is num) return value;
  if (value is String) return num.tryParse(value);
  return null;
}

/// Sous-objet d'une réponse (`report`, `shadowBand`, `overall`, `settings`).
Map<String, dynamic> bandMap(Map<String, dynamic> source, String key) {
  final Object? value = source[key];
  if (value is Map) return Map<String, dynamic>.from(value);
  return const <String, dynamic>{};
}

/// Booléen lu dans une réponse. Absent vaut `false` : on ne suppose pas
/// qu'un échantillon est suffisant faute de réponse.
bool bandFlag(Map<String, dynamic> source, String key) {
  return source[key] == true;
}
