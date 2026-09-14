/// Chemins de l'API v1 du Bridge, regroupes pour eviter les chaines eparpillees.
abstract final class Endpoints {
  static const String base = '/api/v1';

  // --- systeme ---
  static const String health = '$base/health';
  static const String pairing = '$base/pairing';
  static const String pairingStatus = '$base/pairing/status';
  static const String devices = '$base/devices';
  static const String devicesRevoke = '$base/devices/revoke';
  static const String devicesRotate = '$base/devices/rotate';
  static const String pushToken = '$base/devices/push-token';
  static const String status = '$base/status';
  static const String dashboard = '$base/dashboard';
  static const String diagnostics = '$base/diagnostics';
  static const String diagnosticsExport = '$base/diagnostics/export';
  static const String goLiveChecklist = '$base/go-live-checklist';

  static String diagnosticTest(String target) => '$base/diagnostics/test/$target';

  // --- onboarding ---
  static const String onboardingState = '$base/onboarding/state';
  static const String onboardingComplete = '$base/onboarding/complete';

  // --- telegram ---
  static const String telegramStatus = '$base/telegram/status';
  static const String telegramLoginStart = '$base/telegram/login/start';
  static const String telegramLoginCode = '$base/telegram/login/code';
  static const String telegramLogin2fa = '$base/telegram/login/2fa';
  static const String telegramReconnect = '$base/telegram/reconnect';
  static const String telegramDisconnect = '$base/telegram/disconnect';
  static const String telegramLogout = '$base/telegram/logout';
  static const String telegramDiscover = '$base/telegram/discover';
  static const String telegramSuggestions = '$base/telegram/discover/suggestions';
  static const String telegramResolve = '$base/telegram/resolve';

  // --- canaux ---
  static const String channels = '$base/channels';
  static const String channelsCompare = '$base/channels/compare/table';

  static String channel(int id) => '$base/channels/$id';

  static String channelSettings(int id) => '$base/channels/$id/settings';

  static String channelMonitor(int id) => '$base/channels/$id/monitor';

  static String channelAnalyze(int id) => '$base/channels/$id/analyze';

  static String channelAnalyses(int id) => '$base/channels/$id/analyses';

  // --- signaux ---
  static const String signals = '$base/signals';
  static const String signalsPending = '$base/signals/pending';
  static const String signalsParseTest = '$base/signals/parse-test';
  static const String signalsSummary = '$base/signals/stats/summary';

  static String signal(int id) => '$base/signals/$id';

  static String signalApprove(int id) => '$base/signals/$id/approve';

  static String signalReject(int id) => '$base/signals/$id/reject';

  // --- MetaTrader et positions ---
  static const String mt5Status = '$base/mt5/status';
  static const String mt5Account = '$base/mt5/account';
  static const String mt5Reconnect = '$base/mt5/reconnect';
  static const String mt5Symbols = '$base/mt5/symbols';
  static const String positions = '$base/positions';
  static const String orders = '$base/orders';
  static const String history = '$base/history';

  static String mt5Symbol(String symbol) => '$base/mt5/symbols/$symbol';

  static String positionModify(int ticket) => '$base/positions/$ticket/modify';

  static String positionClose(int ticket) => '$base/positions/$ticket/close';

  static String positionBreakEven(int ticket) => '$base/positions/$ticket/break-even';

  static String orderCancel(int ticket) => '$base/orders/$ticket/cancel';

  // --- pilotage ---
  static const String tradingState = '$base/trading/state';
  static const String tradingAuto = '$base/trading/auto';
  static const String tradingPause = '$base/trading/pause';
  static const String tradingResume = '$base/trading/resume';
  static const String tradingExecutionMode = '$base/trading/execution-mode';
  static const String tradingLiveUnlock = '$base/trading/live-unlock';
  static const String tradingLiveLock = '$base/trading/live-lock';
  static const String tradingSync = '$base/trading/sync';

