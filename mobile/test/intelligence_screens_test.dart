import 'dart:convert';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:tradepilot/core/api/api_client.dart';
import 'package:tradepilot/core/connection/connection_controller.dart';
import 'package:tradepilot/core/theme/app_theme.dart';
import 'package:tradepilot/features/decisions/decisions_screen.dart';
import 'package:tradepilot/features/intelligence/labels.dart';
import 'package:tradepilot/features/markets/markets_screen.dart';
import 'package:tradepilot/features/news/news_screen.dart';
import 'package:tradepilot/features/notifications/notifications_screen.dart';
import 'package:tradepilot/features/opportunities/opportunities_screen.dart';

/// Les corps de réponse sont recopiés des routes du Bridge
/// (`app/api/v1/notifications.py`, `news.py`, `decisions.py`, `market.py`).
/// Si un nom de champ change côté Bridge, ces tests cessent de refléter la
/// réalité et doivent échouer.

const Map<String, List<String>> _jsonHeaders = <String, List<String>>{
  Headers.contentTypeHeader: <String>[Headers.jsonContentType],
};

final Map<String, dynamic> notificationsBody = <String, dynamic>{
  'items': <Map<String, dynamic>>[
    <String, dynamic>{
      'id': 7,
      'createdAt': '2026-09-11T06:10:00+00:00',
      'category': 'OPPORTUNITY',
      'priority': 'HIGH',
      'title': '🤖 OPPORTUNITÉ DÉTECTÉE — XAUUSD',
      'body': 'XAUUSD · ACHAT\n\nConfiance : 82 %',
      'data': <String, dynamic>{'route': 'opportunity', 'opportunityId': 3, 'symbol': 'XAUUSD'},
      'symbol': 'XAUUSD',
      'decisionId': 11,
      'newsId': null,
      'pushed': true,
      'pushError': null,
      'readAt': null,
    },
  ],
  'total': 1,
  'limit': 50,
  'offset': 0,
  'unread': 1,
  'unreadByCategory': <String, dynamic>{'OPPORTUNITY': 1},
  'categories': <String>['TRADE', 'OPPORTUNITY', 'NEWS', 'ECONOMIC', 'SYSTEM'],
};

final Map<String, dynamic> newsBody = <String, dynamic>{
  'total': 1,
  'count': 1,
  'limit': 50,
  'offset': 0,
  'items': <Map<String, dynamic>>[
    <String, dynamic>{
      'id': 4,
      'source': 'Réserve fédérale',
      'title': 'Décision de taux : statu quo',
      'url': 'https://example.org/fed',
      'publishedAt': '2026-09-11T05:00:00+00:00',
      'receivedAt': '2026-09-11T05:05:00+00:00',
      'summary': 'La Fed maintient ses taux inchangés.',
      'category': 'MONETARY_POLICY',
      'countries': <String>['US'],
      'entities': <String>[],
      'affectedAssets': <String>['XAUUSD'],
      'affectedCurrencies': <String>['USD'],
      'impactLevel': 'HIGH',
      'sentiment': 'NEUTRAL',
      'confidence': 0.8,
      'reason': 'Mots-clés de politique monétaire',
      'verification': 'CONFIRMED',
      'confirmations': 3,
      'duplicateOf': null,
      'aiProvider': null,
      'aiModel': null,
    },
  ],
};

/// Calendrier sans source configurée : cas réel tant que rien n'est déclaré.
final Map<String, dynamic> calendarBody = <String, dynamic>{
  'range': 'today',
  'from': '2026-09-11T00:00:00+00:00',
  'to': '2026-09-11T23:59:59+00:00',
  'configured': false,
  'count': 0,
  'items': <dynamic>[],
  'detail': 'Aucune source de calendrier économique n’est configurée.',
};

final Map<String, dynamic> decisionsBody = <String, dynamic>{
  'items': <Map<String, dynamic>>[
    <String, dynamic>{
      'id': 11,
      'createdAt': '2026-09-11T06:09:00+00:00',
      'symbol': 'XAUUSD',
      'source': 'AI_GENERATED',
      'action': 'NO_TRADE',
      'direction': 'BUY',
      'globalScore': 48.5,
      'confidence': 0.485,
      'regime': 'TRENDING_UP',
      'reason': 'Couverture insuffisante : trois composantes absentes.',
      'positiveFactors': <String>['Tendance alignée sur D1, H4 et H1.'],
      'negativeFactors': <String>['Analogues historiques non calculés.'],
      'executed': false,
      'shadow': true,
      'signalId': null,
      'opportunityId': 3,
      'tradeId': null,
    },
  ],
  'total': 1,
};

