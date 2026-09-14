import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api/api_client.dart';
import '../../core/api/endpoints.dart';
import '../../core/connection/connection_controller.dart';

/// Correspondance entre un nom vu dans les signaux et le symbole du broker.
class SymbolMapping {
  const SymbolMapping({
    required this.id,
    required this.alias,
    required this.canonical,
    required this.brokerSymbol,
    required this.autoDetected,
    required this.enabled,
    required this.updatedAt,
  });

  factory SymbolMapping.fromJson(Map<String, dynamic> json) {
    return SymbolMapping(
      id: json['id'] is num ? (json['id'] as num).toInt() : null,
      alias: json['alias']?.toString() ?? '--',
      canonical: json['canonical']?.toString() ?? '--',
      brokerSymbol: json['brokerSymbol']?.toString(),
      autoDetected: json['autoDetected'] == true,
      enabled: json['enabled'] != false,
      updatedAt: json['updatedAt']?.toString(),
    );
  }

  final int? id;
  final String alias;
  final String canonical;
  final String? brokerSymbol;
  final bool autoDetected;
  final bool enabled;
  final String? updatedAt;
}

final AutoDisposeFutureProvider<List<SymbolMapping>> symbolMappingsProvider =
    FutureProvider.autoDispose<List<SymbolMapping>>((Ref<Object?> ref) async {
  final List<dynamic> raw = await ref.watch(apiClientProvider).getList(Endpoints.symbolMappings);
  return raw
      .whereType<Map<dynamic, dynamic>>()
      .map((Map<dynamic, dynamic> item) => SymbolMapping.fromJson(Map<String, dynamic>.from(item)))
      .toList(growable: false);
});

/// Symboles réellement disponibles chez le broker pour un instrument donné.
final AutoDisposeFutureProviderFamily<List<String>, String> symbolSuggestionsProvider =
    FutureProvider.autoDispose.family<List<String>, String>((Ref<Object?> ref, String canonical) async {
  if (canonical.trim().isEmpty) return const <String>[];
  final Map<String, dynamic> payload =
      await ref.watch(apiClientProvider).getJson(Endpoints.symbolSuggestions(canonical.trim()));
  final Object? suggestions = payload['suggestions'];
  if (suggestions is! List) return const <String>[];
  return suggestions.map((Object? item) => item.toString()).toList(growable: false);
});

/// Écritures sur les correspondances.
class SymbolMappingActions {
  const SymbolMappingActions(this._api);

  final ApiClient _api;

  Future<void> upsert({
    required String alias,
    required String canonical,
    String? brokerSymbol,
  }) async {
    await _api.putJson(
      Endpoints.symbolMappings,
      body: <String, dynamic>{
        'alias': alias,
        'canonical': canonical,
        'brokerSymbol': brokerSymbol,
      },
    );
  }

  Future<void> delete(int id) async {
    await _api.deleteJson(Endpoints.symbolMapping(id));
  }
}

final AutoDisposeProvider<SymbolMappingActions> symbolMappingActionsProvider =
    Provider.autoDispose<SymbolMappingActions>(
  (Ref<Object?> ref) => SymbolMappingActions(ref.watch(apiClientProvider)),
);
