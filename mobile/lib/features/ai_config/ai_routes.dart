/// Chemins des écrans d'intelligence artificielle.
///
/// Ces constantes sont déclarées ici pour que la fonctionnalité soit autonome ;
/// c'est le routeur de l'application qui les associe aux écrans
/// [AiConfigScreen] et [AiDiagnosticScreen].
abstract final class AiRoutes {
  /// Configuration de l'intelligence artificielle (CDC2 section 95).
  static const String config = '/more/ai-config';

  /// Diagnostic des moteurs et du routeur (CDC2 section 96).
  static const String diagnostic = '/more/ai-diagnostic';
}
