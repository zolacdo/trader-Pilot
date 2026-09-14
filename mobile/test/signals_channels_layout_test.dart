import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:intl/date_symbol_data_local.dart';
import 'package:tradepilot/core/theme/app_theme.dart';
import 'package:tradepilot/features/channels/models/channel.dart';
import 'package:tradepilot/features/channels/models/discovery.dart';
import 'package:tradepilot/features/channels/providers/channels_providers.dart';
import 'package:tradepilot/features/channels/widgets/channel_card.dart';
import 'package:tradepilot/features/channels/widgets/channel_detail_sections.dart';
import 'package:tradepilot/features/channels/widgets/channel_settings_form.dart';
import 'package:tradepilot/features/channels/widgets/discover_result_card.dart';
import 'package:tradepilot/features/signals/models/signal.dart';
import 'package:tradepilot/features/signals/providers/signals_providers.dart';
import 'package:tradepilot/features/signals/widgets/pending_review_banner.dart';
import 'package:tradepilot/features/signals/widgets/signal_detail_sections.dart';
import 'package:tradepilot/features/signals/widgets/signal_result_sections.dart';
import 'package:tradepilot/features/signals/widgets/signal_filters_bar.dart';

/// Ces tests rendent les écrans Signaux et Canaux sur un écran étroit
/// (360 points) : toute mise en page qui déborde fait échouer le test.

final Channel channel = Channel.fromJson(const <String, dynamic>{
  'id': 1,
  'telegramId': -100123,
  'title': 'Gold Signals Premium International',
  'username': 'goldsignalspremium',
  'description': 'Signaux XAUUSD.',
  'membersCount': 128450,
  'signalsCount': 312,
  'monitored': true,
  'joined': false,
  'lastMessageAt': '2026-09-10T10:00:00+00:00',
  'settings': <String, dynamic>{'enabled': true, 'mode': 'MANUAL'},
});

