import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:tradepilot/core/routing/app_router.dart';
import 'package:tradepilot/core/theme/app_theme.dart';
import 'package:tradepilot/features/intelligence/labels.dart';
import 'package:tradepilot/features/news/news_screen.dart';

/// Défauts relevés par l'audit du code, avec leur scénario de déclenchement.

void main() {
  group('Libellés', () {
    test('la chaîne « null » n’est jamais affichée à l’utilisateur', () {
      // Les appelants écrivent couramment '${payload['champ']}'. Quand le
      // Bridge ne renseigne pas la valeur, cela produit littéralement « null »,
      // et l'écran l'affichait tel quel — par exemple « Régime : null » dans
      // le détail d'une décision.
      expect(labelFor(kRegimeLabels, 'null'), '—');
      expect(labelFor(kActionLabels, 'null'), '—');
      expect(labelFor(kImpactLabels, 'null', fallback: 'inconnu'), 'inconnu');
    });

    test('un code réel reste traduit, un code inconnu reste lisible', () {
      expect(labelFor(kRegimeLabels, 'RANGING'), 'Range');
      expect(labelFor(kRegimeLabels, 'NOUVEAU_REGIME'), 'NOUVEAU_REGIME');
    });
  });

  group('Navigation', () {
    test('le calendrier économique a son propre chemin', () {
      // « Ouvrir le calendrier », depuis une notification d'événement
      // économique, menait vers l'onglet Dépêches : on lisait « publication
      // imminente » et on tombait sur des titres de presse.
      expect(Routes.economicCalendar, isNot(Routes.news));
      expect(Routes.economicCalendar, '/more/calendar');
    });

    testWidgets('l’écran s’ouvre sur l’onglet demandé', (WidgetTester tester) async {
      tester.view.physicalSize = const Size(360, 690);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.reset);

      await tester.pumpWidget(
        ProviderScope(
          child: MaterialApp(
            theme: AppTheme.light(),
            home: const NewsScreen(initialTab: 1),
          ),
        ),
      );
      await tester.pump();

      final TabController controller = DefaultTabController.of(
        tester.element(find.byType(TabBar)),
      );
      expect(controller.index, 1, reason: 'le calendrier doit être l’onglet ouvert');
    });

    testWidgets('sans précision, les dépêches restent l’onglet par défaut',
        (WidgetTester tester) async {
      tester.view.physicalSize = const Size(360, 690);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.reset);

      await tester.pumpWidget(
        ProviderScope(
          child: MaterialApp(theme: AppTheme.light(), home: const NewsScreen()),
        ),
      );
      await tester.pump();

      final TabController controller = DefaultTabController.of(
        tester.element(find.byType(TabBar)),
      );
      expect(controller.index, 0);
    });
  });
}
