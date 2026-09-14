import 'dart:convert';
import 'dart:io';

import 'package:drift/drift.dart';
import 'package:drift/native.dart';
import 'package:path/path.dart' as p;
import 'package:path_provider/path_provider.dart';

part 'local_database.g.dart';

/// Instantane JSON d'un ecran, conserve pour l'affichage hors ligne.
class CacheEntries extends Table {
  TextColumn get key => text()();

  TextColumn get payload => text()();

  DateTimeColumn get updatedAt => dateTime()();

  @override
  Set<Column<Object>> get primaryKey => <Column<Object>>{key};
}

/// Derniers signaux recus, consultables sans reseau.
class CachedSignals extends Table {
  IntColumn get id => integer()();

  TextColumn get symbol => text().nullable()();

  TextColumn get direction => text().nullable()();

  TextColumn get status => text()();

  RealColumn get confidence => real().withDefault(const Constant<double>(0))();

  TextColumn get payload => text()();

  DateTimeColumn get receivedAt => dateTime()();

  @override
  Set<Column<Object>> get primaryKey => <Column<Object>>{id};
}

/// Historique recent des trades.
class CachedTrades extends Table {
  IntColumn get id => integer()();

  IntColumn get ticket => integer()();

  TextColumn get symbol => text()();

  TextColumn get direction => text()();

  TextColumn get state => text()();

  RealColumn get profit => real().withDefault(const Constant<double>(0))();

  TextColumn get payload => text()();

  DateTimeColumn get openedAt => dateTime()();

  @override
  Set<Column<Object>> get primaryKey => <Column<Object>>{id};
}

/// Base locale SQLite.
///
/// Elle ne contient QUE des donnees d'affichage : aucun secret, aucun jeton.
/// Les secrets vivent dans le stockage chiffre du telephone, et tout le reste
/// reste sur le Bridge.
@DriftDatabase(tables: <Type>[CacheEntries, CachedSignals, CachedTrades])
class LocalDatabase extends _$LocalDatabase {
  LocalDatabase() : super(_open());

  LocalDatabase.forTesting(super.executor);

  @override
  int get schemaVersion => 1;

  // --- instantanes d'ecran ---
  Future<void> putSnapshot(String key, Map<String, dynamic> payload) {
    return into(cacheEntries).insertOnConflictUpdate(
      CacheEntriesCompanion.insert(
        key: key,
        payload: jsonEncode(payload),
        updatedAt: DateTime.now(),
      ),
    );
  }

  Future<({Map<String, dynamic> payload, DateTime updatedAt})?> readSnapshot(String key) async {
    final CacheEntry? row =
        await (select(cacheEntries)..where(($CacheEntriesTable t) => t.key.equals(key))).getSingleOrNull();
    if (row == null) return null;
    try {
      final Object? decoded = jsonDecode(row.payload);
      if (decoded is Map<String, dynamic>) {
        return (payload: decoded, updatedAt: row.updatedAt);
      }
    } catch (_) {
      // Un cache illisible est simplement ignore.
    }
    return null;
  }

  // --- signaux ---
  Future<void> putSignals(List<Map<String, dynamic>> signals) async {
    await batch((Batch batch) {
      for (final Map<String, dynamic> signal in signals) {
        final Object? id = signal['id'];
        if (id is! int) continue;
        batch.insert(
          cachedSignals,
          CachedSignalsCompanion.insert(
            id: Value<int>(id),
            symbol: Value<String?>(signal['normalizedSymbol']?.toString() ?? signal['symbol']?.toString()),
            direction: Value<String?>(signal['direction']?.toString()),
            status: (signal['status'] ?? 'RECEIVED').toString(),
            confidence: Value<double>((signal['confidence'] as num?)?.toDouble() ?? 0),
            payload: jsonEncode(signal),
            receivedAt: DateTime.tryParse(signal['receivedAt']?.toString() ?? '') ?? DateTime.now(),
          ),
          mode: InsertMode.insertOrReplace,
        );
      }
    });
    await _trim(cachedSignals, 300);
  }

  Future<List<Map<String, dynamic>>> readSignals({int limit = 100}) async {
    final List<CachedSignal> rows = await (select(cachedSignals)
          ..orderBy(<OrderClauseGenerator<$CachedSignalsTable>>[
            ($CachedSignalsTable t) => OrderingTerm.desc(t.receivedAt),
          ])
          ..limit(limit))
        .get();
    return rows.map((CachedSignal row) => _decode(row.payload)).whereType<Map<String, dynamic>>().toList();
  }

  // --- trades ---
  Future<void> putTrades(List<Map<String, dynamic>> trades) async {
    await batch((Batch batch) {
      for (final Map<String, dynamic> trade in trades) {
        final Object? id = trade['id'];
        if (id is! int) continue;
        batch.insert(
          cachedTrades,
          CachedTradesCompanion.insert(
            id: Value<int>(id),
            ticket: (trade['ticket'] as num?)?.toInt() ?? 0,
            symbol: (trade['symbol'] ?? '').toString(),
            direction: (trade['direction'] ?? '').toString(),
            state: (trade['state'] ?? 'CLOSED').toString(),
            profit: Value<double>(
              (trade['realizedPnl'] as num?)?.toDouble() ?? (trade['profit'] as num?)?.toDouble() ?? 0,
            ),
            payload: jsonEncode(trade),
            openedAt: DateTime.tryParse(trade['openedAt']?.toString() ?? '') ?? DateTime.now(),
          ),
          mode: InsertMode.insertOrReplace,
        );
      }
    });
    await _trim(cachedTrades, 300);
  }

  Future<List<Map<String, dynamic>>> readTrades({int limit = 100}) async {
    final List<CachedTrade> rows = await (select(cachedTrades)
          ..orderBy(<OrderClauseGenerator<$CachedTradesTable>>[
            ($CachedTradesTable t) => OrderingTerm.desc(t.openedAt),
          ])
          ..limit(limit))
        .get();
    return rows.map((CachedTrade row) => _decode(row.payload)).whereType<Map<String, dynamic>>().toList();
  }

  Future<void> clearCache() async {
    await delete(cacheEntries).go();
    await delete(cachedSignals).go();
    await delete(cachedTrades).go();
  }

  Future<void> _trim(TableInfo<Table, dynamic> table, int keep) async {
    final int total = await customSelect('SELECT COUNT(*) AS c FROM ${table.actualTableName}')
        .map((QueryRow row) => row.read<int>('c'))
        .getSingle();
    if (total <= keep) return;
    final String orderColumn = table.actualTableName == 'cached_signals' ? 'received_at' : 'opened_at';
    await customStatement(
      'DELETE FROM ${table.actualTableName} WHERE id NOT IN '
      '(SELECT id FROM ${table.actualTableName} ORDER BY $orderColumn DESC LIMIT $keep)',
    );
  }

  static Map<String, dynamic>? _decode(String raw) {
    try {
      final Object? decoded = jsonDecode(raw);
      return decoded is Map<String, dynamic> ? decoded : null;
    } catch (_) {
      return null;
    }
  }
}

QueryExecutor _open() {
  return LazyDatabase(() async {
    final Directory directory = await getApplicationDocumentsDirectory();
    final File file = File(p.join(directory.path, 'tradepilot.sqlite'));
    return NativeDatabase.createInBackground(file);
  });
}

/// Cles d'instantanes utilisees par les ecrans.
abstract final class CacheKeys {
  static const String dashboard = 'dashboard';
  static const String status = 'status';
  static const String riskSettings = 'risk_settings';
  static const String statistics = 'statistics';
  static const String channels = 'channels';
  static const String diagnostics = 'diagnostics';
}
