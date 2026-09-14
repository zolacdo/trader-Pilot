import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../core/api/ws_client.dart';
import '../core/connection/connection_controller.dart';
import '../core/providers/bridge_data.dart';
import '../core/routing/app_router.dart';
import '../core/widgets/app_widgets.dart';

/// Coque de l'application : navigation basse et bandeau hors ligne.
class AppShell extends ConsumerWidget {
  const AppShell({super.key, required this.child, required this.location});

  final Widget child;
  final String location;

  static const List<({String route, IconData icon, IconData activeIcon, String label})> _tabs =
      <({String route, IconData icon, IconData activeIcon, String label})>[
    (route: Routes.dashboard, icon: Icons.home_outlined, activeIcon: Icons.home, label: 'Accueil'),
    (
      route: Routes.signals,
      icon: Icons.podcasts_outlined,
      activeIcon: Icons.podcasts,
      label: 'Signaux'
    ),
    (route: Routes.channels, icon: Icons.forum_outlined, activeIcon: Icons.forum, label: 'Canaux'),
    (
      route: Routes.trades,
      icon: Icons.candlestick_chart_outlined,
      activeIcon: Icons.candlestick_chart,
      label: 'Trades'
    ),
    (route: Routes.more, icon: Icons.more_horiz, activeIcon: Icons.more_horiz, label: 'Plus'),
  ];

  int _indexFor(String location) {
    if (location == Routes.dashboard) return 0;
    for (int i = _tabs.length - 1; i >= 1; i--) {
      if (location.startsWith(_tabs[i].route)) return i;
    }
    return 0;
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    // Maintient l'abonnement temps reel actif tant que la coque est montee.
    ref.watch(liveRefreshProvider);

    final BridgeConnectionState connection = ref.watch(connectionProvider);
    final WsClient ws = ref.watch(wsClientProvider);
    final int index = _indexFor(location);

    return Scaffold(
      body: Column(
        children: <Widget>[
          if (connection.offline)
            OfflineBanner(onRetry: () => ref.read(connectionProvider.notifier).retry()),
          Expanded(child: child),
        ],
      ),
      bottomNavigationBar: ValueListenableBuilder<WsStatus>(
        valueListenable: ws.status,
        builder: (BuildContext context, WsStatus status, Widget? _) {
          return NavigationBar(
            selectedIndex: index,
            onDestinationSelected: (int selected) => context.go(_tabs[selected].route),
            destinations: <Widget>[
              for (final ({String route, IconData icon, IconData activeIcon, String label}) tab in _tabs)
                NavigationDestination(
                  icon: Icon(tab.icon),
                  selectedIcon: Icon(tab.activeIcon),
                  label: tab.label,
                ),
            ],
          );
        },
      ),
    );
  }
}