Future<void> _pump(WidgetTester tester, Widget child) async {
  tester.view.physicalSize = const Size(360, 690);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(
    ProviderScope(
      overrides: <Override>[
        channelsProvider.overrideWith((Ref ref) async => <Channel>[channel]),
        // Sans `expiresAt` : la pastille affiche « Sans délai » et le test ne
        // dépend pas de l'horloge à la seconde.
        pendingSignalsProvider.overrideWith((Ref ref) async => <Signal>[
              Signal.fromJson(const <String, dynamic>{
                'id': 5,
                'status': 'NEEDS_REVIEW',
                'normalizedSymbol': 'XAUUSD',
                'direction': 'SELL',
                'entryMin': 2345.5,
                'entryMax': 2348.0,
                'stopLoss': 2355.0,
                'takeProfits': <double>[2330.0, 2320.0, 2310.0],
                'computedLot': 0.05,
                'riskAmount': 25.0,
                'receivedAt': '2026-09-10T10:00:00+00:00',
              }),
            ]),
      ],
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
  await tester.pump();
}

void main() {
  setUpAll(() => initializeDateFormatting('fr_FR'));

  testWidgets('carte de canal', (WidgetTester tester) async {
    await _pump(tester, ChannelCard(channel: channel));
  });

  testWidgets('resultat de recherche', (WidgetTester tester) async {
    await _pump(
      tester,
      DiscoverResultCard(
        result: DiscoveredChannel.fromJson(const <String, dynamic>{
          'id': -100999,
          'title': 'Forex Scalping Room Officiel',
          'username': 'forexscalpingroom',
          'description': 'Scalping EURUSD et GBPUSD toute la journée.',
          'membersCount': 45210,
          'isPublic': true,
          'alreadyJoined': false,
          'lastMessageAt': '2026-09-10T09:00:00+00:00',
          'estimatedMessages': 12500,
        }),
      ),
    );
  });

  testWidgets('bandeau de validation', (WidgetTester tester) async {
    await _pump(tester, const PendingReviewBanner());
  });

  testWidgets('barre de filtres', (WidgetTester tester) async {
    await _pump(tester, const SignalFiltersBar(symbols: <String>['XAUUSD', 'EURUSD']));
  });

  testWidgets('formulaire de reglages', (WidgetTester tester) async {
    await _pump(
      tester,
      ChannelSettingsForm(
        channelId: 1,
        channelTitle: channel.title,
        settings: channel.settings ?? const ChannelSettings(),
      ),
    );
  });

  testWidgets('sections du canal', (WidgetTester tester) async {
    await _pump(
      tester,
      Column(
        children: <Widget>[
          ChannelInfoCard(channel: channel),
          ParserProfileCard(
            profile: ParserProfile.fromJson(const <String, dynamic>{
              'knownFormats': <String>['BUY {SYMBOL} @ {ENTRY} SL {SL} TP {TP}'],
              'lastSuccessfulFormat': 'BUY {SYMBOL}',
              'deterministicSuccess': 240,
              'aiFallbackCount': 12,
              'confidence': 0.91,
              'symbolAliases': <String, dynamic>{'GOLD': 'XAUUSD'},
            }),
          ),
          RecentSignalsCard(
            signals: <ChannelRecentSignal>[
              ChannelRecentSignal.fromJson(const <String, dynamic>{
                'id': 9,
                'symbol': 'XAUUSD',
                'direction': 'BUY',
                'status': 'PARTIALLY_CLOSED',
                'receivedAt': '2026-09-10T10:00:00+00:00',
              }),
            ],
          ),
        ],
      ),
    );
  });

  testWidgets('sections du signal', (WidgetTester tester) async {
    final SignalDetail detail = SignalDetail.fromJson(const <String, dynamic>{
      'id': 12,
      'status': 'CLOSED',
      'channel': <String, dynamic>{'id': 1, 'title': 'Gold Signals Premium International'},
      'receivedAt': '2026-09-10T10:00:00+00:00',
      'messageDate': '2026-09-10T09:59:00+00:00',
      'telegramMessageId': 88123,
      'rawText': 'XAUUSD BUY NOW 2345.5\nSL 2338\nTP1 2352 TP2 2360 TP3 2375',
      'symbol': 'GOLD',
      'normalizedSymbol': 'XAUUSD',
      'brokerSymbol': 'XAUUSDm',
      'direction': 'BUY',
      'orderType': 'MARKET',
      'entryPrice': 2345.5,
      'stopLoss': 2338.0,
      'takeProfits': <double>[2352.0, 2360.0, 2375.0],
      'confidence': 0.88,
      'parserSource': 'ai',
      'aiModel': 'meta-llama/llama-3.1-70b-instruct:free',
      'executionMode': 'MT5_DEMO',
      'computedLot': 0.05,
      'riskAmount': 37.5,
      'riskReward': 2.13,
      'pendingOrders': <Map<String, dynamic>>[
        <String, dynamic>{
          'id': 1,
          'ticket': 998877,
          'orderType': 'BUY_LIMIT',
          'price': 2340.0,
          'volume': 0.05,
          'state': 'PLACED',
        },
      ],
      'trades': <Map<String, dynamic>>[
        <String, dynamic>{
          'id': 3,
          'ticket': 123456789,
          'symbol': 'XAUUSDm',
          'direction': 'BUY',
          'state': 'CLOSED',
          'volume': 0.05,
          'openPrice': 2345.6,
          'closePrice': 2352.1,
          'profit': 32.5,
          'realizedPnl': 32.5,
          'rMultiple': 0.87,
          'openedAt': '2026-09-10T10:00:10+00:00',
          'closedAt': '2026-09-10T12:30:00+00:00',
          'closeReason': 'TP1 atteint',
        },
      ],
      'followUps': <Map<String, dynamic>>[
        <String, dynamic>{
          'id': 13,
          'status': 'PARSED',
          'followUpAction': 'MOVE_SL_TO_BE',
          'rawText': 'Move SL to entry',
          'receivedAt': '2026-09-10T11:00:00+00:00',
        },
      ],
      'audit': <Map<String, dynamic>>[
        <String, dynamic>{
          'createdAt': '2026-09-10T10:00:00+00:00',
          'action': 'signal_approved',
          'actor': 'device:android',
          'details': <String, dynamic>{'lot': 0.05},
        },
      ],
    });

    await _pump(
      tester,
      Column(
        children: <Widget>[
          RawMessageSection(signal: detail.signal),
          InterpretationSection(signal: detail.signal),
          ValidationSection(signal: detail.signal),
          RiskSection(signal: detail.signal),
          OrderSection(signal: detail.signal, pendingOrders: detail.pendingOrders),
          ResultSection(trades: detail.trades),
          FollowUpsSection(followUps: detail.followUps),
          AuditSection(audit: detail.audit),
        ],
      ),
    );
  });
}
