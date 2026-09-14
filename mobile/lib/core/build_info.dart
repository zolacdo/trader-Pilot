/// Identité du binaire réellement installé.
///
/// `versionName` et `versionCode` sont restés figés à `1.0.0` / `1` pendant
/// toute la mise au point : rien, dans l'application, ne permettait de savoir
/// quelle version on avait sous les yeux. Vérifier exigeait un câble USB et un
/// `adb shell md5sum`. Ces valeurs-ci comblent ce trou.
///
/// Elles sont injectées à la compilation par `scripts/build_apk.ps1` via
/// `--dart-define`. Un build lancé à la main sans ces définitions affiche
/// « inconnu » : c'est volontaire, mieux vaut un aveu d'ignorance qu'une date
/// inventée au moment de l'affichage, qui indiquerait l'heure du lancement de
/// l'application plutôt que celle de sa compilation.
abstract final class BuildInfo {
  /// Horodatage de compilation, au format `2026-09-12 00:57`.
  static const String builtAt = String.fromEnvironment('BUILD_TIME');

  /// Douze premiers caractères de l'empreinte du binaire.
  static const String fingerprint = String.fromEnvironment('BUILD_FINGERPRINT');

  /// Numéro de build, qui croît à chaque compilation (`versionCode` Android).
  static const String number = String.fromEnvironment('BUILD_NUMBER');

  static bool get isKnown => builtAt.isNotEmpty;

  /// Ce qu'on affiche dans « À propos ».
  static String get label {
    if (!isKnown) return 'inconnu (build manuel)';
    final String suffix = number.isEmpty ? '' : ' · n° $number';
    return '$builtAt$suffix';
  }

  /// Empreinte courte, ou `--` quand elle n'a pas été injectée.
  static String get shortFingerprint =>
      fingerprint.isEmpty ? '--' : fingerprint;
}
