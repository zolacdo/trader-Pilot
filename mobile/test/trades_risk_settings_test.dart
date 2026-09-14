import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:intl/date_symbol_data_local.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:tradepilot/core/api/api_client.dart';
import 'package:tradepilot/features/more/more_screen.dart';
import 'package:tradepilot/features/positions/widgets/closed_trades_view.dart';
import 'package:tradepilot/features/settings/settings_providers.dart';
import 'package:tradepilot/features/settings/widgets/openrouter_section.dart';
import 'package:tradepilot/features/settings/widgets/trading_section.dart';
import 'package:tradepilot/core/providers/bridge_data.dart';
import 'package:tradepilot/core/theme/app_theme.dart';
import 'package:tradepilot/features/positions/trades_models.dart';
import 'package:tradepilot/features/positions/trades_providers.dart';
import 'package:tradepilot/features/positions/widgets/open_positions_view.dart';
import 'package:tradepilot/features/positions/widgets/pending_orders_view.dart';
import 'package:tradepilot/features/positions/widgets/trades_header.dart';
import 'package:tradepilot/features/risk/risk_form.dart';
import 'package:tradepilot/features/risk/widgets/risk_limits_sections.dart';
import 'package:tradepilot/features/risk/widgets/risk_management_sections.dart';
import 'package:tradepilot/features/settings/symbol_mapping_providers.dart';
import 'package:tradepilot/features/settings/symbol_mapping_screen.dart';
import 'package:tradepilot/features/settings/widgets/connection_sections.dart';
import 'package:tradepilot/features/settings/widgets/device_sections.dart';

Future<void> _pump(WidgetTester tester, Widget child, {List<Override> overrides = const <Override>[]}) async {
  tester.view.physicalSize = const Size(360, 690);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(
    ProviderScope(
      overrides: overrides,
      child: MaterialApp(theme: AppTheme.light(), home: child),
    ),
  );
  await tester.pumpAndSettle();
}

final Map<String, dynamic> _position = <String, dynamic>{
  'ticket': 12345678,
  'symbol': 'XAUUSD',
  'direction': 'BUY',
  'volume': 0.05,
  'openPrice': 2345.12,
  'currentPrice': 2350.44,
  'stopLoss': 2340.0,
  'takeProfit': 2360.0,
  'profit': 26.6,
  'openedAt': '2026-09-10T09:12:00',
  'signalId': 42,
  'channelId': 1,
  'takeProfitTargets': <double>[2360.0, 2370.0, 2380.0],
  'tpIndex': 1,
  'breakEvenApplied': true,
  'managedByTradePilot': true,
};

final Map<String, dynamic> _order = <String, dynamic>{
  'ticket': 999,
  'symbol': 'EURUSD',
  'orderType': 'BUY_LIMIT',
  'direction': 'BUY',
  'volume': 0.02,
  'price': 1.0812,
  'stopLoss': 1.0780,
  'takeProfit': 1.0900,
  'createdAt': '2026-09-10T08:00:00',
  'signalId': 7,
  'managedByTradePilot': true,
};

