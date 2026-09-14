import '../../../core/utils/formatters.dart';

/// Lectures tolérantes des réponses JSON du Bridge.
///
/// Une valeur absente reste `null` : elle n'est jamais remplacée par une
/// valeur inventée, l'interface affiche `--`.
double? readDouble(Object? raw) {
  if (raw == null) return null;
  if (raw is num) return raw.toDouble();
  return double.tryParse(raw.toString().replaceAll(',', '.'));
}

int? readInt(Object? raw) {
  if (raw == null) return null;
  if (raw is num) return raw.toInt();
  return int.tryParse(raw.toString());
}

/// Chaîne non vide, sinon `null`.
String? readText(Object? raw) {
  if (raw == null) return null;
  final String value = raw.toString().trim();
  return value.isEmpty ? null : value;
}

bool readBool(Object? raw, {bool fallback = false}) {
  if (raw is bool) return raw;
  if (raw is num) return raw != 0;
  if (raw is String) {
    final String value = raw.trim().toLowerCase();
    if (value == 'true' || value == '1') return true;
    if (value == 'false' || value == '0') return false;
  }
  return fallback;
}

/// Date locale, `null` si le Bridge n'a rien renvoyé.
DateTime? readDate(Object? raw) => Fmt.parse(raw);

List<String> readTextList(Object? raw) {
  if (raw is! List) return const <String>[];
  return raw.map(readText).whereType<String>().toList(growable: false);
}

Map<String, dynamic> readMap(Object? raw) {
  if (raw is Map<String, dynamic>) return raw;
  if (raw is Map) return Map<String, dynamic>.from(raw);
  return const <String, dynamic>{};
}

List<Map<String, dynamic>> readMapList(Object? raw) {
  if (raw is! List) return const <Map<String, dynamic>>[];
  return raw.whereType<Object>().map(readMap).toList(growable: false);
}

/// Répartition `{clé: compte}` renvoyée par l'analyse (instruments, directions).
Map<String, int> readCounts(Object? raw) {
  final Map<String, dynamic> source = readMap(raw);
  final Map<String, int> result = <String, int>{};
  source.forEach((String key, Object? value) {
    final int? count = readInt(value);
    if (count != null) result[key] = count;
  });
  return result;
}
