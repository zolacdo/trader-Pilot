import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../app/app_shell.dart';
import '../../features/ai/ai_analysis_screen.dart';
import '../../features/ai_config/ai_config_screen.dart';
import '../../features/ai_config/ai_diagnostic_screen.dart';
import '../../features/bridge/connections_screen.dart';
import '../../features/bridge/pairing_screen.dart';
import '../../features/channels/channel_compare_screen.dart';
import '../../features/channels/channel_detail_screen.dart';
import '../../features/channels/channels_screen.dart';
import '../../features/channels/discover_screen.dart';
import '../../features/dashboard/dashboard_screen.dart';
import '../../features/decisions/decision_detail_screen.dart';
import '../../features/decisions/decisions_screen.dart';
import '../../features/diagnostics/diagnostics_screen.dart';
import '../../features/diagnostics/go_live_screen.dart';
import '../../features/journal/journal_screen.dart';
import '../../features/markets/market_detail_screen.dart';
import '../../features/markets/markets_screen.dart';
import '../../features/more/more_screen.dart';
import '../../features/news/news_detail_screen.dart';
import '../../features/news/news_screen.dart';
import '../../features/notifications/notification_detail_screen.dart';
import '../../features/notifications/notifications_screen.dart';
import '../../features/onboarding/onboarding_screen.dart';
import '../../features/opportunities/opportunities_screen.dart';
import '../../features/orders/emergency_screen.dart';
import '../../features/positions/trades_screen.dart';
import '../../features/risk/risk_screen.dart';
import '../../features/settings/settings_screen.dart';
import '../../features/settings/symbol_mapping_screen.dart';
import '../../features/signals/signal_detail_screen.dart';
import '../../features/signals/signals_screen.dart';
import '../../features/statistics/statistics_screen.dart';
import '../../features/watcher/watcher_screen.dart';
import '../connection/connection_controller.dart';

/// Chemins de navigation, centralises pour eviter les chaines magiques.
abstract final class Routes {
  static const String splash = '/splash';
  static const String pairing = '/pairing';
  static const String onboarding = '/onboarding';

  static const String dashboard = '/';
  static const String signals = '/signals';
  static const String channels = '/channels';
  static const String trades = '/trades';
  static const String more = '/more';

  static const String discover = '/channels/discover';
  static const String compare = '/channels/compare';
  static const String emergency = '/emergency';

  static const String statistics = '/more/statistics';
  static const String watcherBand = '/more/watcher-band';
  static const String ai = '/more/ai';
  static const String journal = '/more/journal';
  static const String risk = '/more/risk';
  static const String connections = '/more/connections';
  static const String settings = '/more/settings';
  static const String diagnostics = '/more/diagnostics';
  static const String symbols = '/more/symbols';
  static const String goLive = '/more/go-live';

  // --- intelligence de marche autonome (CDC2) ---
  static const String notifications = '/more/notifications';
  static const String news = '/more/news';
  static const String economicCalendar = '/more/calendar';
  static const String opportunities = '/more/opportunities';
  static const String decisions = '/more/decisions';
  static const String markets = '/more/markets';
  static const String aiConfig = '/more/ai-config';
  static const String aiDiagnostic = '/more/ai-diagnostic';

  static String signalDetail(int id) => '/signals/$id';

  static String channelDetail(int id) => '/channels/$id';

  static String newsDetail(int id) => '/more/news/$id';

  static String decisionDetail(int id) => '/more/decisions/$id';

  static String notificationDetail(int id) => '/more/notifications/$id';

  /// Le symbole voyage dans l'URL : il doit etre encode (ex. « BRENT/USD »).
  static String marketDetail(String symbol) =>
      '/more/markets/${Uri.encodeComponent(symbol)}';
}

/// Navigateur racine, expose pour que l'appui sur une notification Android
/// puisse ouvrir un ecran sans passer par un `BuildContext`.
final GlobalKey<NavigatorState> rootNavigatorKey = GlobalKey<NavigatorState>();
final GlobalKey<NavigatorState> _rootNavigatorKey = rootNavigatorKey;
final GlobalKey<NavigatorState> _shellNavigatorKey = GlobalKey<NavigatorState>();

