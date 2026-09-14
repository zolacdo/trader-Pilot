// GENERATED CODE - DO NOT MODIFY BY HAND

part of 'local_database.dart';

// ignore_for_file: type=lint
class $CacheEntriesTable extends CacheEntries
    with TableInfo<$CacheEntriesTable, CacheEntry> {
  @override
  final GeneratedDatabase attachedDatabase;
  final String? _alias;
  $CacheEntriesTable(this.attachedDatabase, [this._alias]);
  static const VerificationMeta _keyMeta = const VerificationMeta('key');
  @override
  late final GeneratedColumn<String> key = GeneratedColumn<String>(
      'key', aliasedName, false,
      type: DriftSqlType.string, requiredDuringInsert: true);
  static const VerificationMeta _payloadMeta =
      const VerificationMeta('payload');
  @override
  late final GeneratedColumn<String> payload = GeneratedColumn<String>(
      'payload', aliasedName, false,
      type: DriftSqlType.string, requiredDuringInsert: true);
  static const VerificationMeta _updatedAtMeta =
      const VerificationMeta('updatedAt');
  @override
  late final GeneratedColumn<DateTime> updatedAt = GeneratedColumn<DateTime>(
      'updated_at', aliasedName, false,
      type: DriftSqlType.dateTime, requiredDuringInsert: true);
  @override
  List<GeneratedColumn> get $columns => [key, payload, updatedAt];
  @override
  String get aliasedName => _alias ?? actualTableName;
  @override
  String get actualTableName => $name;
  static const String $name = 'cache_entries';
  @override
  VerificationContext validateIntegrity(Insertable<CacheEntry> instance,
      {bool isInserting = false}) {
    final context = VerificationContext();
    final data = instance.toColumns(true);
    if (data.containsKey('key')) {
      context.handle(
          _keyMeta, key.isAcceptableOrUnknown(data['key']!, _keyMeta));
    } else if (isInserting) {
      context.missing(_keyMeta);
    }
    if (data.containsKey('payload')) {
      context.handle(_payloadMeta,
          payload.isAcceptableOrUnknown(data['payload']!, _payloadMeta));
    } else if (isInserting) {
      context.missing(_payloadMeta);
    }
    if (data.containsKey('updated_at')) {
      context.handle(_updatedAtMeta,
          updatedAt.isAcceptableOrUnknown(data['updated_at']!, _updatedAtMeta));
    } else if (isInserting) {
      context.missing(_updatedAtMeta);
    }
    return context;
  }

  @override
  Set<GeneratedColumn> get $primaryKey => {key};
  @override
  CacheEntry map(Map<String, dynamic> data, {String? tablePrefix}) {
    final effectivePrefix = tablePrefix != null ? '$tablePrefix.' : '';
    return CacheEntry(
      key: attachedDatabase.typeMapping
          .read(DriftSqlType.string, data['${effectivePrefix}key'])!,
      payload: attachedDatabase.typeMapping
          .read(DriftSqlType.string, data['${effectivePrefix}payload'])!,
      updatedAt: attachedDatabase.typeMapping
          .read(DriftSqlType.dateTime, data['${effectivePrefix}updated_at'])!,
    );
  }

  @override
  $CacheEntriesTable createAlias(String alias) {
    return $CacheEntriesTable(attachedDatabase, alias);
  }
}

class CacheEntry extends DataClass implements Insertable<CacheEntry> {
  final String key;
  final String payload;
  final DateTime updatedAt;
  const CacheEntry(
      {required this.key, required this.payload, required this.updatedAt});
  @override
  Map<String, Expression> toColumns(bool nullToAbsent) {
    final map = <String, Expression>{};
    map['key'] = Variable<String>(key);
    map['payload'] = Variable<String>(payload);
    map['updated_at'] = Variable<DateTime>(updatedAt);
    return map;
  }

  CacheEntriesCompanion toCompanion(bool nullToAbsent) {
    return CacheEntriesCompanion(
      key: Value(key),
      payload: Value(payload),
      updatedAt: Value(updatedAt),
    );
  }

  factory CacheEntry.fromJson(Map<String, dynamic> json,
      {ValueSerializer? serializer}) {
    serializer ??= driftRuntimeOptions.defaultSerializer;
    return CacheEntry(
      key: serializer.fromJson<String>(json['key']),
      payload: serializer.fromJson<String>(json['payload']),
      updatedAt: serializer.fromJson<DateTime>(json['updatedAt']),
    );
  }
  @override
  Map<String, dynamic> toJson({ValueSerializer? serializer}) {
    serializer ??= driftRuntimeOptions.defaultSerializer;
    return <String, dynamic>{
      'key': serializer.toJson<String>(key),
      'payload': serializer.toJson<String>(payload),
      'updatedAt': serializer.toJson<DateTime>(updatedAt),
    };
  }

  CacheEntry copyWith({String? key, String? payload, DateTime? updatedAt}) =>
      CacheEntry(
        key: key ?? this.key,
        payload: payload ?? this.payload,
        updatedAt: updatedAt ?? this.updatedAt,
      );
  CacheEntry copyWithCompanion(CacheEntriesCompanion data) {
    return CacheEntry(
      key: data.key.present ? data.key.value : this.key,
      payload: data.payload.present ? data.payload.value : this.payload,
      updatedAt: data.updatedAt.present ? data.updatedAt.value : this.updatedAt,
    );
  }

  @override
  String toString() {
    return (StringBuffer('CacheEntry(')
          ..write('key: $key, ')
          ..write('payload: $payload, ')
          ..write('updatedAt: $updatedAt')
          ..write(')'))
        .toString();
  }

  @override
  int get hashCode => Object.hash(key, payload, updatedAt);
  @override
  bool operator ==(Object other) =>
      identical(this, other) ||
      (other is CacheEntry &&
          other.key == this.key &&
          other.payload == this.payload &&
          other.updatedAt == this.updatedAt);
}

class CacheEntriesCompanion extends UpdateCompanion<CacheEntry> {
  final Value<String> key;
  final Value<String> payload;
  final Value<DateTime> updatedAt;
  final Value<int> rowid;
  const CacheEntriesCompanion({
    this.key = const Value.absent(),
    this.payload = const Value.absent(),
    this.updatedAt = const Value.absent(),
    this.rowid = const Value.absent(),
  });
  CacheEntriesCompanion.insert({
    required String key,
    required String payload,
    required DateTime updatedAt,
    this.rowid = const Value.absent(),
  })  : key = Value(key),
        payload = Value(payload),
        updatedAt = Value(updatedAt);
  static Insertable<CacheEntry> custom({
    Expression<String>? key,
    Expression<String>? payload,
    Expression<DateTime>? updatedAt,
    Expression<int>? rowid,
  }) {
    return RawValuesInsertable({
      if (key != null) 'key': key,
      if (payload != null) 'payload': payload,
      if (updatedAt != null) 'updated_at': updatedAt,
      if (rowid != null) 'rowid': rowid,
    });
  }

  CacheEntriesCompanion copyWith(
      {Value<String>? key,
      Value<String>? payload,
      Value<DateTime>? updatedAt,
      Value<int>? rowid}) {
    return CacheEntriesCompanion(
      key: key ?? this.key,
      payload: payload ?? this.payload,
      updatedAt: updatedAt ?? this.updatedAt,
      rowid: rowid ?? this.rowid,
    );
  }

