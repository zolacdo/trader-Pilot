import 'package:flutter_test/flutter_test.dart';
import 'package:tradepilot/core/build_info.dart';

/// Identité du binaire affichée dans « À propos ».
///
/// `versionName` et `versionCode` sont restés figés à `1.0.0` / `1` pendant
/// toute la mise au point : deux binaires différents s'affichaient donc à
/// l'identique, et savoir lequel tournait exigeait un câble USB et un
/// `adb shell md5sum`.
///
/// Ces tests s'exécutent SANS `--dart-define`, donc dans l'état « build
/// manuel ». C'est justement le cas qui compte : une application qui invente
/// une date serait pire que muette.
void main() {
  group('Identité du build', () {
    test('un build sans injection avoue son ignorance', () {
      // `flutter test` ne passe aucun --dart-define : on est exactement dans
      // la situation d'un `flutter build apk` lancé à la main.
      expect(BuildInfo.isKnown, isFalse);
      expect(BuildInfo.label, 'inconnu (build manuel)');
    });

    test('une empreinte absente se dit absente', () {
      expect(BuildInfo.shortFingerprint, '--');
    });

    test('rien n’est jamais inventé', () {
      // Le piège serait d'afficher DateTime.now() : la date changerait à
      // chaque ouverture de l'écran et indiquerait l'heure de consultation,
      // pas celle de la compilation.
      final String premier = BuildInfo.label;
      final String second = BuildInfo.label;
      expect(premier, second);
      expect(premier, isNot(contains(DateTime.now().year.toString())));
    });

    test('les valeurs injectées sont des constantes de compilation', () {
      // `String.fromEnvironment` doit être const : sinon la valeur serait lue
      // à l'exécution et vaudrait toujours la chaîne vide en release.
      const String valeur = BuildInfo.builtAt;
      expect(valeur, isEmpty);
    });
  });
}