/// Routeur de l'application.
///
/// Tant que le telephone n'est pas appaire avec un Bridge, toute la navigation
/// est redirigee vers l'ecran d'appairage : aucune donnee de trading n'est
/// accessible sans liaison authentifiee.
final Provider<GoRouter> appRouterProvider = Provider<GoRouter>((ref) {
  return GoRouter(
    navigatorKey: _rootNavigatorKey,
    initialLocation: Routes.dashboard,
    debugLogDiagnostics: false,
    redirect: (BuildContext context, GoRouterState state) {
      final BridgeConnectionState connection = ref.read(connectionProvider);
      if (connection.loading) return null;

      final bool onPairing = state.matchedLocation == Routes.pairing;
      final bool onOnboarding = state.matchedLocation == Routes.onboarding;

      if (!connection.paired) {
        return onPairing ? null : Routes.pairing;
      }
      if (onPairing) {
        return Routes.dashboard;
      }
      if (onOnboarding) {
        return null;
      }
      return null;
    },
    routes: <RouteBase>[
      GoRoute(
        path: Routes.pairing,
        parentNavigatorKey: _rootNavigatorKey,
        builder: (BuildContext context, GoRouterState state) => const PairingScreen(),
      ),
      GoRoute(
        path: Routes.onboarding,
        parentNavigatorKey: _rootNavigatorKey,
        builder: (BuildContext context, GoRouterState state) => const OnboardingScreen(),
      ),
      GoRoute(
        path: Routes.emergency,
        parentNavigatorKey: _rootNavigatorKey,
        builder: (BuildContext context, GoRouterState state) => const EmergencyScreen(),
      ),
      ShellRoute(
        navigatorKey: _shellNavigatorKey,
        builder: (BuildContext context, GoRouterState state, Widget child) =>
            AppShell(location: state.matchedLocation, child: child),
        routes: <RouteBase>[
          GoRoute(
            path: Routes.dashboard,
            builder: (BuildContext context, GoRouterState state) => const DashboardScreen(),
          ),
          GoRoute(
            path: Routes.signals,
            builder: (BuildContext context, GoRouterState state) => const SignalsScreen(),
            routes: <RouteBase>[
              GoRoute(
                path: ':id',
                parentNavigatorKey: _rootNavigatorKey,
                builder: (BuildContext context, GoRouterState state) => SignalDetailScreen(
                  signalId: int.tryParse(state.pathParameters['id'] ?? '') ?? 0,
                ),
              ),
            ],
          ),
          GoRoute(
            path: Routes.channels,
            builder: (BuildContext context, GoRouterState state) => const ChannelsScreen(),
            routes: <RouteBase>[
              GoRoute(
                path: 'discover',
                parentNavigatorKey: _rootNavigatorKey,
                builder: (BuildContext context, GoRouterState state) => const DiscoverScreen(),
              ),
              GoRoute(
                path: 'compare',
                parentNavigatorKey: _rootNavigatorKey,
                builder: (BuildContext context, GoRouterState state) => const ChannelCompareScreen(),
              ),
              GoRoute(
                path: ':id',
                parentNavigatorKey: _rootNavigatorKey,
                builder: (BuildContext context, GoRouterState state) => ChannelDetailScreen(
                  channelId: int.tryParse(state.pathParameters['id'] ?? '') ?? 0,
                ),
              ),
            ],
          ),
          GoRoute(
            path: Routes.trades,
            builder: (BuildContext context, GoRouterState state) => const TradesScreen(),
          ),
          GoRoute(
            path: Routes.more,
            builder: (BuildContext context, GoRouterState state) => const MoreScreen(),
            routes: <RouteBase>[
              GoRoute(
                path: 'statistics',
                parentNavigatorKey: _rootNavigatorKey,
                builder: (BuildContext context, GoRouterState state) => const StatisticsScreen(),
              ),
              GoRoute(
                path: 'watcher-band',
                parentNavigatorKey: _rootNavigatorKey,
                builder: (BuildContext context, GoRouterState state) =>
                    const WatcherBandScreen(),
              ),
              GoRoute(
                path: 'ai',
                parentNavigatorKey: _rootNavigatorKey,
                builder: (BuildContext context, GoRouterState state) => const AiAnalysisScreen(),
              ),
              GoRoute(
                path: 'journal',
                parentNavigatorKey: _rootNavigatorKey,
                builder: (BuildContext context, GoRouterState state) => const JournalScreen(),
              ),
              GoRoute(
                path: 'risk',
                parentNavigatorKey: _rootNavigatorKey,
                builder: (BuildContext context, GoRouterState state) => const RiskScreen(),
              ),
              GoRoute(
                path: 'connections',
                parentNavigatorKey: _rootNavigatorKey,
                builder: (BuildContext context, GoRouterState state) => const ConnectionsScreen(),
              ),
              GoRoute(
                path: 'settings',
                parentNavigatorKey: _rootNavigatorKey,
                builder: (BuildContext context, GoRouterState state) => const SettingsScreen(),
              ),
              GoRoute(
                path: 'diagnostics',
                parentNavigatorKey: _rootNavigatorKey,
                builder: (BuildContext context, GoRouterState state) => const DiagnosticsScreen(),
              ),
              GoRoute(
                path: 'symbols',
                parentNavigatorKey: _rootNavigatorKey,
                builder: (BuildContext context, GoRouterState state) => const SymbolMappingScreen(),
              ),
              GoRoute(
                path: 'go-live',
                parentNavigatorKey: _rootNavigatorKey,
                builder: (BuildContext context, GoRouterState state) => const GoLiveScreen(),
              ),
              GoRoute(
                path: 'notifications',
                parentNavigatorKey: _rootNavigatorKey,
                builder: (BuildContext context, GoRouterState state) =>
                    const NotificationsScreen(),
                routes: <RouteBase>[
                  GoRoute(
                    path: ':id',
                    parentNavigatorKey: _rootNavigatorKey,
                    builder: (BuildContext context, GoRouterState state) =>
                        NotificationDetailScreen(
                      notificationId: int.tryParse(state.pathParameters['id'] ?? '') ?? 0,
                    ),
                  ),
                ],
              ),
              GoRoute(
                path: 'news',
                parentNavigatorKey: _rootNavigatorKey,
                builder: (BuildContext context, GoRouterState state) => const NewsScreen(),
                routes: <RouteBase>[
                  GoRoute(
                    path: ':id',
                    parentNavigatorKey: _rootNavigatorKey,
                    builder: (BuildContext context, GoRouterState state) => NewsDetailScreen(
                      newsId: int.tryParse(state.pathParameters['id'] ?? '') ?? 0,
                    ),
                  ),
                ],
              ),
              GoRoute(
                path: 'calendar',
                parentNavigatorKey: _rootNavigatorKey,
                builder: (BuildContext context, GoRouterState state) =>
                    const NewsScreen(initialTab: 1),
              ),
              GoRoute(
                path: 'opportunities',
                parentNavigatorKey: _rootNavigatorKey,
                builder: (BuildContext context, GoRouterState state) =>
                    const OpportunitiesScreen(),
              ),
              GoRoute(
                path: 'decisions',
                parentNavigatorKey: _rootNavigatorKey,
                builder: (BuildContext context, GoRouterState state) => const DecisionsScreen(),
                routes: <RouteBase>[
                  GoRoute(
                    path: ':id',
                    parentNavigatorKey: _rootNavigatorKey,
                    builder: (BuildContext context, GoRouterState state) => DecisionDetailScreen(
                      decisionId: int.tryParse(state.pathParameters['id'] ?? '') ?? 0,
                    ),
                  ),
                ],
              ),
              GoRoute(
                path: 'markets',
                parentNavigatorKey: _rootNavigatorKey,
                builder: (BuildContext context, GoRouterState state) => const MarketsScreen(),
                routes: <RouteBase>[
                  GoRoute(
                    path: ':symbol',
                    parentNavigatorKey: _rootNavigatorKey,
                    builder: (BuildContext context, GoRouterState state) => MarketDetailScreen(
                      symbol: state.pathParameters['symbol'] ?? '',
                    ),
                  ),
                ],
              ),
              GoRoute(
                path: 'ai-config',
                parentNavigatorKey: _rootNavigatorKey,
                builder: (BuildContext context, GoRouterState state) => const AiConfigScreen(),
              ),
              GoRoute(
                path: 'ai-diagnostic',
                parentNavigatorKey: _rootNavigatorKey,
                builder: (BuildContext context, GoRouterState state) =>
                    const AiDiagnosticScreen(),
              ),
            ],
          ),
        ],
      ),
    ],
    errorBuilder: (BuildContext context, GoRouterState state) => Scaffold(
      appBar: AppBar(title: const Text('Page introuvable')),
      body: Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: <Widget>[
              const Icon(Icons.help_outline, size: 40),
              const SizedBox(height: 16),
              Text('Aucun écran pour ${state.uri}'),
              const SizedBox(height: 16),
              FilledButton(
                onPressed: () => context.go(Routes.dashboard),
                child: const Text('Retour à l’accueil'),
              ),
            ],
          ),
        ),
      ),
    ),
  );
});
