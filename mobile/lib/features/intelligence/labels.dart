import 'package:flutter/material.dart';

import '../../core/widgets/app_widgets.dart';

/// Libelles et couleurs partages par les ecrans d'intelligence de marche.
///
/// Le Bridge renvoie des codes stables (`HIGH`, `TRENDING_UP`, `NO_TRADE`…).
/// L'application les traduit ici, en un seul endroit : un code inconnu est
/// affiche tel quel plutot que masque, pour qu'une evolution du Bridge se voie
/// au lieu de disparaitre silencieusement.

const Map<String, String> kImpactLabels = <String, String>{
  'LOW': 'Faible',
  'MEDIUM': 'Moyen',
  'HIGH': 'Élevé',
  'CRITICAL': 'Critique',
};

const Map<String, String> kSentimentLabels = <String, String>{
  'POSITIVE': 'Positif',
  'NEGATIVE': 'Négatif',
  'NEUTRAL': 'Neutre',
  'MIXED': 'Contrasté',
};

const Map<String, String> kRegimeLabels = <String, String>{
  'TRENDING_UP': 'Tendance haussière',
  'TRENDING_DOWN': 'Tendance baissière',
  'RANGING': 'Range',
  'HIGH_VOLATILITY': 'Volatilité élevée',
  'LOW_VOLATILITY': 'Volatilité faible',
  'BREAKOUT': 'Cassure',
  'NEWS_DRIVEN': 'Piloté par l’actualité',
  'UNCERTAIN': 'Incertain',
};

const Map<String, String> kActionLabels = <String, String>{
  'BUY': 'Acheter',
  'SELL': 'Vendre',
  'WAIT': 'Attendre',
  'NO_TRADE': 'Ne pas trader',
  'NEEDS_REVIEW': 'À revoir',
  'CLOSE': 'Clôturer',
  'REDUCE': 'Réduire',
};

const Map<String, String> kSourceLabels = <String, String>{
  'AI_GENERATED': 'Généré par l’IA',
  'TELEGRAM': 'Signal Telegram',
  'MANUAL': 'Manuel',
  'UNKNOWN': 'Origine inconnue',
};

const Map<String, String> kCategoryLabels = <String, String>{
  'TRADE': 'Trades',
  'OPPORTUNITY': 'Opportunités',
  'SIGNAL': 'Signaux',
  'NEWS': 'Actualités',
  'ECONOMIC': 'Calendrier',
  'RISK': 'Risque',
  'SYSTEM': 'Système',
  'MARKET': 'Marché',
  'REPORT': 'Rapports',
  'AI': 'Intelligence artificielle',
};

const Map<String, String> kPriorityLabels = <String, String>{
  'LOW': 'Basse',
  'MEDIUM': 'Moyenne',
  'HIGH': 'Haute',
  'CRITICAL': 'Critique',
};

const Map<String, String> kVerificationLabels = <String, String>{
  'UNCONFIRMED': 'Non confirmée',
  'CONFIRMED': 'Confirmée',
  'SINGLE_SOURCE': 'Source unique',
  'DISPUTED': 'Contestée',
};

const Map<String, String> kTrendLabels = <String, String>{
  'BULLISH': 'Haussière',
  'BEARISH': 'Baissière',
  'NEUTRAL': 'Neutre',
};

/// Traduit un code, ou le rend tel quel s'il est inconnu du dictionnaire.
///
/// La chaîne `'null'` est traitée comme une absence : les appelants écrivent
/// couramment `'\${payload['champ']}'`, ce qui produit littéralement « null »
/// quand le Bridge n'a pas renseigné la valeur. Sans cette garde, l'écran
/// affichait le mot « null » à l'utilisateur.
String labelFor(Map<String, String> dictionary, String? code, {String fallback = '—'}) {
  if (code == null || code.isEmpty || code == 'null') return fallback;
  return dictionary[code.toUpperCase()] ?? code;
}