  @override
  Map<String, Expression> toColumns(bool nullToAbsent) {
    final map = <String, Expression>{};
    if (key.present) {
      map['key'] = Variable<String>(key.value);
    }
    if (payload.present) {
      map['payload'] = Variable<String>(payload.value);
    }
    if (updatedAt.present) {
      map['updated_at'] = Variable<DateTime>(updatedAt.value);
    }
    if (rowid.present) {
      map['rowid'] = Variable<int>(rowid.value);
    }
    return map;
  }

  @override
  String toString() {
    return (StringBuffer('CacheEntriesCompanion(')
          ..write('key: $key, ')
          ..write('payload: $payload, ')
          ..write('updatedAt: $updatedAt, ')
          ..write('rowid: $rowid')
          ..write(')'))
        .toString();
  }
}

class $CachedSignalsTable extends CachedSignals
    with TableInfo<$CachedSignalsTable, CachedSignal> {
  @override
  final GeneratedDatabase attachedDatabase;
  final String? _alias;
  $CachedSignalsTable(this.attachedDatabase, [this._alias]);
  static const VerificationMeta _idMeta = const VerificationMeta('id');
  @override
  late final GeneratedColumn<int> id = GeneratedColumn<int>(
      'id', aliasedName, false,
      type: DriftSqlType.int, requiredDuringInsert: false);
  static const VerificationMeta _symbolMeta = const VerificationMeta('symbol');
  @override
  late final GeneratedColumn<String> symbol = GeneratedColumn<String>(
      'symbol', aliasedName, true,
      type: DriftSqlType.string, requiredDuringInsert: false);
  static const VerificationMeta _directionMeta =
      const VerificationMeta('direction');
  @override
  late final GeneratedColumn<String> direction = GeneratedColumn<String>(
      'direction', aliasedName, true,
      type: DriftSqlType.string, requiredDuringInsert: false);
  static const VerificationMeta _statusMeta = const VerificationMeta('status');
  @override
  late final GeneratedColumn<String> status = GeneratedColumn<String>(
      'status', aliasedName, false,
      type: DriftSqlType.string, requiredDuringInsert: true);
  static const VerificationMeta _confidenceMeta =
      const VerificationMeta('confidence');
  @override
  late final GeneratedColumn<double> confidence = GeneratedColumn<double>(
      'confidence', aliasedName, false,
      type: DriftSqlType.double,
      requiredDuringInsert: false,
      defaultValue: const Constant<double>(0));
  static const VerificationMeta _payloadMeta =
      const VerificationMeta('payload');
  @override
  late final GeneratedColumn<String> payload = GeneratedColumn<String>(
      'payload', aliasedName, false,
      type: DriftSqlType.string, requiredDuringInsert: true);
  static const VerificationMeta _receivedAtMeta =
      const VerificationMeta('receivedAt');
  @override
  late final GeneratedColumn<DateTime> receivedAt = GeneratedColumn<DateTime>(
      'received_at', aliasedName, false,
      type: DriftSqlType.dateTime, requiredDuringInsert: true);
  @override
  List<GeneratedColumn> get $columns =>
      [id, symbol, direction, status, confidence, payload, receivedAt];
  @override
  String get aliasedName => _alias ?? actualTableName;
  @override
  String get actualTableName => $name;
  static const String $name = 'cached_signals';
  @override
  VerificationContext validateIntegrity(Insertable<CachedSignal> instance,
      {bool isInserting = false}) {
    final context = VerificationContext();
    final data = instance.toColumns(true);
    if (data.containsKey('id')) {
      context.handle(_idMeta, id.isAcceptableOrUnknown(data['id']!, _idMeta));
    }
    if (data.containsKey('symbol')) {
      context.handle(_symbolMeta,
          symbol.isAcceptableOrUnknown(data['symbol']!, _symbolMeta));
    }
    if (data.containsKey('direction')) {
      context.handle(_directionMeta,
          direction.isAcceptableOrUnknown(data['direction']!, _directionMeta));
    }
    if (data.containsKey('status')) {
      context.handle(_statusMeta,
          status.isAcceptableOrUnknown(data['status']!, _statusMeta));
    } else if (isInserting) {
      context.missing(_statusMeta);
    }
    if (data.containsKey('confidence')) {
      context.handle(
          _confidenceMeta,
          confidence.isAcceptableOrUnknown(
              data['confidence']!, _confidenceMeta));
    }
    if (data.containsKey('payload')) {
      context.handle(_payloadMeta,
          payload.isAcceptableOrUnknown(data['payload']!, _payloadMeta));
    } else if (isInserting) {
      context.missing(_payloadMeta);
    }
    if (data.containsKey('received_at')) {
      context.handle(
          _receivedAtMeta,
          receivedAt.isAcceptableOrUnknown(
              data['received_at']!, _receivedAtMeta));
    } else if (isInserting) {
      context.missing(_receivedAtMeta);
    }
    return context;
  }

  @override
  Set<GeneratedColumn> get $primaryKey => {id};
  @override
  CachedSignal map(Map<String, dynamic> data, {String? tablePrefix}) {
    final effectivePrefix = tablePrefix != null ? '$tablePrefix.' : '';
    return CachedSignal(
      id: attachedDatabase.typeMapping
          .read(DriftSqlType.int, data['${effectivePrefix}id'])!,
      symbol: attachedDatabase.typeMapping
          .read(DriftSqlType.string, data['${effectivePrefix}symbol']),
      direction: attachedDatabase.typeMapping
          .read(DriftSqlType.string, data['${effectivePrefix}direction']),
      status: attachedDatabase.typeMapping
          .read(DriftSqlType.string, data['${effectivePrefix}status'])!,
      confidence: attachedDatabase.typeMapping
          .read(DriftSqlType.double, data['${effectivePrefix}confidence'])!,
      payload: attachedDatabase.typeMapping
          .read(DriftSqlType.string, data['${effectivePrefix}payload'])!,
      receivedAt: attachedDatabase.typeMapping
          .read(DriftSqlType.dateTime, data['${effectivePrefix}received_at'])!,
    );
  }

  @override
  $CachedSignalsTable createAlias(String alias) {
    return $CachedSignalsTable(attachedDatabase, alias);
  }
}

class CachedSignal extends DataClass implements Insertable<CachedSignal> {
  final int id;
  final String? symbol;
  final String? direction;
  final String status;
  final double confidence;
  final String payload;
  final DateTime receivedAt;
  const CachedSignal(
      {required this.id,
      this.symbol,
      this.direction,
      required this.status,
      required this.confidence,
      required this.payload,
      required this.receivedAt});
  @override
  Map<String, Expression> toColumns(bool nullToAbsent) {
    final map = <String, Expression>{};
    map['id'] = Variable<int>(id);
    if (!nullToAbsent || symbol != null) {
      map['symbol'] = Variable<String>(symbol);
    }
    if (!nullToAbsent || direction != null) {
      map['direction'] = Variable<String>(direction);
    }
    map['status'] = Variable<String>(status);
    map['confidence'] = Variable<double>(confidence);
    map['payload'] = Variable<String>(payload);
    map['received_at'] = Variable<DateTime>(receivedAt);
    return map;
  }