/// Aucune simulation clôturée : les statistiques ne doivent rien inventer.
final Map<String, dynamic> shadowEmptyBody = <String, dynamic>{
  'days': 30,
  'symbol': null,
  'disclaimer': 'Résultats simulés : aucun ordre n’a été envoyé.',
  'overall': <String, dynamic>{
    'simulated': 0,
    'skipped': 0,
    'closed': 0,
    'wins': 0,
    'losses': 0,
    'flat': 0,
    'winRate': null,
    'lossRate': null,
    'averageR': null,
    'totalR': 0.0,
    'maxDrawdownR': 0.0,
    'profitFactor': null,
  },
  'bySource': <String, dynamic>{},
  'byEngine': <String, dynamic>{},
};

final Map<String, dynamic> opportunitiesBody = <String, dynamic>{
  'items': <Map<String, dynamic>>[
    <String, dynamic>{
      'id': 3,
      'symbol': 'XAUUSD',
      'brokerSymbol': 'XAUUSDm',
      'createdAt': '2026-09-11T06:09:00+00:00',
      'expiresAt': '2026-09-11T06:39:00+00:00',
      'direction': 'BUY',
      'strategy': 'suivi_de_tendance',
      'entryMin': 2648.0,
      'entryMax': 2652.0,
      'entryPrice': 2650.0,
      'stopLoss': 2640.0,
      'takeProfits': <double>[2670.0, 2690.0],
      'expectedRr': 2.0,
      'confidence': 0.82,
      'status': 'PENDING',
      'reasons': <String>['Structure haussière confirmée.'],
      'negativeFactors': <String>['Spread supérieur à la normale.'],
      'decisionId': 11,
      'signalId': null,
    },
  ],
  'total': 1,
};

final Map<String, dynamic> intelligenceStatusBody = <String, dynamic>{
  'started': true,
  'scan': <String, dynamic>{
    'name': 'scan',
    'running': false,
    'lastRunAt': '2026-09-11T06:08:00+00:00',
    'lastError': null,
    'runs': 4,
    'failures': 0,
    'detail': '1 qualifiée(s) / 3 analysée(s)',
  },
  'news': <String, dynamic>{'name': 'news', 'running': false, 'runs': 1, 'failures': 0},
  'calendar': <String, dynamic>{'name': 'calendar', 'running': false, 'runs': 2, 'failures': 0},
  'lastCycle': null,
  'intervals': <String, dynamic>{
    'enabled': true,
    'scanMinutes': 5.0,
    'newsMinutes': 20.0,
    'calendarMinutes': 2.0,
  },
};

final Map<String, dynamic> watchlistBody = <String, dynamic>{
  'count': 1,
  'items': <Map<String, dynamic>>[
    <String, dynamic>{
      'id': 1,
      'symbol': 'XAUUSD',
      'brokerSymbol': 'XAUUSDm',
      'enabled': true,
      'available': true,
      'scanPriority': 1,
      'allowAiTrading': false,
      'allowTelegramTrading': true,
      'notifyNews': true,
      'notifyOpportunities': true,
      'notifyVolatility': true,
      'lastScannedAt': '2026-09-11T06:08:00+00:00',
      'addedAt': '2026-09-01T10:00:00+00:00',
      'updatedAt': '2026-09-11T06:08:00+00:00',
    },
  ],
};

/// Watchlist non encore analysée : aucun instantané disponible.
final Map<String, dynamic> emptyScanBody = <String, dynamic>{
  'count': 0,
  'items': <dynamic>[],
};

class _FakeAdapter implements HttpClientAdapter {
  _FakeAdapter({this.failing = false});

  final bool failing;
  final List<RequestOptions> requests = <RequestOptions>[];

  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<Uint8List>? requestStream,
    Future<void>? cancelFuture,
  ) async {
    requests.add(options);
    if (failing) {
      return ResponseBody.fromString(
        jsonEncode(<String, dynamic>{'detail': 'Bridge injoignable'}),
        503,
        headers: _jsonHeaders,
      );
    }
    return ResponseBody.fromString(
      jsonEncode(_bodyFor(options.path) ?? <String, dynamic>{}),
      200,
      headers: _jsonHeaders,
    );
  }

  Object? _bodyFor(String path) {
    if (path.endsWith('/notifications/unread-count')) {
      return <String, dynamic>{'unread': 1, 'byCategory': <String, dynamic>{}};
    }
    if (path.endsWith('/notifications')) return notificationsBody;
    if (path.endsWith('/economic-calendar')) return calendarBody;
    if (path.endsWith('/news')) return newsBody;
    if (path.endsWith('/decisions')) return decisionsBody;
    if (path.endsWith('/shadow/performance')) return shadowEmptyBody;
    if (path.endsWith('/opportunities')) return opportunitiesBody;
    if (path.endsWith('/intelligence/status')) return intelligenceStatusBody;
    if (path.endsWith('/market/watchlist')) return watchlistBody;
    if (path.endsWith('/market/scan')) return emptyScanBody;
    return null;
  }

  @override
  void close({bool force = false}) {}
}

ApiClient _client(_FakeAdapter adapter) {
  final Dio dio = Dio()..httpClientAdapter = adapter;
  return ApiClient(dio: dio)
    ..configure(baseUrl: 'http://bridge.test', token: 'jeton-de-test');
}

