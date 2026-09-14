import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:intl/date_symbol_data_local.dart';

import 'core/connection/connection_controller.dart';
import 'core/notifications/notification_service.dart';
import 'core/notifications/push_registration.dart';
import 'core/routing/app_router.dart';
import 'core/theme/app_theme.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await initializeDateFormatting('fr_FR');
  await SystemChrome.setPreferredOrientations(<DeviceOrientation>[
    DeviceOrientation.portraitUp,
    DeviceOrientation.portraitDown,
  ]);
  runApp(const ProviderScope(child: TradePilotApp()));
}

class TradePilotApp extends ConsumerStatefulWidget {
  const TradePilotApp({super.key});

  @override
  ConsumerState<TradePilotApp> createState() => _TradePilotAppState();
}

class _TradePilotAppState extends ConsumerState<TradePilotApp> {
  bool _restoring = true;
  NotificationService? _notifications;
  PushRegistration? _push;

  @override
  void initState() {
    super.initState();
    // La configuration enregistree (adresse du Bridge, jeton) est rechargee
    // avant d'afficher quoi que ce soit.
    WidgetsBinding.instance.addPostFrameCallback((_) async {
      final NotificationService service = ref.read(notificationServiceProvider);
      _notifications = service;
      service.opened.addListener(_onNotificationOpened);
      await service.initialize();
      await ref.read(connectionProvider.notifier).restore();
      // Branche les notifications sur le flux temps reel du Bridge.
      ref.read(notificationBridgeProvider);

      // Le push se branche APRÈS la restauration : l'enregistrement du jeton
      // appelle le Bridge, dont l'adresse et le jeton d'appairage viennent
      // d'être rechargés. L'inverse échouait silencieusement au premier
      // lancement.
      final PushRegistration push = PushRegistration(ref.read(apiClientProvider));
      _push = push;
      await push.initialiser();

      if (mounted) setState(() => _restoring = false);
      // Une notification peut avoir lance l'application : on traite ce qui
      // attendait deja, une fois le routeur disponible.
      _onNotificationOpened();
    });
  }

  @override
  void dispose() {
    _notifications?.opened.removeListener(_onNotificationOpened);
    _push?.dispose();
    super.dispose();
  }

  /// Ouvre l'ecran correspondant a la notification sur laquelle on a appuye.
  void _onNotificationOpened() {
    final int? id = _notifications?.opened.value;
    if (id == null || _restoring) return;
    final BuildContext? context = rootNavigatorKey.currentContext;
    if (context == null) return;
    _notifications?.clearOpened();
    // Un identifiant absent renvoie vers la liste : mieux vaut l'inbox qu'un
    // ecran vide.
    context.push(id > 0 ? Routes.notificationDetail(id) : Routes.notifications);
  }

  @override
  Widget build(BuildContext context) {
    if (_restoring) {
      return MaterialApp(
        debugShowCheckedModeBanner: false,
        theme: AppTheme.light(),
        darkTheme: AppTheme.dark(),
        home: const _SplashScreen(),
      );
    }

    final GoRouter router = ref.watch(appRouterProvider);
    return MaterialApp.router(
      title: 'TradePilot',
      debugShowCheckedModeBanner: false,
      theme: AppTheme.light(),
      darkTheme: AppTheme.dark(),
      themeMode: ThemeMode.system,
      routerConfig: router,
    );
  }
}

class _SplashScreen extends StatelessWidget {
  const _SplashScreen();

  @override
  Widget build(BuildContext context) {
    return const Scaffold(
      body: Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: <Widget>[
            // Le logo porte deja le nom de l'application : pas de texte en plus.
            Image(
              image: AssetImage('assets/icon/tradepilot_logo.png'),
              width: 220,
              filterQuality: FilterQuality.medium,
            ),
            SizedBox(height: 8),
            SizedBox(
              width: 26,
              height: 26,
              child: CircularProgressIndicator(strokeWidth: 2.4),
            ),
          ],
        ),
      ),
    );
  }
}