  CachedSignalsCompanion toCompanion(bool nullToAbsent) {
    return CachedSignalsCompanion(
      id: Value(id),
      symbol:
          symbol == null && nullToAbsent ? const Value.absent() : Value(symbol),
      direction: direction == null && nullToAbsent
          ? const Value.absent()
          : Value(direction),
      status: Value(status),
      confidence: Value(confidence),
      payload: Value(payload),
      receivedAt: Value(receivedAt),
    );
  }

  factory CachedSignal.fromJson(Map<String, dynamic> json,
      {ValueSerializer? serializer}) {
    serializer ??= driftRuntimeOptions.defaultSerializer;
    return CachedSignal(
      id: serializer.fromJson<int>(json['id']),
      symbol: serializer.fromJson<String?>(json['symbol']),
      direction: serializer.fromJson<String?>(json['direction']),
      status: serializer.fromJson<String>(json['status']),
      confidence: serializer.fromJson<double>(json['confidence']),
      payload: serializer.fromJson<String>(json['payload']),
      receivedAt: serializer.fromJson<DateTime>(json['receivedAt']),
    );
  }
  @override
  Map<String, dynamic> toJson({ValueSerializer? serializer}) {
    serializer ??= driftRuntimeOptions.defaultSerializer;
    return <String, dynamic>{
      'id': serializer.toJson<int>(id),
      'symbol': serializer.toJson<String?>(symbol),
      'direction': serializer.toJson<String?>(direction),
      'status': serializer.toJson<String>(status),
      'confidence': serializer.toJson<double>(confidence),
      'payload': serializer.toJson<String>(payload),
      'receivedAt': serializer.toJson<DateTime>(receivedAt),
    };
  }

  CachedSignal copyWith(
          {int? id,
          Value<String?> symbol = const Value.absent(),
          Value<String?> direction = const Value.absent(),
          String? status,
          double? confidence,
          String? payload,
          DateTime? receivedAt}) =>
      CachedSignal(
        id: id ?? this.id,
        symbol: symbol.present ? symbol.value : this.symbol,
        direction: direction.present ? direction.value : this.direction,
        status: status ?? this.status,
        confidence: confidence ?? this.confidence,
        payload: payload ?? this.payload,
        receivedAt: receivedAt ?? this.receivedAt,
      );
  CachedSignal copyWithCompanion(CachedSignalsCompanion data) {
    return CachedSignal(
      id: data.id.present ? data.id.value : this.id,
      symbol: data.symbol.present ? data.symbol.value : this.symbol,
      direction: data.direction.present ? data.direction.value : this.direction,
      status: data.status.present ? data.status.value : this.status,
      confidence:
          data.confidence.present ? data.confidence.value : this.confidence,
      payload: data.payload.present ? data.payload.value : this.payload,
      receivedAt:
          data.receivedAt.present ? data.receivedAt.value : this.receivedAt,
    );
  }

  @override
  String toString() {
    return (StringBuffer('CachedSignal(')
          ..write('id: $id, ')
          ..write('symbol: $symbol, ')
          ..write('direction: $direction, ')
          ..write('status: $status, ')
          ..write('confidence: $confidence, ')
          ..write('payload: $payload, ')
          ..write('receivedAt: $receivedAt')
          ..write(')'))
        .toString();
  }

  @override
  int get hashCode => Object.hash(
      id, symbol, direction, status, confidence, payload, receivedAt);
  @override
  bool operator ==(Object other) =>
      identical(this, other) ||
      (other is CachedSignal &&
          other.id == this.id &&
          other.symbol == this.symbol &&
          other.direction == this.direction &&
          other.status == this.status &&
          other.confidence == this.confidence &&
          other.payload == this.payload &&
          other.receivedAt == this.receivedAt);
}

class CachedSignalsCompanion extends UpdateCompanion<CachedSignal> {
  final Value<int> id;
  final Value<String?> symbol;
  final Value<String?> direction;
  final Value<String> status;
  final Value<double> confidence;
  final Value<String> payload;
  final Value<DateTime> receivedAt;
  const CachedSignalsCompanion({
    this.id = const Value.absent(),
    this.symbol = const Value.absent(),
    this.direction = const Value.absent(),
    this.status = const Value.absent(),
    this.confidence = const Value.absent(),
    this.payload = const Value.absent(),
    this.receivedAt = const Value.absent(),
  });
  CachedSignalsCompanion.insert({
    this.id = const Value.absent(),
    this.symbol = const Value.absent(),
    this.direction = const Value.absent(),
    required String status,
    this.confidence = const Value.absent(),
    required String payload,
    required DateTime receivedAt,
  })  : status = Value(status),
        payload = Value(payload),
        receivedAt = Value(receivedAt);
  static Insertable<CachedSignal> custom({
    Expression<int>? id,
    Expression<String>? symbol,
    Expression<String>? direction,
    Expression<String>? status,
    Expression<double>? confidence,
    Expression<String>? payload,
    Expression<DateTime>? receivedAt,
  }) {
    return RawValuesInsertable({
      if (id != null) 'id': id,
      if (symbol != null) 'symbol': symbol,
      if (direction != null) 'direction': direction,
      if (status != null) 'status': status,
      if (confidence != null) 'confidence': confidence,
      if (payload != null) 'payload': payload,
      if (receivedAt != null) 'received_at': receivedAt,
    });
  }

  CachedSignalsCompanion copyWith(
      {Value<int>? id,
      Value<String?>? symbol,
      Value<String?>? direction,
      Value<String>? status,
      Value<double>? confidence,
      Value<String>? payload,
      Value<DateTime>? receivedAt}) {
    return CachedSignalsCompanion(
      id: id ?? this.id,
      symbol: symbol ?? this.symbol,
      direction: direction ?? this.direction,
      status: status ?? this.status,
      confidence: confidence ?? this.confidence,
      payload: payload ?? this.payload,
      receivedAt: receivedAt ?? this.receivedAt,
    );
  }

  @override
  Map<String, Expression> toColumns(bool nullToAbsent) {
    final map = <String, Expression>{};
    if (id.present) {
      map['id'] = Variable<int>(id.value);
    }
    if (symbol.present) {
      map['symbol'] = Variable<String>(symbol.value);
    }
    if (direction.present) {
      map['direction'] = Variable<String>(direction.value);
    }
    if (status.present) {
      map['status'] = Variable<String>(status.value);
    }
    if (confidence.present) {
      map['confidence'] = Variable<double>(confidence.value);
    }
    if (payload.present) {
      map['payload'] = Variable<String>(payload.value);
    }
    if (receivedAt.present) {
      map['received_at'] = Variable<DateTime>(receivedAt.value);
    }
    return map;
  }

  @override
  String toString() {
    return (StringBuffer('CachedSignalsCompanion(')
          ..write('id: $id, ')
          ..write('symbol: $symbol, ')
          ..write('direction: $direction, ')
          ..write('status: $status, ')
          ..write('confidence: $confidence, ')
          ..write('payload: $payload, ')
          ..write('receivedAt: $receivedAt')
          ..write(')'))
        .toString();
  }
}