Future<void> _pump(WidgetTester tester, Widget screen, {_FakeAdapter? adapter}) async {
  tester.view.physicalSize = const Size(360, 690);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(
    ProviderScope(
      overrides: <Override>[
        apiClientProvider.overrideWithValue(_client(adapter ?? _FakeAdapter())),
      ],
      child: MaterialApp(theme: AppTheme.light(), home: screen),
    ),
  );
  await tester.pumpAndSettle();
}

void main() {
  group('Libellés partagés', () {
    test('un code connu est traduit, un code inconnu reste lisible', () {
      expect(labelFor(kImpactLabels, 'HIGH'), 'Élevé');
      expect(labelFor(kRegimeLabels, 'TRENDING_UP'), 'Tendance haussière');
      // Un code ajouté plus tard côté Bridge doit rester visible tel quel :
      // le masquer ferait disparaître l'information sans prévenir.
      expect(labelFor(kImpactLabels, 'EXTREME'), 'EXTREME');
      expect(labelFor(kImpactLabels, null), '—');
    });

    test('une valeur absente ne s’affiche jamais « null »', () {
      expect(number(null), '—');
      expect(number(2.5), '2.50');
      expect(percentFromRatio(null), '—');
      expect(percentFromRatio(0.82), '82 %');
    });
  });

  group('Notifications', () {
    testWidgets('l’inbox affiche la notification et son état non lu',
        (WidgetTester tester) async {
      await _pump(tester, const NotificationsScreen());
      expect(find.textContaining('OPPORTUNITÉ DÉTECTÉE'), findsOneWidget);
      expect(find.text('Opportunités'), findsWidgets);
      expect(find.text('Haute'), findsOneWidget);
      expect(find.text('XAUUSD'), findsOneWidget);
    });

    testWidgets('une panne du Bridge est annoncée, pas masquée',
        (WidgetTester tester) async {
      await _pump(tester, const NotificationsScreen(), adapter: _FakeAdapter(failing: true));
      expect(find.textContaining('Bridge injoignable'), findsWidgets);
    });
  });

  group('Actualités', () {
    testWidgets('une dépêche affiche sa source, son impact et ses confirmations',
        (WidgetTester tester) async {
      await _pump(tester, const NewsScreen());
      expect(find.text('Décision de taux : statu quo'), findsOneWidget);
      expect(find.text('Impact élevé'), findsOneWidget);
      expect(find.text('3 sources'), findsOneWidget);
    });

    testWidgets('sans source de calendrier, l’écran le dit clairement',
        (WidgetTester tester) async {
      await _pump(tester, const NewsScreen());
      await tester.tap(find.text('Calendrier'));
      await tester.pumpAndSettle();
      expect(find.text('Aucune source de calendrier'), findsOneWidget);
      expect(find.textContaining('n’est configurée'), findsOneWidget);
    });
  });

  group('Décisions', () {
    testWidgets('une décision non prise reste lisible avec son motif',
        (WidgetTester tester) async {
      await _pump(tester, const DecisionsScreen());
      expect(find.text('Ne pas trader'), findsOneWidget);
      expect(find.text('49/100'), findsOneWidget);
      expect(find.textContaining('Couverture insuffisante'), findsOneWidget);
      expect(find.text('Observation'), findsOneWidget);
    });

    testWidgets('sans simulation clôturée, aucune statistique n’est inventée',
        (WidgetTester tester) async {
      await _pump(tester, const DecisionsScreen());
      await tester.tap(find.text('Mode observation'));
      await tester.pumpAndSettle();
      expect(find.text('Aucune simulation clôturée'), findsOneWidget);
      // Surtout pas de « 0 % » ni de facteur de profit fabriqué.
      expect(find.text('0 %'), findsNothing);
    });
  });

  group('Opportunités', () {
    testWidgets('le plan chiffré est affiché tel que le Bridge l’a calculé',
        (WidgetTester tester) async {
      await _pump(tester, const OpportunitiesScreen());
      expect(find.text('XAUUSD'), findsOneWidget);
      expect(find.text('BUY'), findsOneWidget);
      expect(find.text('82 %'), findsOneWidget);
      expect(find.text('2650.00000'), findsOneWidget);
      expect(find.text('2640.00000'), findsOneWidget);
      expect(find.text('2.00'), findsOneWidget);
      expect(find.textContaining('Structure haussière'), findsOneWidget);
    });

    testWidgets('l’état du scan automatique est rappelé', (WidgetTester tester) async {
      await _pump(tester, const OpportunitiesScreen());
      expect(find.textContaining('Analyse automatique active'), findsOneWidget);
    });
  });

  group('Marchés', () {
    testWidgets('un instrument jamais analysé le dit au lieu d’afficher des tirets',
        (WidgetTester tester) async {
      await _pump(tester, const MarketsScreen());
      expect(find.text('XAUUSD'), findsOneWidget);
      expect(find.text('Pas encore analysé.'), findsOneWidget);
    });
  });
}
