import 'package:intl/intl.dart';

/// Mises en forme partagees : montants, prix, dates, durees.
abstract final class Fmt {
  static final NumberFormat _money = NumberFormat.currency(locale: 'fr_FR', symbol: '', decimalDigits: 2);
  static final NumberFormat _percent = NumberFormat('#,##0.00', 'fr_FR');
  static final DateFormat _time = DateFormat('HH:mm', 'fr_FR');
  static final DateFormat _dayTime = DateFormat('dd/MM HH:mm', 'fr_FR');
  static final DateFormat _full = DateFormat('dd/MM/yyyy HH:mm:ss', 'fr_FR');
  static final DateFormat _day = DateFormat('dd/MM/yyyy', 'fr_FR');

  /// Montant avec devise, sans signe force.
  static String money(num? value, {String currency = 'USD', int digits = 2}) {
    if (value == null) return '--';
    return '${_money.format(value).trim()} $currency';
  }

  /// Montant signe : le signe rend la lecture d'un P&L immediate.
  static String signedMoney(num? value, {String currency = 'USD'}) {
    if (value == null) return '--';
    final String sign = value > 0 ? '+' : '';
    return '$sign${_money.format(value).trim()} $currency';
  }

  static String percent(num? value, {int digits = 2, bool signed = false}) {
    if (value == null) return '--';
    final String sign = signed && value > 0 ? '+' : '';
    return '$sign${_percent.format(value)} %';
  }

  /// Prix affiche avec la precision du symbole (5 decimales en forex,
  /// 2 sur l'or, 1 sur les indices).
  static String price(num? value, {int? digits}) {
    if (value == null) return '--';
    final int decimals = digits ?? _guessDigits(value);
    return value.toStringAsFixed(decimals);
  }

  static int _guessDigits(num value) {
    final double abs = value.abs().toDouble();
    if (abs >= 1000) return 2;
    if (abs >= 100) return 3;
    if (abs >= 10) return 4;
    return 5;
  }

  static String lots(num? value) => value == null ? '--' : value.toStringAsFixed(2);

  static String confidence(num? value) =>
      value == null ? '--' : '${(value * 100).round()} %';

  // --- dates ---
  static DateTime? parse(Object? raw) {
    if (raw == null) return null;
    if (raw is DateTime) return raw.toLocal();
    final String text = raw.toString();
    if (text.isEmpty) return null;
    return DateTime.tryParse(text)?.toLocal();
  }

  static String time(Object? raw) {
    final DateTime? date = parse(raw);
    return date == null ? '--' : _time.format(date);
  }

  static String dayTime(Object? raw) {
    final DateTime? date = parse(raw);
    return date == null ? '--' : _dayTime.format(date);
  }

  static String full(Object? raw) {
    final DateTime? date = parse(raw);
    return date == null ? '--' : _full.format(date);
  }

  static String day(Object? raw) {
    final DateTime? date = parse(raw);
    return date == null ? '--' : _day.format(date);
  }

  /// Affichage relatif court : "a l'instant", "il y a 4 min", "il y a 2 h".
  static String relative(Object? raw) {
    final DateTime? date = parse(raw);
    if (date == null) return '--';
    final Duration delta = DateTime.now().difference(date);
    if (delta.inSeconds < 60) return 'à l’instant';
    if (delta.inMinutes < 60) return 'il y a ${delta.inMinutes} min';
    if (delta.inHours < 24) return 'il y a ${delta.inHours} h';
    if (delta.inDays < 7) return 'il y a ${delta.inDays} j';
    return _day.format(date);
  }

  static String duration(int? seconds) {
    if (seconds == null) return '--';
    if (seconds < 60) return '$seconds s';
    if (seconds < 3600) return '${seconds ~/ 60} min';
    if (seconds < 86400) return '${seconds ~/ 3600} h';
    return '${seconds ~/ 86400} j';
  }

  /// Libelle francais d'un motif de refus renvoye par le Bridge.
  static String rejectionReason(String? code) {
    if (code == null || code.isEmpty) return 'Motif inconnu';
    return _rejectionLabels[code] ?? code.replaceAll('_', ' ').toLowerCase();
  }