class $CachedTradesTable extends CachedTrades
    with TableInfo<$CachedTradesTable, CachedTrade> {
  @override
  final GeneratedDatabase attachedDatabase;
  final String? _alias;
  $CachedTradesTable(this.attachedDatabase, [this._alias]);
  static const VerificationMeta _idMeta = const VerificationMeta('id');
  @override
  late final GeneratedColumn<int> id = GeneratedColumn<int>(
      'id', aliasedName, false,
      type: DriftSqlType.int, requiredDuringInsert: false);
  static const VerificationMeta _ticketMeta = const VerificationMeta('ticket');
  @override
  late final GeneratedColumn<int> ticket = GeneratedColumn<int>(
      'ticket', aliasedName, false,
      type: DriftSqlType.int, requiredDuringInsert: true);
  static const VerificationMeta _symbolMeta = const VerificationMeta('symbol');
  @override
  late final GeneratedColumn<String> symbol = GeneratedColumn<String>(
      'symbol', aliasedName, false,
      type: DriftSqlType.string, requiredDuringInsert: true);
  static const VerificationMeta _directionMeta =
      const VerificationMeta('direction');
  @override
  late final GeneratedColumn<String> direction = GeneratedColumn<String>(
      'direction', aliasedName, false,
      type: DriftSqlType.string, requiredDuringInsert: true);
  static const VerificationMeta _stateMeta = const VerificationMeta('state');
  @override
  late final GeneratedColumn<String> state = GeneratedColumn<String>(
      'state', aliasedName, false,
      type: DriftSqlType.string, requiredDuringInsert: true);
  static const VerificationMeta _profitMeta = const VerificationMeta('profit');
  @override
  late final GeneratedColumn<double> profit = GeneratedColumn<double>(
      'profit', aliasedName, false,
      type: DriftSqlType.double,
      requiredDuringInsert: false,
      defaultValue: const Constant<double>(0));
  static const VerificationMeta _payloadMeta =
      const VerificationMeta('payload');
  @override
  late final GeneratedColumn<String> payload = GeneratedColumn<String>(
      'payload', aliasedName, false,
      type: DriftSqlType.string, requiredDuringInsert: true);
  static const VerificationMeta _openedAtMeta =
      const VerificationMeta('openedAt');
  @override
  late final GeneratedColumn<DateTime> openedAt = GeneratedColumn<DateTime>(
      'opened_at', aliasedName, false,
      type: DriftSqlType.dateTime, requiredDuringInsert: true);
  @override
  List<GeneratedColumn> get $columns =>
      [id, ticket, symbol, direction, state, profit, payload, openedAt];
  @override
  String get aliasedName => _alias ?? actualTableName;
  @override
  String get actualTableName => $name;
  static const String $name = 'cached_trades';
  @override
  VerificationContext validateIntegrity(Insertable<CachedTrade> instance,
      {bool isInserting = false}) {
    final context = VerificationContext();
    final data = instance.toColumns(true);
    if (data.containsKey('id')) {
      context.handle(_idMeta, id.isAcceptableOrUnknown(data['id']!, _idMeta));
    }
    if (data.containsKey('ticket')) {
      context.handle(_ticketMeta,
          ticket.isAcceptableOrUnknown(data['ticket']!, _ticketMeta));
    } else if (isInserting) {
      context.missing(_ticketMeta);
    }
    if (data.containsKey('symbol')) {
      context.handle(_symbolMeta,
          symbol.isAcceptableOrUnknown(data['symbol']!, _symbolMeta));
    } else if (isInserting) {
      context.missing(_symbolMeta);
    }
    if (data.containsKey('direction')) {
      context.handle(_directionMeta,
          direction.isAcceptableOrUnknown(data['direction']!, _directionMeta));
    } else if (isInserting) {
      context.missing(_directionMeta);
    }
    if (data.containsKey('state')) {
      context.handle(
          _stateMeta, state.isAcceptableOrUnknown(data['state']!, _stateMeta));
    } else if (isInserting) {
      context.missing(_stateMeta);
    }
    if (data.containsKey('profit')) {
      context.handle(_profitMeta,
          profit.isAcceptableOrUnknown(data['profit']!, _profitMeta));
    }
    if (data.containsKey('payload')) {
      context.handle(_payloadMeta,
          payload.isAcceptableOrUnknown(data['payload']!, _payloadMeta));
    } else if (isInserting) {
      context.missing(_payloadMeta);
    }
    if (data.containsKey('opened_at')) {
      context.handle(_openedAtMeta,
          openedAt.isAcceptableOrUnknown(data['opened_at']!, _openedAtMeta));
    } else if (isInserting) {
      context.missing(_openedAtMeta);
    }
    return context;
  }

  @override
  Set<GeneratedColumn> get $primaryKey => {id};
  @override
  CachedTrade map(Map<String, dynamic> data, {String? tablePrefix}) {
    final effectivePrefix = tablePrefix != null ? '$tablePrefix.' : '';
    return CachedTrade(
      id: attachedDatabase.typeMapping
          .read(DriftSqlType.int, data['${effectivePrefix}id'])!,
      ticket: attachedDatabase.typeMapping
          .read(DriftSqlType.int, data['${effectivePrefix}ticket'])!,
      symbol: attachedDatabase.typeMapping
          .read(DriftSqlType.string, data['${effectivePrefix}symbol'])!,
      direction: attachedDatabase.typeMapping
          .read(DriftSqlType.string, data['${effectivePrefix}direction'])!,
      state: attachedDatabase.typeMapping
          .read(DriftSqlType.string, data['${effectivePrefix}state'])!,
      profit: attachedDatabase.typeMapping
          .read(DriftSqlType.double, data['${effectivePrefix}profit'])!,
      payload: attachedDatabase.typeMapping
          .read(DriftSqlType.string, data['${effectivePrefix}payload'])!,
      openedAt: attachedDatabase.typeMapping
          .read(DriftSqlType.dateTime, data['${effectivePrefix}opened_at'])!,
    );
  }

  @override
  $CachedTradesTable createAlias(String alias) {
    return $CachedTradesTable(attachedDatabase, alias);
  }
}

class CachedTrade extends DataClass implements Insertable<CachedTrade> {
  final int id;
  final int ticket;
  final String symbol;
  final String direction;
  final String state;
  final double profit;
  final String payload;
  final DateTime openedAt;
  const CachedTrade(
      {required this.id,
      required this.ticket,
      required this.symbol,
      required this.direction,
      required this.state,
      required this.profit,
      required this.payload,
      required this.openedAt});
  @override
  Map<String, Expression> toColumns(bool nullToAbsent) {
    final map = <String, Expression>{};
    map['id'] = Variable<int>(id);
    map['ticket'] = Variable<int>(ticket);
    map['symbol'] = Variable<String>(symbol);
    map['direction'] = Variable<String>(direction);
    map['state'] = Variable<String>(state);
    map['profit'] = Variable<double>(profit);
    map['payload'] = Variable<String>(payload);
    map['opened_at'] = Variable<DateTime>(openedAt);
    return map;
  }

  CachedTradesCompanion toCompanion(bool nullToAbsent) {
    return CachedTradesCompanion(
      id: Value(id),
      ticket: Value(ticket),
      symbol: Value(symbol),
      direction: Value(direction),
      state: Value(state),
      profit: Value(profit),
      payload: Value(payload),
      openedAt: Value(openedAt),
    );
  }

