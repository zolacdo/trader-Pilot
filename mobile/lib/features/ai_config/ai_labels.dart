import 'models/ai_settings.dart';

/// Libellés et explications en français des notions d'intelligence hybride.
///
/// Un seul endroit pour les textes : l'écran de configuration et l'écran de
/// diagnostic doivent nommer les mêmes choses de la même façon.
abstract final class AiLabels {
  /// Nom court d'un mode.
  static String mode(String? code) => switch (code) {
        AiMode.single => 'Un seul avis',
        AiMode.ensemble => 'Deux avis confrontés',
        null => '--',
        _ => code,
      };

  /// Une phrase qui explique ce que le mode change concrètement.
  static String modeDescription(String code) => switch (code) {
        AiMode.single =>
          'Un seul modèle est interrogé. C’est plus rapide et cela consomme moins de '
              'quota, mais aucune erreur du modèle n’est rattrapée.',
        AiMode.ensemble =>
          'Deux modèles différents traitent la même question, puis leurs conclusions '
              'sont confrontées : la décision n’est retenue que si elles concordent.',
        _ => 'Mode renvoyé par le Bridge.',
      };

  /// Nom d'un moteur.
  static String provider(String? code) => switch (code?.toUpperCase()) {
        'OPENROUTER' => 'OpenRouter',
        null => '--',
        _ => code!,
      };

  /// État de santé d'un moteur (CDC2 section 96).
  static String health(String? code) => switch (code?.toUpperCase()) {
        'ONLINE' => 'En ligne',
        'DEGRADED' => 'Dégradé',
        'OFFLINE' => 'Hors service',
        null => '--',
        _ => code!,
      };

  /// Conduite à tenir quand les deux moteurs ne sont pas d'accord.
  static String disagreement(String? code) => switch (code) {
        AiDisagreement.noTrade => 'Aucun trade',
        AiDisagreement.manualReview => 'Revue manuelle',
        null => '--',
        _ => code,
      };

  /// Nature d'une tâche confiée à l'IA (`AITaskKind`).
  static String task(String? code) => switch (code?.toUpperCase()) {
        'SIGNAL_PARSE' => 'Lecture d’un signal',
        'NEWS_CLASSIFY' => 'Classement d’actualité',
        'NEWS_SUMMARY' => 'Résumé d’actualité',
        'MARKET_ANALYSIS' => 'Analyse de marché',
        'MACRO_ANALYSIS' => 'Analyse macro',
        'VISION' => 'Lecture de graphique',
        'OPPORTUNITY_REVIEW' => 'Revue d’opportunité',
        null => '--',
        _ => code!,
      };

  /// Taux 0..1 affiché en pourcentage, `--` si le Bridge n'a rien mesuré.
  static String rate(double? value) =>
      value == null ? '--' : '${(value * 100).toStringAsFixed(0)} %';

  /// Latence en millisecondes.
  static String latency(num? value) => value == null ? '--' : '${value.round()} ms';

  /// Oui / non, jamais une case vide.
  static String yesNo(bool? value) => value == null
      ? '--'
      : value
          ? 'Oui'
          : 'Non';
}