/// Ton d'affichage d'un niveau d'impact.
StatusTone impactTone(String? impact) {
  return switch ((impact ?? '').toUpperCase()) {
    'CRITICAL' => StatusTone.bad,
    'HIGH' => StatusTone.warning,
    'MEDIUM' => StatusTone.accent,
    _ => StatusTone.neutral,
  };
}

/// Ton d'affichage d'une action de decision.
StatusTone actionTone(String? action) {
  return switch ((action ?? '').toUpperCase()) {
    'BUY' => StatusTone.good,
    'SELL' => StatusTone.bad,
    'NO_TRADE' => StatusTone.neutral,
    'NEEDS_REVIEW' => StatusTone.warning,
    'WAIT' => StatusTone.accent,
    _ => StatusTone.neutral,
  };
}

StatusTone priorityTone(String? priority) {
  return switch ((priority ?? '').toUpperCase()) {
    'CRITICAL' => StatusTone.bad,
    'HIGH' => StatusTone.warning,
    'MEDIUM' => StatusTone.accent,
    _ => StatusTone.neutral,
  };
}

StatusTone sentimentTone(String? sentiment) {
  return switch ((sentiment ?? '').toUpperCase()) {
    'POSITIVE' => StatusTone.good,
    'NEGATIVE' => StatusTone.bad,
    _ => StatusTone.neutral,
  };
}

IconData categoryIcon(String? category) {
  return switch ((category ?? '').toUpperCase()) {
    'TRADE' => Icons.candlestick_chart_outlined,
    'OPPORTUNITY' => Icons.auto_awesome_outlined,
    'SIGNAL' => Icons.sensors_outlined,
    'NEWS' => Icons.public_outlined,
    'ECONOMIC' => Icons.event_outlined,
    'RISK' => Icons.shield_outlined,
    'MARKET' => Icons.show_chart_outlined,
    'REPORT' => Icons.summarize_outlined,
    'AI' => Icons.psychology_outlined,
    _ => Icons.settings_outlined,
  };
}

/// Date courte et lisible : « 11/09 06:13 », ou « — » si absente.
String shortMoment(String? isoDate) {
  final DateTime? moment = parseMoment(isoDate);
  if (moment == null) return '—';
  final DateTime local = moment.toLocal();
  String two(int value) => value.toString().padLeft(2, '0');
  return '${two(local.day)}/${two(local.month)} ${two(local.hour)}:${two(local.minute)}';
}

/// Anciennete lisible : « à l’instant », « il y a 12 min », « il y a 3 h ».
String relativeMoment(String? isoDate) {
  final DateTime? moment = parseMoment(isoDate);
  if (moment == null) return '—';
  final Duration elapsed = DateTime.now().difference(moment.toLocal());
  if (elapsed.isNegative) {
    final Duration remaining = -elapsed;
    if (remaining.inMinutes < 60) return 'dans ${remaining.inMinutes} min';
    if (remaining.inHours < 24) return 'dans ${remaining.inHours} h';
    return 'dans ${remaining.inDays} j';
  }
  if (elapsed.inMinutes < 1) return 'à l’instant';
  if (elapsed.inMinutes < 60) return 'il y a ${elapsed.inMinutes} min';
  if (elapsed.inHours < 24) return 'il y a ${elapsed.inHours} h';
  return 'il y a ${elapsed.inDays} j';
}

DateTime? parseMoment(String? isoDate) {
  if (isoDate == null || isoDate.isEmpty) return null;
  return DateTime.tryParse(isoDate);
}

/// Nombre formate, ou tiret cadratin : on n'affiche jamais « null ».
String number(Object? value, {int digits = 2}) {
  if (value is num) return value.toStringAsFixed(digits);
  return '—';
}

/// Pourcentage a partir d'un ratio 0-1.
String percentFromRatio(Object? value, {int digits = 0}) {
  if (value is num) return '${(value * 100).toStringAsFixed(digits)} %';
  return '—';
}