  factory CachedTrade.fromJson(Map<String, dynamic> json,
      {ValueSerializer? serializer}) {
    serializer ??= driftRuntimeOptions.defaultSerializer;
    return CachedTrade(
      id: serializer.fromJson<int>(json['id']),
      ticket: serializer.fromJson<int>(json['ticket']),
      symbol: serializer.fromJson<String>(json['symbol']),
      direction: serializer.fromJson<String>(json['direction']),
      state: serializer.fromJson<String>(json['state']),
      profit: serializer.fromJson<double>(json['profit']),
      payload: serializer.fromJson<String>(json['payload']),
      openedAt: serializer.fromJson<DateTime>(json['openedAt']),
    );
  }
  @override
  Map<String, dynamic> toJson({ValueSerializer? serializer}) {
    serializer ??= driftRuntimeOptions.defaultSerializer;
    return <String, dynamic>{
      'id': serializer.toJson<int>(id),
      'ticket': serializer.toJson<int>(ticket),
      'symbol': serializer.toJson<String>(symbol),
      'direction': serializer.toJson<String>(direction),
      'state': serializer.toJson<String>(state),
      'profit': serializer.toJson<double>(profit),
      'payload': serializer.toJson<String>(payload),
      'openedAt': serializer.toJson<DateTime>(openedAt),
    };
  }

  CachedTrade copyWith(
          {int? id,
          int? ticket,
          String? symbol,
          String? direction,
          String? state,
          double? profit,
          String? payload,
          DateTime? openedAt}) =>
      CachedTrade(
        id: id ?? this.id,
        ticket: ticket ?? this.ticket,
        symbol: symbol ?? this.symbol,
        direction: direction ?? this.direction,
        state: state ?? this.state,
        profit: profit ?? this.profit,
        payload: payload ?? this.payload,
        openedAt: openedAt ?? this.openedAt,
      );
  CachedTrade copyWithCompanion(CachedTradesCompanion data) {
    return CachedTrade(
      id: data.id.present ? data.id.value : this.id,
      ticket: data.ticket.present ? data.ticket.value : this.ticket,
      symbol: data.symbol.present ? data.symbol.value : this.symbol,
      direction: data.direction.present ? data.direction.value : this.direction,
      state: data.state.present ? data.state.value : this.state,
      profit: data.profit.present ? data.profit.value : this.profit,
      payload: data.payload.present ? data.payload.value : this.payload,
      openedAt: data.openedAt.present ? data.openedAt.value : this.openedAt,
    );
  }

  @override
  String toString() {
    return (StringBuffer('CachedTrade(')
          ..write('id: $id, ')
          ..write('ticket: $ticket, ')
          ..write('symbol: $symbol, ')
          ..write('direction: $direction, ')
          ..write('state: $state, ')
          ..write('profit: $profit, ')
          ..write('payload: $payload, ')
          ..write('openedAt: $openedAt')
          ..write(')'))
        .toString();
  }

  @override
  int get hashCode => Object.hash(
      id, ticket, symbol, direction, state, profit, payload, openedAt);
  @override
  bool operator ==(Object other) =>
      identical(this, other) ||
      (other is CachedTrade &&
          other.id == this.id &&
          other.ticket == this.ticket &&
          other.symbol == this.symbol &&
          other.direction == this.direction &&
          other.state == this.state &&
          other.profit == this.profit &&
          other.payload == this.payload &&
          other.openedAt == this.openedAt);
}

class CachedTradesCompanion extends UpdateCompanion<CachedTrade> {
  final Value<int> id;
  final Value<int> ticket;
  final Value<String> symbol;
  final Value<String> direction;
  final Value<String> state;
  final Value<double> profit;
  final Value<String> payload;
  final Value<DateTime> openedAt;
  const CachedTradesCompanion({
    this.id = const Value.absent(),
    this.ticket = const Value.absent(),
    this.symbol = const Value.absent(),
    this.direction = const Value.absent(),
    this.state = const Value.absent(),
    this.profit = const Value.absent(),
    this.payload = const Value.absent(),
    this.openedAt = const Value.absent(),
  });
  CachedTradesCompanion.insert({
    this.id = const Value.absent(),
    required int ticket,
    required String symbol,
    required String direction,
    required String state,
    this.profit = const Value.absent(),
    required String payload,
    required DateTime openedAt,
  })  : ticket = Value(ticket),
        symbol = Value(symbol),
        direction = Value(direction),
        state = Value(state),
        payload = Value(payload),
        openedAt = Value(openedAt);
  static Insertable<CachedTrade> custom({
    Expression<int>? id,
    Expression<int>? ticket,
    Expression<String>? symbol,
    Expression<String>? direction,
    Expression<String>? state,
    Expression<double>? profit,
    Expression<String>? payload,
    Expression<DateTime>? openedAt,
  }) {
    return RawValuesInsertable({
      if (id != null) 'id': id,
      if (ticket != null) 'ticket': ticket,
      if (symbol != null) 'symbol': symbol,
      if (direction != null) 'direction': direction,
      if (state != null) 'state': state,
      if (profit != null) 'profit': profit,
      if (payload != null) 'payload': payload,
      if (openedAt != null) 'opened_at': openedAt,
    });
  }

  CachedTradesCompanion copyWith(
      {Value<int>? id,
      Value<int>? ticket,
      Value<String>? symbol,
      Value<String>? direction,
      Value<String>? state,
      Value<double>? profit,
      Value<String>? payload,
      Value<DateTime>? openedAt}) {
    return CachedTradesCompanion(
      id: id ?? this.id,
      ticket: ticket ?? this.ticket,
      symbol: symbol ?? this.symbol,
      direction: direction ?? this.direction,
      state: state ?? this.state,
      profit: profit ?? this.profit,
      payload: payload ?? this.payload,
      openedAt: openedAt ?? this.openedAt,
    );
  }

  @override
  Map<String, Expression> toColumns(bool nullToAbsent) {
    final map = <String, Expression>{};
    if (id.present) {
      map['id'] = Variable<int>(id.value);
    }
    if (ticket.present) {
      map['ticket'] = Variable<int>(ticket.value);
    }
    if (symbol.present) {
      map['symbol'] = Variable<String>(symbol.value);
    }
    if (direction.present) {
      map['direction'] = Variable<String>(direction.value);
    }
    if (state.present) {
      map['state'] = Variable<String>(state.value);
    }
    if (profit.present) {
      map['profit'] = Variable<double>(profit.value);
    }
    if (payload.present) {
      map['payload'] = Variable<String>(payload.value);
    }
    if (openedAt.present) {
      map['opened_at'] = Variable<DateTime>(openedAt.value);
    }
    return map;
  }

  @override
  String toString() {
    return (StringBuffer('CachedTradesCompanion(')
          ..write('id: $id, ')
          ..write('ticket: $ticket, ')
          ..write('symbol: $symbol, ')
          ..write('direction: $direction, ')
          ..write('state: $state, ')
          ..write('profit: $profit, ')
          ..write('payload: $payload, ')
          ..write('openedAt: $openedAt')
          ..write(')'))
        .toString();
  }
}