void main() {
  setUpAll(() async => initializeDateFormatting('fr_FR'));

  testWidgets('positions ouvertes', (WidgetTester tester) async {
    await _pump(
      tester,
      const Scaffold(body: OpenPositionsView()),
      overrides: <Override>[
        openPositionsProvider.overrideWith((Ref<Object?> ref) async => PositionsSnapshot.fromJson(
              <String, dynamic>{
                'executionMode': 'MT5_DEMO',
                'items': <Map<String, dynamic>>[_position],
              },
            )),
        channelNamesProvider.overrideWith((Ref<Object?> ref) async => <int, String>{1: 'Canal Or Premium'}),
      ],
    );
    expect(find.text('XAUUSD'), findsOneWidget);
  });

  testWidgets('ordres en attente', (WidgetTester tester) async {
    await _pump(
      tester,
      const Scaffold(body: PendingOrdersView()),
      overrides: <Override>[
        pendingOrdersProvider.overrideWith((Ref<Object?> ref) async => OrdersSnapshot.fromJson(
              <String, dynamic>{
                'executionMode': 'PAPER',
                'items': <Map<String, dynamic>>[_order],
              },
            )),
      ],
    );
    expect(find.text('Achat limite · 0.02 lot · ticket 999'), findsOneWidget);
  });

  testWidgets('bandeau trades', (WidgetTester tester) async {
    await _pump(
      tester,
      const Scaffold(body: TradesHeader()),
      overrides: <Override>[
        tradingStateProvider.overrideWith((Ref<Object?> ref) async => <String, dynamic>{
              'executionMode': 'MT5_LIVE',
              'autoTradingEnabled': true,
              'paused': true,
              'pauseReason': 'trop de pertes consécutives',
            }),
        openPositionsProvider.overrideWith((Ref<Object?> ref) async => PositionsSnapshot.fromJson(
              <String, dynamic>{
                'executionMode': 'MT5_LIVE',
                'items': <Map<String, dynamic>>[_position],
              },
            )),
      ],
    );
    expect(find.text('MT5 réel'), findsOneWidget);
  });

  testWidgets('formulaire de risque', (WidgetTester tester) async {
    final RiskFormController controller = RiskFormController(ApiClient());
    const RiskDraft draft = RiskDraft(original: <String, dynamic>{
      'riskPercent': 1.0,
      'maxDailyLossPercent': 3.0,
      'maxPositions': 5,
      'requireStopLoss': true,
      'tradingHoursStart': '08:00',
      'tradingHoursEnd': '22:00',
      'tradingDays': <int>[0, 1, 2, 3, 4],
      'allowedSymbols': <String>['XAUUSD'],
      'multiTpStrategy': 'PARTIAL_CLOSE',
      'splitRatios': <double>[40, 30, 30],
      'breakEvenEnabled': true,
      'breakEvenTrigger': 'R_MULTIPLE',
      'trailingMode': 'FIXED_DISTANCE',
      'paperBalance': 10000.0,
      'paperCurrency': 'USD',
    });
    await _pump(
      tester,
      Scaffold(
        body: SingleChildScrollView(
          child: Column(
            children: <Widget>[
              RiskLimitsSections(
                draft: draft,
                controller: controller,
                reference: const RiskReference(balance: 10000, currency: 'USD'),
              ),
              RiskManagementSections(draft: draft, controller: controller),
            ],
          ),
        ),
      ),
    );
    expect(find.textContaining('risqués par trade'), findsOneWidget);
  });

  testWidgets('correspondance des symboles', (WidgetTester tester) async {
    await _pump(
      tester,
      const SymbolMappingScreen(),
      overrides: <Override>[
        symbolMappingsProvider.overrideWith((Ref<Object?> ref) async => <SymbolMapping>[
              const SymbolMapping(
                id: 1,
                alias: 'GOLD',
                canonical: 'XAUUSD',
                brokerSymbol: 'XAUUSDm',
                autoDetected: true,
                enabled: true,
                updatedAt: '2026-09-10T10:00:00',
              ),
            ]),
      ],
    );
    await tester.drag(find.byType(ListView), const Offset(0, -600));
    await tester.pumpAndSettle();
    expect(find.text('XAUUSDm'), findsOneWidget);
  });

  testWidgets('sections de connexion et a propos', (WidgetTester tester) async {
    final Map<String, dynamic> status = <String, dynamic>{
      'bridge': <String, dynamic>{
        'state': 'CONNECTED',
        'version': '1.0.0',
        'apiVersion': 'v1',
        'python': '3.13.0',
        'uptimeSeconds': 4200,
        'platform': 'Windows-10',
        'publicUrl': 'https://exemple.ngrok-free.app',
      },
      'tunnel': <String, dynamic>{'state': 'CONNECTED'},
      'telegram': <String, dynamic>{
        'state': 'CONNECTED',
        'authorized': true,
        'username': 'utilisateur',
        'phone': '+336****89',
      },
      'mt5': <String, dynamic>{
        'state': 'CONNECTED',
        'account': <String, dynamic>{'login': 123456, 'server': 'Exness-MT5Trial', 'kind': 'DEMO'},
        'terminal': <String, dynamic>{'tradeAllowed': true},
        'terminalPath': r'C:\Program Files\MetaTrader 5\terminal64.exe',
      },
    };
    await _pump(
      tester,
      Scaffold(
        body: SingleChildScrollView(
          child: Column(
            children: <Widget>[
              BridgeSection(status: status),
              TelegramSection(status: status),
              MetaTraderSection(status: status),
              AboutSection(status: status),
            ],
          ),
        ),
      ),
    );
    expect(find.text('Exness-MT5Trial'), findsOneWidget);
  });

  testWidgets('page Plus', (WidgetTester tester) async {
    await _pump(
      tester,
      const MoreScreen(),
      overrides: <Override>[
        tradingStateProvider.overrideWith((Ref<Object?> ref) async => <String, dynamic>{
              'executionMode': 'PAPER',
              'autoTradingEnabled': false,
              'paused': false,
              'consecutiveLosses': 0,
            }),
      ],
    );
    // On fait defiler jusqu'a l'entree plutot que d'une distance fixe :
    // ajouter un ecran a la page Plus ne doit pas casser ce test.
    await tester.scrollUntilVisible(
      find.text('Gestion du risque'),
      200,
      scrollable: find.byType(Scrollable).first,
    );
    await tester.pumpAndSettle();
    expect(find.text('Gestion du risque'), findsOneWidget);
  });

  testWidgets('section trading en mode reel deverrouille', (WidgetTester tester) async {
    await _pump(
      tester,
      const Scaffold(body: SingleChildScrollView(child: Column(children: <Widget>[TradingSection()]))),
      overrides: <Override>[
        tradingStateProvider.overrideWith((Ref<Object?> ref) async => <String, dynamic>{
              'executionMode': 'MT5_LIVE',
              'autoTradingEnabled': true,
              'liveUnlocked': true,
              'paused': true,
              'pauseReason': 'perte journalière maximale atteinte',
            }),
      ],
    );
    expect(find.text('Reverrouiller le mode réel'), findsOneWidget);
  });

  testWidgets('section openrouter sans modele gratuit', (WidgetTester tester) async {
    await _pump(
      tester,
      const Scaffold(body: SingleChildScrollView(child: Column(children: <Widget>[OpenRouterSection()]))),
      overrides: <Override>[
        openrouterStatusProvider.overrideWith((Ref<Object?> ref) async => <String, dynamic>{
              'state': 'DISCONNECTED',
              'configured': true,
              'apiKeyHint': 'sk-or…9f21',
              'autoMode': true,
              'textModel': null,
              'visionModel': null,
              'lastError': 'Aucun modele gratuit disponible actuellement.',
              'circuitOpen': false,
            }),
      ],
    );
    expect(find.textContaining('Aucun modèle gratuit disponible'), findsOneWidget);
  });

  testWidgets('historique en erreur affiche un reessai', (WidgetTester tester) async {
    await _pump(tester, const Scaffold(body: ClosedTradesView()));
    expect(find.text('Réessayer'), findsOneWidget);
  });

  testWidgets('apparence et notifications', (WidgetTester tester) async {
    SharedPreferences.setMockInitialValues(<String, Object>{});
    await _pump(
      tester,
      const Scaffold(
        body: SingleChildScrollView(
          child: Column(children: <Widget>[AppearanceSection(), NotificationsSection()]),
        ),
      ),
    );
    expect(find.text('Comme le téléphone'), findsOneWidget);
    expect(find.text('Bridge hors ligne'), findsOneWidget);
  });
}
