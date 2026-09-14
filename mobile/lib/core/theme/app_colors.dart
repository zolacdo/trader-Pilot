import 'package:flutter/material.dart';

/// Palette TradePilot.
///
/// Une seule vraie couleur d'accent : [primary]. Le vert et le rouge ne sont
/// utilises que lorsqu'ils portent un sens fonctionnel (profit, perte, achat,
/// vente, succes, erreur critique) et jamais comme decoration.
abstract final class AppColors {
  /// Accent unique de l'application.
  static const Color primary = Color(0xFF2563EB);
  static const Color primaryDark = Color(0xFF1D4ED8);
  static const Color primarySurface = Color(0xFFEFF4FF);

  // --- neutres clairs ---
  static const Color background = Color(0xFFF7F8FA);
  static const Color surface = Color(0xFFFFFFFF);
  static const Color surfaceMuted = Color(0xFFF2F4F7);
  static const Color border = Color(0xFFE4E7EC);
  static const Color borderStrong = Color(0xFFD0D5DD);

  // --- texte ---
  static const Color textPrimary = Color(0xFF101828);
  static const Color textSecondary = Color(0xFF475467);
  static const Color textTertiary = Color(0xFF98A2B3);
  static const Color textOnPrimary = Color(0xFFFFFFFF);

  // --- neutres sombres ---
  static const Color backgroundDark = Color(0xFF0F1115);
  static const Color surfaceDark = Color(0xFF171A21);
  static const Color surfaceMutedDark = Color(0xFF1F232C);
  static const Color borderDark = Color(0xFF2A2F3A);
  static const Color textPrimaryDark = Color(0xFFF2F4F7);
  static const Color textSecondaryDark = Color(0xFF98A2B3);

  // --- couleurs fonctionnelles, jamais decoratives ---
  /// Profit realise, position gagnante, direction BUY.
  static const Color profit = Color(0xFF067647);
  static const Color profitSurface = Color(0xFFECFDF3);

  /// Perte, position perdante, direction SELL.
  static const Color loss = Color(0xFFB42318);
  static const Color lossSurface = Color(0xFFFEF3F2);

  /// Avertissement : limite approchee, connexion instable.
  static const Color warning = Color(0xFFB54708);
  static const Color warningSurface = Color(0xFFFFFAEB);

  /// Etat neutre ou en attente.
  static const Color neutral = Color(0xFF475467);
  static const Color neutralSurface = Color(0xFFF2F4F7);

  /// Couleur d'un montant : vert au-dessus de zero, rouge en dessous,
  /// neutre a zero. Utilisee partout pour les P&L.
  static Color forAmount(num value, {bool dark = false}) {
    if (value > 0) return profit;
    if (value < 0) return loss;
    return dark ? textSecondaryDark : textSecondary;
  }
}