abstract class _$LocalDatabase extends GeneratedDatabase {
  _$LocalDatabase(QueryExecutor e) : super(e);
  $LocalDatabaseManager get managers => $LocalDatabaseManager(this);
  late final $CacheEntriesTable cacheEntries = $CacheEntriesTable(this);
  late final $CachedSignalsTable cachedSignals = $CachedSignalsTable(this);
  late final $CachedTradesTable cachedTrades = $CachedTradesTable(this);
  @override
  Iterable<TableInfo<Table, Object?>> get allTables =>
      allSchemaEntities.whereType<TableInfo<Table, Object?>>();
  @override
  List<DatabaseSchemaEntity> get allSchemaEntities =>
      [cacheEntries, cachedSignals, cachedTrades];
}

typedef $$CacheEntriesTableCreateCompanionBuilder = CacheEntriesCompanion
    Function({
  required String key,
  required String payload,
  required DateTime updatedAt,
  Value<int> rowid,
});
typedef $$CacheEntriesTableUpdateCompanionBuilder = CacheEntriesCompanion
    Function({
  Value<String> key,
  Value<String> payload,
  Value<DateTime> updatedAt,
  Value<int> rowid,
});

class $$CacheEntriesTableFilterComposer
    extends Composer<_$LocalDatabase, $CacheEntriesTable> {
  $$CacheEntriesTableFilterComposer({
    required super.$db,
    required super.$table,
    super.joinBuilder,
    super.$addJoinBuilderToRootComposer,
    super.$removeJoinBuilderFromRootComposer,
  });
  ColumnFilters<String> get key => $composableBuilder(
      column: $table.key, builder: (column) => ColumnFilters(column));

  ColumnFilters<String> get payload => $composableBuilder(
      column: $table.payload, builder: (column) => ColumnFilters(column));

  ColumnFilters<DateTime> get updatedAt => $composableBuilder(
      column: $table.updatedAt, builder: (column) => ColumnFilters(column));
}

class $$CacheEntriesTableOrderingComposer
    extends Composer<_$LocalDatabase, $CacheEntriesTable> {
  $$CacheEntriesTableOrderingComposer({
    required super.$db,
    required super.$table,
    super.joinBuilder,
    super.$addJoinBuilderToRootComposer,
    super.$removeJoinBuilderFromRootComposer,
  });
  ColumnOrderings<String> get key => $composableBuilder(
      column: $table.key, builder: (column) => ColumnOrderings(column));

  ColumnOrderings<String> get payload => $composableBuilder(
      column: $table.payload, builder: (column) => ColumnOrderings(column));

  ColumnOrderings<DateTime> get updatedAt => $composableBuilder(
      column: $table.updatedAt, builder: (column) => ColumnOrderings(column));
}

class $$CacheEntriesTableAnnotationComposer
    extends Composer<_$LocalDatabase, $CacheEntriesTable> {
  $$CacheEntriesTableAnnotationComposer({
    required super.$db,
    required super.$table,
    super.joinBuilder,
    super.$addJoinBuilderToRootComposer,
    super.$removeJoinBuilderFromRootComposer,
  });
  GeneratedColumn<String> get key =>
      $composableBuilder(column: $table.key, builder: (column) => column);

  GeneratedColumn<String> get payload =>
      $composableBuilder(column: $table.payload, builder: (column) => column);

  GeneratedColumn<DateTime> get updatedAt =>
      $composableBuilder(column: $table.updatedAt, builder: (column) => column);
}

class $$CacheEntriesTableTableManager extends RootTableManager<
    _$LocalDatabase,
    $CacheEntriesTable,
    CacheEntry,
    $$CacheEntriesTableFilterComposer,
    $$CacheEntriesTableOrderingComposer,
    $$CacheEntriesTableAnnotationComposer,
    $$CacheEntriesTableCreateCompanionBuilder,
    $$CacheEntriesTableUpdateCompanionBuilder,
    (
      CacheEntry,
      BaseReferences<_$LocalDatabase, $CacheEntriesTable, CacheEntry>
    ),
    CacheEntry,
    PrefetchHooks Function()> {
  $$CacheEntriesTableTableManager(_$LocalDatabase db, $CacheEntriesTable table)
      : super(TableManagerState(
          db: db,
          table: table,
          createFilteringComposer: () =>
              $$CacheEntriesTableFilterComposer($db: db, $table: table),
          createOrderingComposer: () =>
              $$CacheEntriesTableOrderingComposer($db: db, $table: table),
          createComputedFieldComposer: () =>
              $$CacheEntriesTableAnnotationComposer($db: db, $table: table),
          updateCompanionCallback: ({
            Value<String> key = const Value.absent(),
            Value<String> payload = const Value.absent(),
            Value<DateTime> updatedAt = const Value.absent(),
            Value<int> rowid = const Value.absent(),
          }) =>
              CacheEntriesCompanion(
            key: key,
            payload: payload,
            updatedAt: updatedAt,
            rowid: rowid,
          ),
          createCompanionCallback: ({
            required String key,
            required String payload,
            required DateTime updatedAt,
            Value<int> rowid = const Value.absent(),
          }) =>
              CacheEntriesCompanion.insert(
            key: key,
            payload: payload,
            updatedAt: updatedAt,
            rowid: rowid,
          ),
          withReferenceMapper: (p0) => p0
              .map((e) => (e.readTable(table), BaseReferences(db, table, e)))
              .toList(),
          prefetchHooksCallback: null,
        ));
}

typedef $$CacheEntriesTableProcessedTableManager = ProcessedTableManager<
    _$LocalDatabase,
    $CacheEntriesTable,
    CacheEntry,
    $$CacheEntriesTableFilterComposer,
    $$CacheEntriesTableOrderingComposer,
    $$CacheEntriesTableAnnotationComposer,
    $$CacheEntriesTableCreateCompanionBuilder,
    $$CacheEntriesTableUpdateCompanionBuilder,
    (
      CacheEntry,
      BaseReferences<_$LocalDatabase, $CacheEntriesTable, CacheEntry>
    ),
    CacheEntry,
    PrefetchHooks Function()>;
typedef $$CachedSignalsTableCreateCompanionBuilder = CachedSignalsCompanion
    Function({
  Value<int> id,
  Value<String?> symbol,
  Value<String?> direction,
  required String status,
  Value<double> confidence,
  required String payload,
  required DateTime receivedAt,
});
typedef $$CachedSignalsTableUpdateCompanionBuilder = CachedSignalsCompanion
    Function({
  Value<int> id,
  Value<String?> symbol,
  Value<String?> direction,
  Value<String> status,
  Value<double> confidence,
  Value<String> payload,
  Value<DateTime> receivedAt,
});

