/// Lectures tolérantes du JSON renvoyé par le Bridge.
///
/// Le Bridge peut omettre un champ (MetaTrader absent, compte inconnu, aucune
/// clé OpenRouter). Aucune valeur n'est inventée ici : une donnée manquante
/// remonte à `null` et l'interface affiche « -- » ou un état vide explicite.
abstract final class Json {
  /// Sous-objet d'une réponse. Retourne une map vide plutôt que `null`.
  static Map<String, dynamic> map(Object? raw) {
    if (raw is Map<String, dynamic>) return raw;
    if (raw is Map) return Map<String, dynamic>.from(raw);
    return const <String, dynamic>{};
  }

  /// Sous-objet imbriqué : `Json.at(payload, <String>['account', 'account'])`.
  static Map<String, dynamic> at(Object? raw, List<String> path) {
    Map<String, dynamic> current = map(raw);
    for (final String key in path) {
      current = map(current[key]);
    }
    return current;
  }

  /// Liste d'objets. Les éléments non conformes sont ignorés.
  static List<Map<String, dynamic>> objects(Object? raw) {
    if (raw is! List) return const <Map<String, dynamic>>[];
    return raw.whereType<Object>().map(map).toList(growable: false);
  }

  /// Liste de chaînes non vides.
  static List<String> strings(Object? raw) {
    if (raw is! List) return const <String>[];
    return raw
        .map(text)
        .whereType<String>()
        .toList(growable: false);
  }

  /// Chaîne non vide, sinon `null`.
  static String? text(Object? raw) {
    if (raw == null) return null;
    final String value = raw.toString().trim();
    return value.isEmpty ? null : value;
  }

  static num? number(Object? raw) {
    if (raw is num) return raw;
    if (raw is String) return num.tryParse(raw.replaceAll(',', '.'));
    return null;
  }

  static int? integer(Object? raw) {
    if (raw is int) return raw;
    final num? value = number(raw);
    return value?.toInt();
  }

  /// Booléen strict : une valeur absente ou illisible vaut `false`.
  static bool flag(Object? raw) {
    if (raw is bool) return raw;
    if (raw is String) return raw.toLowerCase() == 'true';
    return false;
  }
}
