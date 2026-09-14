import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:intl/date_symbol_data_local.dart';
import 'package:tradepilot/core/theme/app_theme.dart';
import 'package:tradepilot/features/channels/models/channel.dart';
import 'package:tradepilot/features/channels/models/discovery.dart';
import 'package:tradepilot/features/channels/widgets/channel_analysis_view.dart';
import 'package:tradepilot/features/channels/widgets/channel_mode_selector.dart';
import 'package:tradepilot/features/channels/widgets/compare_table_view.dart';
import 'package:tradepilot/features/signals/models/signal.dart';
import 'package:tradepilot/features/signals/widgets/signal_card.dart';
import 'package:tradepilot/features/signals/widgets/signal_timeline.dart';

/// Rend un widget dans un écran de téléphone étroit (360 points de large).
Future<void> _pump(WidgetTester tester, Widget child) async {
  tester.view.physicalSize = const Size(360, 690);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(
    ProviderScope(
      child: MaterialApp(
        theme: AppTheme.light(),
        home: Scaffold(
          body: SingleChildScrollView(
            child: Padding(padding: const EdgeInsets.all(16), child: child),
          ),
        ),
      ),
    ),
  );
  await tester.pump();
}

void main() {
  setUpAll(() => initializeDateFormatting('fr_FR'));

  final Signal rejected = Signal.fromJson(const <String, dynamic>{
    'id': 12,
    'channelId': 3,
    'receivedAt': '2026-09-10T10:00:00+00:00',
    'symbol': 'GOLD',
    'normalizedSymbol': 'XAUUSD',
    'direction': 'BUY',
    'orderType': 'MARKET',
    'entryPrice': 2345.5,
    'stopLoss': 2338.0,
    'takeProfits': <double>[2352.0, 2360.0],
    'confidence': 0.82,
    'parserSource': 'deterministic',
    'status': 'REJECTED',
    'rejectionReason': 'SPREAD_TOO_HIGH',
    'rejectionDetail': 'Spread observé : 42 points.',
  });

  testWidgets('la carte de signal affiche le motif quand le signal est refusé',
      (WidgetTester tester) async {
    await _pump(tester, SignalCard(signal: rejected, channelTitle: 'Gold Signals'));

    expect(find.text('XAUUSD'), findsOneWidget);
    expect(find.text('BUY'), findsOneWidget);
    expect(find.text('Refusé'), findsOneWidget);
    expect(find.textContaining('Spread trop élevé'), findsOneWidget);
    expect(find.textContaining('Spread observé'), findsOneWidget);
  });

  testWidgets('une valeur absente s\'affiche -- et n\'est jamais inventée',
      (WidgetTester tester) async {
    final Signal bare = Signal.fromJson(const <String, dynamic>{'id': 7, 'status': 'RECEIVED'});
    await _pump(tester, SignalCard(signal: bare));

    // Instrument, entrée, SL, TP, confiance et canal sont tous inconnus.
    expect(find.text('--'), findsWidgets);
  });

  testWidgets('la chronologie marque une étape en échec', (WidgetTester tester) async {
    await _pump(
      tester,
      SignalTimeline(
        steps: <SignalStep>[
          SignalStep.fromJson(const <String, dynamic>{
            'stage': 'parser',
            'success': true,
            'message': 'Signal interprété par le parser local',
            'createdAt': '2026-09-10T10:00:00+00:00',
          }),
          SignalStep.fromJson(const <String, dynamic>{
            'stage': 'order_send',
            'success': false,
            'message': 'Le broker a refusé l\'ordre',
            'createdAt': '2026-09-10T10:00:05+00:00',
          }),
        ],
      ),
    );

    expect(find.text('Parser'), findsOneWidget);
    expect(find.text('Envoi de l\'ordre (order_send)'), findsOneWidget);
    expect(find.byIcon(Icons.error_outline), findsOneWidget);
  });

  testWidgets('le rapport d\'analyse reste factuel et affiche les avertissements',
      (WidgetTester tester) async {
    final ChannelAnalysis analysis = ChannelAnalysis.fromJson(const <String, dynamic>{
      'id': 1,
      'createdAt': '2026-09-10T10:00:00+00:00',
      'messagesScanned': 250,
      'signalLikeMessages': 120,
      'parsedMessages': 107,
      'duplicateSignals': 4,
      'structureQuality': 92.0,
      'withStopLossRate': 95.0,
      'withTakeProfitRate': 98.0,
      'parseableRate': 89.0,
      'signalsPerDay': 4.2,
      'symbols': <String, dynamic>{'XAUUSD': 80, 'EURUSD': 27},
      'directions': <String, dynamic>{'BUY': 60, 'SELL': 47},
      'disclaimer': 'Mesures factuelles observees sur les messages analyses.',
      'backtest': <String, dynamic>{
        'testable': 90,
        'wins': 40,
        'losses': 35,
        'ambiguous': 9,
        'undetermined': 6,
        'open': 0,
        'averageR': 0.12,
        'theoreticalDrawdownR': 4.5,
        'disclaimer': 'Simulation historique indicative.',
      },
    });

    await _pump(tester, ChannelAnalysisView(analysis: analysis));

    expect(find.text('92,0 %'), findsOneWidget);
    expect(find.text('4,2 / jour'), findsOneWidget);
    expect(find.textContaining('Mesures factuelles'), findsOneWidget);
    expect(find.textContaining('jamais compté comme gagné'), findsOneWidget);
    expect(find.textContaining('Simulation historique indicative'), findsOneWidget);
  });

  testWidgets('la légende des modes dit que l\'observation ne trade jamais',
      (WidgetTester tester) async {
    await _pump(tester, const ChannelModeLegend());

    expect(find.textContaining('Aucun ordre n\'est jamais envoyé.'), findsOneWidget);
    expect(find.textContaining('attend votre confirmation'), findsOneWidget);
    expect(find.textContaining('toutes les protections passent'), findsOneWidget);
  });

  testWidgets('le tableau de comparaison ne désigne aucun meilleur canal',
      (WidgetTester tester) async {
    final List<CompareRow> rows = <CompareRow>[
      CompareRow.fromJson(const <String, dynamic>{
        'channelId': 1,
        'title': 'Gold Signals',
        'username': 'goldsignals',
        'signalsDetected': 107,
        'parseRate': 89.0,
        'paperTrades': 12,
        'paperPnl': 24.5,
        'historyAvailable': true,
      }),
      CompareRow.fromJson(const <String, dynamic>{
        'channelId': 2,
        'title': 'FX Room',
        'signalsDetected': null,
      }),
    ];

    await _pump(tester, CompareTableView(rows: rows));

    expect(find.text('Gold Signals'), findsOneWidget);
    expect(find.text('FX Room'), findsOneWidget);
    // Les colonnes sans mesure restent vides plutôt que remplies au hasard.
    expect(find.text('--'), findsWidgets);
    expect(find.textContaining('meilleur'), findsNothing);
  });
}