class $$CachedSignalsTableFilterComposer
    extends Composer<_$LocalDatabase, $CachedSignalsTable> {
  $$CachedSignalsTableFilterComposer({
    required super.$db,
    required super.$table,
    super.joinBuilder,
    super.$addJoinBuilderToRootComposer,
    super.$removeJoinBuilderFromRootComposer,
  });
  ColumnFilters<int> get id => $composableBuilder(
      column: $table.id, builder: (column) => ColumnFilters(column));

  ColumnFilters<String> get symbol => $composableBuilder(
      column: $table.symbol, builder: (column) => ColumnFilters(column));

  ColumnFilters<String> get direction => $composableBuilder(
      column: $table.direction, builder: (column) => ColumnFilters(column));

  ColumnFilters<String> get status => $composableBuilder(
      column: $table.status, builder: (column) => ColumnFilters(column));

  ColumnFilters<double> get confidence => $composableBuilder(
      column: $table.confidence, builder: (column) => ColumnFilters(column));

  ColumnFilters<String> get payload => $composableBuilder(
      column: $table.payload, builder: (column) => ColumnFilters(column));

  ColumnFilters<DateTime> get receivedAt => $composableBuilder(
      column: $table.receivedAt, builder: (column) => ColumnFilters(column));
}

class $$CachedSignalsTableOrderingComposer
    extends Composer<_$LocalDatabase, $CachedSignalsTable> {
  $$CachedSignalsTableOrderingComposer({
    required super.$db,
    required super.$table,
    super.joinBuilder,
    super.$addJoinBuilderToRootComposer,
    super.$removeJoinBuilderFromRootComposer,
  });
  ColumnOrderings<int> get id => $composableBuilder(
      column: $table.id, builder: (column) => ColumnOrderings(column));

  ColumnOrderings<String> get symbol => $composableBuilder(
      column: $table.symbol, builder: (column) => ColumnOrderings(column));

  ColumnOrderings<String> get direction => $composableBuilder(
      column: $table.direction, builder: (column) => ColumnOrderings(column));

  ColumnOrderings<String> get status => $composableBuilder(
      column: $table.status, builder: (column) => ColumnOrderings(column));

  ColumnOrderings<double> get confidence => $composableBuilder(
      column: $table.confidence, builder: (column) => ColumnOrderings(column));

  ColumnOrderings<String> get payload => $composableBuilder(
      column: $table.payload, builder: (column) => ColumnOrderings(column));

  ColumnOrderings<DateTime> get receivedAt => $composableBuilder(
      column: $table.receivedAt, builder: (column) => ColumnOrderings(column));
}

class $$CachedSignalsTableAnnotationComposer
    extends Composer<_$LocalDatabase, $CachedSignalsTable> {
  $$CachedSignalsTableAnnotationComposer({
    required super.$db,
    required super.$table,
    super.joinBuilder,
    super.$addJoinBuilderToRootComposer,
    super.$removeJoinBuilderFromRootComposer,
  });
  GeneratedColumn<int> get id =>
      $composableBuilder(column: $table.id, builder: (column) => column);

  GeneratedColumn<String> get symbol =>
      $composableBuilder(column: $table.symbol, builder: (column) => column);

  GeneratedColumn<String> get direction =>
      $composableBuilder(column: $table.direction, builder: (column) => column);

  GeneratedColumn<String> get status =>
      $composableBuilder(column: $table.status, builder: (column) => column);

  GeneratedColumn<double> get confidence => $composableBuilder(
      column: $table.confidence, builder: (column) => column);

  GeneratedColumn<String> get payload =>
      $composableBuilder(column: $table.payload, builder: (column) => column);

  GeneratedColumn<DateTime> get receivedAt => $composableBuilder(
      column: $table.receivedAt, builder: (column) => column);
}

class $$CachedSignalsTableTableManager extends RootTableManager<
    _$LocalDatabase,
    $CachedSignalsTable,
    CachedSignal,
    $$CachedSignalsTableFilterComposer,
    $$CachedSignalsTableOrderingComposer,
    $$CachedSignalsTableAnnotationComposer,
    $$CachedSignalsTableCreateCompanionBuilder,
    $$CachedSignalsTableUpdateCompanionBuilder,
    (
      CachedSignal,
      BaseReferences<_$LocalDatabase, $CachedSignalsTable, CachedSignal>
    ),
    CachedSignal,
    PrefetchHooks Function()> {
  $$CachedSignalsTableTableManager(
      _$LocalDatabase db, $CachedSignalsTable table)
      : super(TableManagerState(
          db: db,
          table: table,
          createFilteringComposer: () =>
              $$CachedSignalsTableFilterComposer($db: db, $table: table),
          createOrderingComposer: () =>
              $$CachedSignalsTableOrderingComposer($db: db, $table: table),
          createComputedFieldComposer: () =>
              $$CachedSignalsTableAnnotationComposer($db: db, $table: table),
          updateCompanionCallback: ({
            Value<int> id = const Value.absent(),
            Value<String?> symbol = const Value.absent(),
            Value<String?> direction = const Value.absent(),
            Value<String> status = const Value.absent(),
            Value<double> confidence = const Value.absent(),
            Value<String> payload = const Value.absent(),
            Value<DateTime> receivedAt = const Value.absent(),
          }) =>
              CachedSignalsCompanion(
            id: id,
            symbol: symbol,
            direction: direction,
            status: status,
            confidence: confidence,
            payload: payload,
            receivedAt: receivedAt,
          ),
          createCompanionCallback: ({
            Value<int> id = const Value.absent(),
            Value<String?> symbol = const Value.absent(),
            Value<String?> direction = const Value.absent(),
            required String status,
            Value<double> confidence = const Value.absent(),
            required String payload,
            required DateTime receivedAt,
          }) =>
              CachedSignalsCompanion.insert(
            id: id,
            symbol: symbol,
            direction: direction,
            status: status,
            confidence: confidence,
            payload: payload,
            receivedAt: receivedAt,
          ),
          withReferenceMapper: (p0) => p0
              .map((e) => (e.readTable(table), BaseReferences(db, table, e)))
              .toList(),
          prefetchHooksCallback: null,
        ));
}

typedef $$CachedSignalsTableProcessedTableManager = ProcessedTableManager<
    _$LocalDatabase,
    $CachedSignalsTable,
    CachedSignal,
    $$CachedSignalsTableFilterComposer,
    $$CachedSignalsTableOrderingComposer,
    $$CachedSignalsTableAnnotationComposer,
    $$CachedSignalsTableCreateCompanionBuilder,
    $$CachedSignalsTableUpdateCompanionBuilder,
    (
      CachedSignal,
      BaseReferences<_$LocalDatabase, $CachedSignalsTable, CachedSignal>
    ),
    CachedSignal,
    PrefetchHooks Function()>;
typedef $$CachedTradesTableCreateCompanionBuilder = CachedTradesCompanion
    Function({
  Value<int> id,
  required int ticket,
  required String symbol,
  required String direction,
  required String state,
  Value<double> profit,
  required String payload,
  required DateTime openedAt,
});
typedef $$CachedTradesTableUpdateCompanionBuilder = CachedTradesCompanion
    Function({
  Value<int> id,
  Value<int> ticket,
  Value<String> symbol,
  Value<String> direction,
  Value<String> state,
  Value<double> profit,
  Value<String> payload,
  Value<DateTime> openedAt,
});

