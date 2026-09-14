import 'package:flutter/widgets.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:tradepilot/features/news/news_screen.dart';

/// Les cartes du calendrier ne montrent que les chiffres réellement fournis.
///
/// Constaté à l'écran le 12/09/2026 : chaque événement affichait « PRÉVISION —
/// PRÉCÉDENT — PUBLIÉ — ». Mesuré ensuite sur la source : le calendrier
/// hebdomadaire de Forex Factory n'expose que `country, date, forecast,
/// impact, previous, title`. Le champ `actual` n'existe pas, donc la colonne
/// « Publié » ne pouvait structurellement jamais être remplie.
void main() {
  group('Chiffres d’un événement économique', () {
    test('une source sans valeur publiée n’affiche pas la colonne', () {
      // Ligne réelle du flux : ni valeur publiée, ni prévision.
      final List<Widget> widgets = buildEventMetrics(<String, dynamic>{
        'title': 'BRICS Summit',
        'forecast': '',
        'previous': '',
      });

      expect(widgets, isEmpty, reason: 'une rangée creuse ne renseigne sur rien');
    });

    test('seules les colonnes renseignées sont construites', () {
      final List<Widget> widgets = buildEventMetrics(<String, dynamic>{
        'forecast': '117.9%',
        'previous': '116.4%',
        'actual': null,
      });

      // Un espacement plus la rangée : la rangée porte deux colonnes sur trois.
      expect(widgets, hasLength(2));
      final Row rangee = widgets.last as Row;
      expect(rangee.children, hasLength(2));
    });

    test('les trois colonnes apparaissent quand la source les fournit', () {
      final List<Widget> widgets = buildEventMetrics(<String, dynamic>{
        'forecast': '0.2%',
        'previous': '0.1%',
        'actual': '0.3%',
      });

      final Row rangee = widgets.last as Row;
      expect(rangee.children, hasLength(3));
    });

    test('une valeur faite d’espaces compte comme absente', () {
      final List<Widget> widgets = buildEventMetrics(<String, dynamic>{
        'forecast': '   ',
        'previous': '116.4%',
      });

      final Row rangee = widgets.last as Row;
      expect(rangee.children, hasLength(1));
    });

    test('un événement sans aucun champ ne casse rien', () {
      expect(buildEventMetrics(<String, dynamic>{}), isEmpty);
    });
  });
}
