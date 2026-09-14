import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api/api_client.dart';
import '../../core/api/api_exception.dart';
import '../../core/api/endpoints.dart';
import '../../core/api/ws_client.dart';
import '../../core/connection/connection_controller.dart';

/// Niveaux de journalisation (CDC section 61).
const List<String> journalLevels = <String>['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'];

/// Catégories fonctionnelles écrites par le Bridge.
const List<String> journalCategories = <String>[
  'system',
  'signal',
  'trading',
  'risk',
  'telegram',
  'mt5',
  'ai',
  'security',
  'emergency',
  'channel',
];

/// Libellé français d'une catégorie.
String journalCategoryLabel(String? code) {
  return switch (code) {
    'system' => 'Système',
    'signal' => 'Signaux',
    'trading' => 'Trading',
    'risk' => 'Risque',
    'telegram' => 'Telegram',
    'mt5' => 'MetaTrader 5',
    'ai' => 'Intelligence artificielle',
    'security' => 'Sécurité',
    'emergency' => 'Urgence',
    'channel' => 'Canaux',
    _ => code ?? '--',
  };
}

/// Filtres du journal : niveau et catégorie.
@immutable
class JournalFilter {
  const JournalFilter({this.level, this.category});

  final String? level;
  final String? category;

  JournalFilter withLevel(String? value) => JournalFilter(level: value, category: category);

  JournalFilter withCategory(String? value) => JournalFilter(level: level, category: value);

  @override
  bool operator ==(Object other) =>
      other is JournalFilter && other.level == level && other.category == category;

  @override
  int get hashCode => Object.hash(level, category);
}

/// État de la liste paginée du journal.
@immutable
class JournalState {
  const JournalState({
    this.items = const <Map<String, dynamic>>[],
    this.loading = true,
    this.loadingMore = false,
    this.hasMore = true,
    this.errorMessage,
    this.errorTechnical,
  });

  final List<Map<String, dynamic>> items;
  final bool loading;
  final bool loadingMore;
  final bool hasMore;
  final String? errorMessage;
  final String? errorTechnical;

  bool get isEmpty => !loading && errorMessage == null && items.isEmpty;
}

/// Journal paginé, complété en temps réel par l'événement WebSocket `journal`.
class JournalController extends StateNotifier<JournalState> {
  JournalController({required ApiClient api, required WsClient ws, required this.filter})
      : _api = api,
        super(const JournalState()) {
    _subscription = ws.on(<String>{BridgeEvents.journal}).listen(_onLiveEntry);
    unawaited(refresh());
  }

  static const int _pageSize = 50;

  final ApiClient _api;
  final JournalFilter filter;
  StreamSubscription<BridgeEvent>? _subscription;

  Map<String, dynamic> get _query => <String, dynamic>{
        'limit': _pageSize,
        if (filter.level != null) 'level': filter.level,
        if (filter.category != null) 'category': filter.category,
      };

  Future<void> refresh() async {
    state = const JournalState();
    try {
      final Map<String, dynamic> payload = await _api.getJson(
        Endpoints.journal,
        query: <String, dynamic>{..._query, 'offset': 0},
      );
      final List<Map<String, dynamic>> items = _items(payload);
      state = JournalState(
        items: items,
        loading: false,
        hasMore: items.length >= _pageSize,
      );
    } on ApiException catch (error) {
      state = JournalState(
        loading: false,
        hasMore: false,
        errorMessage: error.message,
        errorTechnical: error.technical,
      );
    }
  }

  /// Charge la page suivante quand l'utilisateur atteint le bas de la liste.
  Future<void> loadMore() async {
    if (state.loading || state.loadingMore || !state.hasMore) return;
    state = JournalState(
      items: state.items,
      loading: false,
      loadingMore: true,
      hasMore: state.hasMore,
    );
    try {
      final Map<String, dynamic> payload = await _api.getJson(
        Endpoints.journal,
        query: <String, dynamic>{..._query, 'offset': state.items.length},
      );
      final List<Map<String, dynamic>> page = _items(payload);
      state = JournalState(
        items: <Map<String, dynamic>>[...state.items, ...page],
        loading: false,
        hasMore: page.length >= _pageSize,
      );
    } on ApiException catch (error) {
      state = JournalState(
        items: state.items,
        loading: false,
        hasMore: false,
        errorMessage: error.message,
        errorTechnical: error.technical,
      );
    }
  }

  /// Insère en tête une entrée poussée par le Bridge, si elle passe les filtres.
  void _onLiveEntry(BridgeEvent event) {
    final Map<String, dynamic> entry = event.data;
    if (entry.isEmpty) return;
    if (filter.level != null && entry['level'] != filter.level) return;
    if (filter.category != null && entry['category'] != filter.category) return;
    if (state.items.any((Map<String, dynamic> item) =>
        item['id'] != null && item['id'] == entry['id'])) {
      return;
    }
    state = JournalState(
      items: <Map<String, dynamic>>[entry, ...state.items],
      loading: false,
      loadingMore: state.loadingMore,
      hasMore: state.hasMore,
      errorMessage: state.errorMessage,
      errorTechnical: state.errorTechnical,
    );
  }

  static List<Map<String, dynamic>> _items(Map<String, dynamic> payload) {
    final Object? raw = payload['items'];
    if (raw is! List) return const <Map<String, dynamic>>[];
    return raw
        .whereType<Map<dynamic, dynamic>>()
        .map((Map<dynamic, dynamic> row) => Map<String, dynamic>.from(row))
        .toList(growable: false);
  }

  @override
  void dispose() {
    _subscription?.cancel();
    _subscription = null;
    super.dispose();
  }
}

final StateProvider<JournalFilter> journalFilterProvider =
    StateProvider<JournalFilter>((Ref ref) => const JournalFilter());

final AutoDisposeStateNotifierProvider<JournalController, JournalState> journalProvider =
    StateNotifierProvider.autoDispose<JournalController, JournalState>((Ref ref) {
  return JournalController(
    api: ref.watch(apiClientProvider),
    ws: ref.watch(wsClientProvider),
    filter: ref.watch(journalFilterProvider),
  );
});

/// Journal d'audit : actions sensibles uniquement (`GET /api/v1/journal/audit`).
final AutoDisposeFutureProvider<List<Map<String, dynamic>>> journalAuditProvider =
    FutureProvider.autoDispose<List<Map<String, dynamic>>>((Ref ref) async {
  final Map<String, dynamic> payload = await ref.watch(apiClientProvider).getJson(
    Endpoints.journalAudit,
    query: <String, dynamic>{'limit': 200},
  );
  final Object? raw = payload['items'];
  if (raw is! List) return const <Map<String, dynamic>>[];
  return raw
      .whereType<Map<dynamic, dynamic>>()
      .map((Map<dynamic, dynamic> row) => Map<String, dynamic>.from(row))
      .toList(growable: false);
});