  static const Map<String, String> _rejectionLabels = <String, String>{
    'BRIDGE_OFFLINE': 'Bridge hors ligne',
    'MT5_DISCONNECTED': 'MetaTrader 5 déconnecté',
    'AUTO_TRADING_OFF': 'Trading automatique désactivé',
    'TRADING_PAUSED': 'Automatisation en pause',
    'CHANNEL_DISABLED': 'Canal désactivé',
    'CHANNEL_OBSERVE_MODE': 'Canal en mode observation',
    'CHANNEL_NOT_ALLOWED': 'Canal non autorisé',
    'SYMBOL_NOT_ALLOWED': 'Instrument non autorisé',
    'SYMBOL_NOT_FOUND': 'Instrument introuvable chez le broker',
    'DIRECTION_NOT_ALLOWED': 'Direction non copiée',
    'DUPLICATE_SIGNAL': 'Signal en doublon',
    'SIGNAL_EXPIRED': 'Signal périmé',
    'LOW_CONFIDENCE': 'Confiance insuffisante',
    'MISSING_STOP_LOSS': 'Stop loss absent',
    'MISSING_TAKE_PROFIT': 'Take profit absent',
    'INVALID_ENTRY': 'Prix d’entrée invalide',
    'INVALID_STOP_LOSS': 'Stop loss invalide',
    'INVALID_TAKE_PROFIT': 'Take profit invalide',
    'RR_TOO_LOW': 'Ratio rendement/risque trop faible',
    'SPREAD_TOO_HIGH': 'Spread trop élevé',
    'MARKET_CLOSED': 'Marché fermé',
    'INVALID_VOLUME': 'Volume invalide',
    'INSUFFICIENT_MARGIN': 'Marge insuffisante',
    'RISK_TOO_HIGH': 'Risque trop élevé',
    'DAILY_LOSS_LIMIT': 'Limite de perte journalière atteinte',
    'DAILY_RISK_LIMIT': 'Limite de risque journalier atteinte',
    'DAILY_PROFIT_TARGET': 'Objectif de gain du jour atteint',
    'MAX_DRAWDOWN': 'Drawdown maximum atteint',
    'MAX_POSITIONS': 'Nombre maximum de positions atteint',
    'MAX_POSITIONS_SYMBOL': 'Maximum de positions sur cet instrument',
    'MAX_EXPOSURE': 'Exposition maximale atteinte',
    'CONSECUTIVE_LOSSES': 'Trop de pertes consécutives',
    'OUTSIDE_TRADING_HOURS': 'Hors plage horaire autorisée',
    'OUTSIDE_TRADING_DAYS': 'Jour non autorisé',
    'ORDER_CHECK_FAILED': 'Contrôle broker refusé',
    'ORDER_SEND_FAILED': 'Envoi de l’ordre refusé',
    'LOT_LIMIT': 'Limite de lot atteinte',
    'NO_ACTION': 'Aucune intention de trade',
    'MANUAL_REJECTION': 'Refusé manuellement',
    'ACCOUNT_MISMATCH': 'Type de compte incompatible',
    'LIVE_NOT_UNLOCKED': 'Mode réel non déverrouillé',
  };

  /// Libelle francais d'un statut de signal.
  static String signalStatus(String? code) {
    return switch (code) {
      'RECEIVED' => 'Reçu',
      'PARSED' => 'Interprété',
      'NEEDS_REVIEW' => 'À valider',
      'VALIDATED' => 'Validé',
      'REJECTED' => 'Refusé',
      'APPROVED' => 'Approuvé',
      'ORDER_CHECKED' => 'Contrôle broker OK',
      'SENT' => 'Ordre envoyé',
      'OPEN' => 'Position ouverte',
      'PARTIALLY_CLOSED' => 'Partiellement fermée',
      'MODIFIED' => 'Modifié',
      'CLOSED' => 'Clôturé',
      'FAILED' => 'Échec',
      'EXPIRED' => 'Périmé',
      'NO_ACTION' => 'Aucune action',
      'OBSERVED' => 'Observé',
      'CANCELLED' => 'Annulé',
      _ => code ?? '--',
    };
  }

  static String executionMode(String? code) {
    return switch (code) {
      'PAPER' => 'Paper Trading',
      'MT5_DEMO' => 'MT5 Demo',
      'MT5_LIVE' => 'MT5 Réel',
      _ => code ?? '--',
    };
  }

  static String channelMode(String? code) {
    return switch (code) {
      'OBSERVE' => 'Observation',
      'MANUAL' => 'Manuel',
      'AUTO' => 'Automatique',
      _ => code ?? '--',
    };
  }
}