class $$CachedTradesTableFilterComposer
    extends Composer<_$LocalDatabase, $CachedTradesTable> {
  $$CachedTradesTableFilterComposer({
    required super.$db,
    required super.$table,
    super.joinBuilder,
    super.$addJoinBuilderToRootComposer,
    super.$removeJoinBuilderFromRootComposer,
  });
  ColumnFilters<int> get id => $composableBuilder(
      column: $table.id, builder: (column) => ColumnFilters(column));

  ColumnFilters<int> get ticket => $composableBuilder(
      column: $table.ticket, builder: (column) => ColumnFilters(column));

  ColumnFilters<String> get symbol => $composableBuilder(
      column: $table.symbol, builder: (column) => ColumnFilters(column));

  ColumnFilters<String> get direction => $composableBuilder(
      column: $table.direction, builder: (column) => ColumnFilters(column));

  ColumnFilters<String> get state => $composableBuilder(
      column: $table.state, builder: (column) => ColumnFilters(column));

  ColumnFilters<double> get profit => $composableBuilder(
      column: $table.profit, builder: (column) => ColumnFilters(column));

  ColumnFilters<String> get payload => $composableBuilder(
      column: $table.payload, builder: (column) => ColumnFilters(column));

  ColumnFilters<DateTime> get openedAt => $composableBuilder(
      column: $table.openedAt, builder: (column) => ColumnFilters(column));
}

class $$CachedTradesTableOrderingComposer
    extends Composer<_$LocalDatabase, $CachedTradesTable> {
  $$CachedTradesTableOrderingComposer({
    required super.$db,
    required super.$table,
    super.joinBuilder,
    super.$addJoinBuilderToRootComposer,
    super.$removeJoinBuilderFromRootComposer,
  });
  ColumnOrderings<int> get id => $composableBuilder(
      column: $table.id, builder: (column) => ColumnOrderings(column));

  ColumnOrderings<int> get ticket => $composableBuilder(
      column: $table.ticket, builder: (column) => ColumnOrderings(column));

  ColumnOrderings<String> get symbol => $composableBuilder(
      column: $table.symbol, builder: (column) => ColumnOrderings(column));

  ColumnOrderings<String> get direction => $composableBuilder(
      column: $table.direction, builder: (column) => ColumnOrderings(column));

  ColumnOrderings<String> get state => $composableBuilder(
      column: $table.state, builder: (column) => ColumnOrderings(column));

  ColumnOrderings<double> get profit => $composableBuilder(
      column: $table.profit, builder: (column) => ColumnOrderings(column));

  ColumnOrderings<String> get payload => $composableBuilder(
      column: $table.payload, builder: (column) => ColumnOrderings(column));

  ColumnOrderings<DateTime> get openedAt => $composableBuilder(
      column: $table.openedAt, builder: (column) => ColumnOrderings(column));
}

class $$CachedTradesTableAnnotationComposer
    extends Composer<_$LocalDatabase, $CachedTradesTable> {
  $$CachedTradesTableAnnotationComposer({
    required super.$db,
    required super.$table,
    super.joinBuilder,
    super.$addJoinBuilderToRootComposer,
    super.$removeJoinBuilderFromRootComposer,
  });
  GeneratedColumn<int> get id =>
      $composableBuilder(column: $table.id, builder: (column) => column);

  GeneratedColumn<int> get ticket =>
      $composableBuilder(column: $table.ticket, builder: (column) => column);

  GeneratedColumn<String> get symbol =>
      $composableBuilder(column: $table.symbol, builder: (column) => column);

  GeneratedColumn<String> get direction =>
      $composableBuilder(column: $table.direction, builder: (column) => column);

  GeneratedColumn<String> get state =>
      $composableBuilder(column: $table.state, builder: (column) => column);

  GeneratedColumn<double> get profit =>
      $composableBuilder(column: $table.profit, builder: (column) => column);

  GeneratedColumn<String> get payload =>
      $composableBuilder(column: $table.payload, builder: (column) => column);

  GeneratedColumn<DateTime> get openedAt =>
      $composableBuilder(column: $table.openedAt, builder: (column) => column);
}

class $$CachedTradesTableTableManager extends RootTableManager<
    _$LocalDatabase,
    $CachedTradesTable,
    CachedTrade,
    $$CachedTradesTableFilterComposer,
    $$CachedTradesTableOrderingComposer,
    $$CachedTradesTableAnnotationComposer,
    $$CachedTradesTableCreateCompanionBuilder,
    $$CachedTradesTableUpdateCompanionBuilder,
    (
      CachedTrade,
      BaseReferences<_$LocalDatabase, $CachedTradesTable, CachedTrade>
    ),
    CachedTrade,
    PrefetchHooks Function()> {
  $$CachedTradesTableTableManager(_$LocalDatabase db, $CachedTradesTable table)
      : super(TableManagerState(
          db: db,
          table: table,
          createFilteringComposer: () =>
              $$CachedTradesTableFilterComposer($db: db, $table: table),
          createOrderingComposer: () =>
              $$CachedTradesTableOrderingComposer($db: db, $table: table),
          createComputedFieldComposer: () =>
              $$CachedTradesTableAnnotationComposer($db: db, $table: table),
          updateCompanionCallback: ({
            Value<int> id = const Value.absent(),
            Value<int> ticket = const Value.absent(),
            Value<String> symbol = const Value.absent(),
            Value<String> direction = const Value.absent(),
            Value<String> state = const Value.absent(),
            Value<double> profit = const Value.absent(),
            Value<String> payload = const Value.absent(),
            Value<DateTime> openedAt = const Value.absent(),
          }) =>
              CachedTradesCompanion(
            id: id,
            ticket: ticket,
            symbol: symbol,
            direction: direction,
            state: state,
            profit: profit,
            payload: payload,
            openedAt: openedAt,
          ),
          createCompanionCallback: ({
            Value<int> id = const Value.absent(),
            required int ticket,
            required String symbol,
            required String direction,
            required String state,
            Value<double> profit = const Value.absent(),
            required String payload,
            required DateTime openedAt,
          }) =>
              CachedTradesCompanion.insert(
            id: id,
            ticket: ticket,
            symbol: symbol,
            direction: direction,
            state: state,
            profit: profit,
            payload: payload,
            openedAt: openedAt,
          ),
          withReferenceMapper: (p0) => p0
              .map((e) => (e.readTable(table), BaseReferences(db, table, e)))
              .toList(),
          prefetchHooksCallback: null,
        ));
}

typedef $$CachedTradesTableProcessedTableManager = ProcessedTableManager<
    _$LocalDatabase,
    $CachedTradesTable,
    CachedTrade,
    $$CachedTradesTableFilterComposer,
    $$CachedTradesTableOrderingComposer,
    $$CachedTradesTableAnnotationComposer,
    $$CachedTradesTableCreateCompanionBuilder,
    $$CachedTradesTableUpdateCompanionBuilder,
    (
      CachedTrade,
      BaseReferences<_$LocalDatabase, $CachedTradesTable, CachedTrade>
    ),
    CachedTrade,
    PrefetchHooks Function()>;

class $LocalDatabaseManager {
  final _$LocalDatabase _db;
  $LocalDatabaseManager(this._db);
  $$CacheEntriesTableTableManager get cacheEntries =>
      $$CacheEntriesTableTableManager(_db, _db.cacheEntries);
  $$CachedSignalsTableTableManager get cachedSignals =>
      $$CachedSignalsTableTableManager(_db, _db.cachedSignals);
  $$CachedTradesTableTableManager get cachedTrades =>
      $$CachedTradesTableTableManager(_db, _db.cachedTrades);
}