  // --- urgence ---
  static const String emergencyInfo = '$base/emergency/info';
  static const String emergencyCancelPending = '$base/emergency/cancel-pending';
  static const String emergencyCloseAll = '$base/emergency/close-all';

  // --- risque et configuration ---
  static const String riskSettings = '$base/risk/settings';
  static const String riskEvents = '$base/risk/events';
  static const String openrouterStatus = '$base/openrouter/status';
  static const String openrouterKey = '$base/openrouter/key';
  static const String openrouterModels = '$base/openrouter/models';
  static const String openrouterTest = '$base/openrouter/test';
  static const String aiChart = '$base/ai/chart';
  static const String symbolMappings = '$base/symbols/mappings';
  static const String settingsExport = '$base/settings/export';
  static const String settingsImport = '$base/settings/import';

  static String symbolMapping(int id) => '$base/symbols/mappings/$id';

  static String symbolSuggestions(String canonical) => '$base/symbols/suggestions/$canonical';

  // --- statistiques et journal ---
  static const String statistics = '$base/statistics';
  static const String statisticsToday = '$base/statistics/today';
  static const String journal = '$base/journal';
  static const String journalAudit = '$base/journal/audit';

  // --- temps reel ---
  // --- Intelligence hybride (CDC2) ---
  static const String aiStatus = '$base/ai/status';
  static const String aiProviders = '$base/ai/providers';
  static const String aiOpenRouterModels = '$base/ai/openrouter/models';
  static const String aiOpenRouterTest = '$base/ai/openrouter/test';
  static const String aiRouterSettings = '$base/ai/router/settings';
  static const String aiMetrics = '$base/ai/metrics';
  static String aiConsensus(int decisionId) => '$base/ai/consensus/$decisionId';

  // --- Marches ---
  static const String marketWatchlist = '$base/market/watchlist';
  static const String marketWatchlistRefresh = '$base/market/watchlist/refresh';
  static const String marketSymbols = '$base/market/symbols';
  static const String marketScan = '$base/market/scan';

  static String marketWatchlistItem(String symbol) => '$base/market/watchlist/$symbol';

  static String marketDetail(String symbol) => '$base/market/$symbol';

  static String marketCandles(String symbol) => '$base/market/$symbol/candles';

  static String marketRegimes(String symbol) => '$base/market/$symbol/regimes';

  // --- Analyse historique et correlations ---
  static String patterns(String symbol) => '$base/patterns/$symbol';
  static const String crossMarket = '$base/cross-market';
  static const String learningPerformance = '$base/learning/performance';

  // --- Actualites et calendrier ---
  static const String news = '$base/news';
  static String newsDetail(int id) => '$base/news/$id';
  static const String newsRefresh = '$base/news/refresh';
  static const String newsSources = '$base/news/sources';
  static const String economicCalendar = '$base/economic-calendar';
  static const String economicCalendarRefresh = '$base/economic-calendar/refresh';

  // --- Decisions et opportunites ---
  static const String decisions = '$base/decisions';
  static String decisionDetail(int id) => '$base/decisions/$id';
  static const String opportunities = '$base/opportunities';

  static String opportunityDetail(int id) => '$base/opportunities/$id';
  static const String shadowPerformance = '$base/shadow/performance';
  static const String circuitBreaker = '$base/circuit-breaker';

  // --- Notifications ---
  static const String notifications = '$base/notifications';
  static String notificationDetail(int id) => '$base/notifications/$id';

  static String notificationRead(int id) => '$base/notifications/$id/read';
  static const String notificationsReadAll = '$base/notifications/read-all';
  static const String notificationPreferences = '$base/notifications/preferences';
  static const String notificationTest = '$base/notifications/test';
  static const String notificationPushStatus = '$base/notifications/push/status';
  static const String notificationsUnreadCount = '$base/notifications/unread-count';

  // --- Intelligence autonome ---
  static const String intelligenceStatus = '$base/intelligence/status';
  static const String intelligenceIntervals = '$base/intelligence/intervals';

  static String intelligenceRun(String target) => '$base/intelligence/run/$target';

  static const String websocket = '$base/ws';
}
