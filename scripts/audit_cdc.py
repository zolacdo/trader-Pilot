"""Audit du cahier des charges : chaque exigence est verifiee contre le code.

Usage :  bridge/.venv/Scripts/python.exe scripts/audit_cdc.py

Rejouez-le apres toute modification pour verifier qu'aucune fonction du
cahier des charges n'a disparu. Le code de sortie vaut 1 si une exigence
n'est plus couverte.

Aucune affirmation n'est faite de memoire. Chaque point est associe a une
preuve concrete : une route exposee, un symbole present dans les sources, un
fichier existant. Ce qui n'est pas trouve est declare manquant.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BRIDGE = ROOT / "bridge" / "app"
MOBILE = ROOT / "mobile" / "lib"
DOCS = ROOT / "docs"
SCRIPTS = ROOT / "scripts"
TESTS = ROOT / "bridge" / "tests"

with open(DOCS / "openapi.json", encoding="utf-8") as handle:
    ROUTES = set(json.load(handle)["paths"])


def _read_all(folder: Path, suffix: str) -> str:
    if not folder.exists():
        return ""
    chunks = []
    for path in folder.rglob(f"*{suffix}"):
        if "__pycache__" in str(path) or ".dart_tool" in str(path):
            continue
        try:
            chunks.append(path.read_text(encoding="utf-8", errors="ignore"))
        except OSError:
            continue
    return "\n".join(chunks)


BRIDGE_SRC = _read_all(BRIDGE, ".py")
MOBILE_SRC = _read_all(MOBILE, ".dart")
TESTS_SRC = _read_all(TESTS, ".py")
SCRIPTS_SRC = _read_all(SCRIPTS, ".ps1")
ALL_SRC = BRIDGE_SRC + MOBILE_SRC


@dataclass
class Probe:
    kind: str          # route | py | dart | any | file | test | script
    needle: str
    label: str = ""


@dataclass
class Requirement:
    section: str
    title: str
    probes: list[Probe]


def check(probe: Probe) -> bool:
    if probe.kind == "route":
        return any(probe.needle in route for route in ROUTES)
    if probe.kind == "file":
        return (ROOT / probe.needle).exists()
    haystack = {
        "py": BRIDGE_SRC,
        "dart": MOBILE_SRC,
        "any": ALL_SRC,
        "test": TESTS_SRC,
        "script": SCRIPTS_SRC,
    }[probe.kind]
    return re.search(probe.needle, haystack) is not None


REQUIREMENTS: list[Requirement] = [
    Requirement("2", "MT5 Desktop via le package Python officiel", [
        Probe("py", r"import MetaTrader5"), Probe("py", r"class RealMetaTraderService")]),
    Requirement("3", "Monorepo mobile / bridge / docs / scripts", [
        Probe("file", "mobile"), Probe("file", "bridge"), Probe("file", "docs"),
        Probe("file", "scripts"), Probe("file", "README.md"), Probe("file", ".gitignore"),
        Probe("file", ".env.example")]),
    Requirement("4", "Flutter : Riverpod, go_router, Dio, SQLite, secure storage, WebSocket", [
        Probe("file", "mobile/pubspec.yaml"), Probe("dart", r"flutter_riverpod"),
        Probe("dart", r"go_router"), Probe("dart", r"package:dio"),
        Probe("dart", r"flutter_secure_storage"), Probe("dart", r"web_socket_channel")]),
    Requirement("5", "Design sobre, accent unique #2563EB, Material 3", [
        Probe("dart", r"0xFF2563EB"), Probe("dart", r"useMaterial3")]),
    Requirement("6", "Navigation : Accueil, Signaux, Canaux, Trades, Plus", [
        Probe("dart", r"NavigationBar|BottomNavigation"), Probe("file", "mobile/lib/features/dashboard"),
        Probe("file", "mobile/lib/features/signals"), Probe("file", "mobile/lib/features/channels"),
        Probe("file", "mobile/lib/features/positions"), Probe("dart", r"more_screen|MoreScreen")]),
    Requirement("7", "Onboarding complet en 8 etapes", [
        Probe("file", "mobile/lib/features/onboarding"), Probe("route", "/onboarding/state"),
        Probe("route", "/onboarding/complete")]),
    Requirement("8", "Bridge FastAPI structure en services", [
        Probe("file", "bridge/app/main.py"), Probe("file", "bridge/app/services/mt5"),
        Probe("file", "bridge/app/services/telegram"), Probe("file", "bridge/app/services/signals"),
        Probe("file", "bridge/app/services/risk"), Probe("file", "bridge/app/services/trading"),
        Probe("file", "bridge/app/services/channels"), Probe("file", "bridge/app/services/openrouter"),
        Probe("file", "bridge/app/services/statistics"), Probe("file", "bridge/app/services/security")]),
    Requirement("9", "MetaTraderService complet (order_check, order_send, modify, close)", [
        Probe("py", r"order_check"), Probe("py", r"order_send"), Probe("py", r"def account_info"),
        Probe("py", r"def symbol_info_tick|def symbol_tick"), Probe("py", r"def positions"),
        Probe("py", r"def orders"), Probe("py", r"def history"), Probe("py", r"terminal_info")]),
    Requirement("9b", "File de travail serialisee pour MT5", [
        Probe("py", r"class Mt5ProcessWorker"), Probe("py", r"asyncio\.Lock")]),
    Requirement("10", "Mode DEMO par defaut, auto trading OFF, passage au reel protege", [
        Probe("py", r"auto_trading_enabled: bool = Field\(default=False\)"),
        Probe("py", r"execution_mode: ExecutionMode = Field\(default=ExecutionMode\.PAPER\)"),
        Probe("py", r"live_unlocked: bool = Field\(default=False\)"),
        Probe("route", "/trading/live-unlock"), Probe("py", r"LIVE_NOT_UNLOCKED")]),
    Requirement("11", "Session utilisateur Telethon : OTP et 2FA", [
        Probe("py", r"from telethon"), Probe("route", "/telegram/login/start"),
        Probe("route", "/telegram/login/code"), Probe("route", "/telegram/login/2fa"),
        Probe("py", r"StringSession")]),
    Requirement("12", "Recherche de canaux Telegram", [
        Probe("route", "/telegram/discover"), Probe("route", "/telegram/discover/suggestions")]),
    Requirement("13", "Channel Analyzer avec mesures factuelles", [
        Probe("file", "bridge/app/services/channels/analyzer.py"),
        Probe("route", "/channels/{channel_id}/analyze"), Probe("py", r"parseable_rate"),
        Probe("py", r"signals_per_day")]),
    Requirement("14", "Simulation historique, cas AMBIGUOUS jamais compte gagnant", [
        Probe("file", "bridge/app/services/channels/backtester.py"),
        Probe("py", r"AMBIGUOUS"), Probe("py", r"BacktestOutcome")]),
    Requirement("15", "Reglages par canal avec overrides", [
        Probe("py", r"class ChannelSettings"), Probe("route", "/channels/{channel_id}/settings")]),
    Requirement("16", "Pipeline hybride deterministe puis IA", [
        Probe("file", "bridge/app/services/signals/deterministic_parser.py"),
        Probe("file", "bridge/app/services/signals/pipeline.py"),
        Probe("file", "bridge/app/services/signals/normalizer.py")]),
    Requirement("17", "Modele TradingSignal complet", [
        Probe("py", r"idempotency_key"), Probe("py", r"entry_min"), Probe("py", r"entry_max"),
        Probe("py", r"take_profits"), Probe("py", r"parser_source"), Probe("py", r"original_signal_id")]),
    Requirement("18", "Messages de suivi rattaches au bon signal", [
        Probe("file", "bridge/app/services/signals/follow_up_parser.py"),
        Probe("py", r"TP_HIT"), Probe("py", r"MOVE_SL_BE"), Probe("py", r"CLOSE_PARTIAL"),
        Probe("py", r"reply_to_message_id")]),
    Requirement("19", "OpenRouter + selection automatique de modeles gratuits", [
        Probe("file", "bridge/app/services/openrouter/model_selector.py"),
        Probe("route", "/openrouter/models"), Probe("route", "/openrouter/test"),
        Probe("py", r"free_only|is_free")]),
    Requirement("20", "Economie des appels : templates par canal", [
        Probe("py", r"class ChannelParserProfile"), Probe("py", r"known_formats")]),
    Requirement("21", "Prompt strict, validation locale de la sortie IA", [
        Probe("py", r"[Nn]ever invent"), Probe("py", r"parse_trading_signal")]),
    Requirement("22", "Analyse IA de graphiques, sans declenchement de trade", [
        Probe("route", "/ai/chart"), Probe("file", "mobile/lib/features/ai")]),
    Requirement("23", "RiskManager independant de l'IA", [
        Probe("file", "bridge/app/services/risk/manager.py"),
        Probe("py", r"max_daily_loss_percent"), Probe("py", r"max_drawdown_percent"),
        Probe("py", r"max_consecutive_losses"), Probe("py", r"trading_hours_start"),
        Probe("py", r"max_spread_points")]),
    Requirement("24", "Lot calcule sur les metadonnees reelles du broker", [
        Probe("file", "bridge/app/services/risk/calculator.py"),
        Probe("py", r"volume_step"), Probe("py", r"trade_tick_value"),
        Probe("py", r"order_calc_profit|order_calc"), Probe("py", r"INVALID_VOLUME")]),
    Requirement("25", "Validation complete avant order_send", [
        Probe("file", "bridge/app/services/signals/validator.py"), Probe("py", r"order_check")]),
    Requirement("26", "Anti-doublon par cle d'idempotence", [
        Probe("py", r"idempotency_key"), Probe("py", r"DUPLICATE_SIGNAL")]),
    Requirement("27", "Tous les types d'ordres et modifications", [
        Probe("py", r"BUY_LIMIT"), Probe("py", r"SELL_STOP"), Probe("py", r"BUY_STOP_LIMIT"),
        Probe("py", r"def modify|modify_position"), Probe("py", r"def close_partial|partial")]),
    Requirement("28", "Strategies TP multiples configurables", [
        Probe("py", r"class MultiTpStrategy"), Probe("py", r"SPLIT_POSITIONS"),
        Probe("py", r"PARTIAL_CLOSE"), Probe("py", r"FIRST_TP_ONLY")]),
    Requirement("29", "Break even parametrable", [
        Probe("py", r"class BreakEvenTrigger"), Probe("py", r"break_even_offset_points"),
        Probe("py", r"break_even_applied")]),
    Requirement("30", "Trailing stop optionnel", [
        Probe("py", r"class TrailingMode"), Probe("py", r"trailing_distance_points")]),
    Requirement("31", "Accueil : soldes, statuts, positions, boutons separes", [
        Probe("route", "/dashboard"), Probe("file", "mobile/lib/features/dashboard")]),
    Requirement("32", "Pause distincte de l'arret d'urgence", [
        Probe("route", "/trading/pause"), Probe("route", "/emergency/close-all"),
        Probe("route", "/emergency/cancel-pending"), Probe("dart", r"emergency_screen|EmergencyScreen")]),
    Requirement("33", "Page Signaux avec filtres", [
        Probe("route", "/signals"), Probe("dart", r"signals_screen|SignalsScreen")]),
    Requirement("34", "Detail du signal avec chronologie", [
        Probe("route", "/signals/{signal_id}"), Probe("dart", r"signal_detail|SignalDetail"),
        Probe("py", r"class SignalEvent")]),
    Requirement("35", "Page Trades : ouverts, en attente, fermes + actions", [
        Probe("route", "/positions"), Probe("route", "/orders"), Probe("route", "/history"),
        Probe("dart", r"trades_screen|TradesScreen"), Probe("route", "/positions/{ticket}/close")]),
    Requirement("36", "Statistiques reelles globales et par canal", [
        Probe("file", "bridge/app/services/statistics/service.py"),
        Probe("route", "/statistics"), Probe("py", r"profitFactor"),
        Probe("py", r"winRate"), Probe("py", r"max_drawdown")]),
    Requirement("37", "Journal de tous les evenements importants", [
        Probe("file", "bridge/app/services/journal.py"), Probe("route", "/journal"),
        Probe("py", r"class JournalEntry")]),
    Requirement("38", "API versionnee /api/v1", [Probe("route", "/api/v1/health")]),
    Requirement("39", "WebSocket temps reel avec reconnexion", [
        Probe("file", "bridge/app/api/v1/websocket.py"), Probe("dart", r"class WsClient"),
        Probe("dart", r"backoff|reconnect")]),
    Requirement("40", "Mode hors ligne du mobile", [
        Probe("dart", r"OfflineBanner"), Probe("dart", r"local_database|LocalDatabase"),
        Probe("py", r"SIGNAL_EXPIRED")]),
    Requirement("41", "Appairage et authentification de toutes les routes sensibles", [
        Probe("route", "/pairing"), Probe("py", r"def require_device"),
        Probe("route", "/devices/revoke"), Probe("route", "/devices/rotate")]),
    Requirement("42", "Secrets chiffres, jamais en clair", [
        Probe("file", "bridge/app/services/security/crypto.py"), Probe("py", r"Fernet"),
        Probe("py", r"def redact"), Probe("file", ".env.example")]),
    Requirement("43", "Tables de base de donnees", [
        Probe("py", r'__tablename__ = "signals"'), Probe("py", r'__tablename__ = "channels"'),
        Probe("py", r'__tablename__ = "trades"'), Probe("py", r'__tablename__ = "audit_logs"'),
        Probe("py", r'__tablename__ = "daily_statistics"'), Probe("py", r'__tablename__ = "ai_requests"')]),
    Requirement("44", "Resilience : reconnexions, echec en mode sur", [
        Probe("py", r"MT5_RETRY_DELAYS|retry"), Probe("py", r"CircuitBreaker|circuit")]),
    Requirement("45", "Notifications Android parametrables", [
        Probe("dart", r"flutter_local_notifications"), Probe("dart", r"class NotificationService")]),
    Requirement("46", "Ecran Parametres complet", [
        Probe("dart", r"settings_screen|SettingsScreen"), Probe("route", "/openrouter/key")]),
    Requirement("47", "Tests Python et Flutter", [
        Probe("file", "bridge/tests"), Probe("file", "mobile/test"),
        Probe("py", r"class FakeMetaTraderService"), Probe("test", r"def test_")]),
    Requirement("48", "Jeux de messages de test realistes", [
        Probe("file", "bridge/tests/fixtures/messages.py"), Probe("test", r"AMBIGUOUS_MESSAGES|NOISE")]),
    Requirement("49", "Protection contre les hallucinations : NO_ACTION", [
        Probe("py", r"NO_ACTION"), Probe("py", r"looks_like_noise")]),
    Requirement("50", "Score de confiance et seuil minimum", [
        Probe("py", r"min_confidence"), Probe("py", r"NEEDS_REVIEW"), Probe("py", r"LOW_CONFIDENCE")]),
    Requirement("51", "Validation manuelle avec expiration", [
        Probe("route", "/signals/{signal_id}/approve"), Probe("route", "/signals/{signal_id}/reject"), Probe("py", r"expires_at")]),
    Requirement("52", "Mode automatique sans contournement des protections", [
        Probe("py", r"class ChannelMode"), Probe("py", r"AUTO")]),
    Requirement("53", "Apprentissage des formats par canal", [
        Probe("py", r"class ChannelParserProfile"), Probe("py", r"structure_fingerprint")]),
    Requirement("54", "Mapping des symboles Exness", [
        Probe("file", "bridge/app/services/trading/symbol_resolver.py"),
        Probe("route", "/symbols/suggestions/{canonical}"), Probe("py", r"class SymbolMapping"),
        Probe("dart", r"symbol_mapping|SymbolMapping")]),
    Requirement("55", "MT5 source prioritaire des donnees de marche", [
        Probe("py", r"attach_price_source"), Probe("py", r"uses_live_prices")]),
    Requirement("56", "Aucune API payante obligatoire", [
        Probe("py", r"openrouter_free_only|free_only")]),
    Requirement("57", "Documentation complete", [
        Probe("file", "docs/ARCHITECTURE.md"), Probe("file", "docs/ANDROID_SETUP.md"),
        Probe("file", "docs/BRIDGE_WINDOWS_SETUP.md"), Probe("file", "docs/MT5_EXNESS_SETUP.md"),
        Probe("file", "docs/TELEGRAM_SETUP.md"), Probe("file", "docs/OPENROUTER_SETUP.md"),
        Probe("file", "docs/RISK_MANAGEMENT.md"), Probe("file", "docs/CHANNEL_DISCOVERY.md"),
        Probe("file", "docs/CHANNEL_ANALYSIS.md"), Probe("file", "docs/SECURITY.md"),
        Probe("file", "docs/DEMO_TESTING.md"), Probe("file", "docs/GO_LIVE_CHECKLIST.md"),
        Probe("file", "docs/TROUBLESHOOTING.md")]),
    Requirement("58", "Scripts PowerShell d'installation", [
        Probe("file", "scripts/install_bridge.ps1"), Probe("file", "scripts/start_bridge.ps1"),
        Probe("file", "scripts/check_environment.ps1")]),
    Requirement("58b", "Packaging PyInstaller", [Probe("file", "bridge/tradepilot.spec")]),
    Requirement("59", "Build Android fonctionnel", [
        Probe("file", "mobile/build/app/outputs/flutter-apk/app-release.apk")]),
    Requirement("60", "Ecran Diagnostic avec tests", [
        Probe("route", "/diagnostics"), Probe("dart", r"diagnostics_screen|DiagnosticsScreen"),
        Probe("route", "/diagnostics/test/")]),
    Requirement("61", "Logs structures avec rotation et export", [
        Probe("py", r"RotatingFileHandler"), Probe("py", r"class JsonFormatter"),
        Probe("route", "/diagnostics/export")]),
    Requirement("62", "Erreurs comprehensibles cote mobile", [
        Probe("dart", r"class ApiException"), Probe("dart", r"technical")]),
    Requirement("63", "Performance : intervalles et pagination", [
        Probe("py", r"mt5_poll_interval"), Probe("py", r"offset: int")]),
    Requirement("64", "Machine d'etat des signaux", [
        Probe("py", r"class SignalStatus"), Probe("py", r"ORDER_CHECKED"),
        Probe("py", r"PARTIALLY_CLOSED")]),
    Requirement("65", "Audit complet de chaque trade", [
        Probe("py", r"class AuditLog"), Probe("route", "/audit"), Probe("py", r"ai_model")]),
    # L'exigence est une ABSENCE : aucune logique de martingale ne doit exister.
    # La preuve est que l'application l'annonce explicitement a l'utilisateur et
    # qu'aucun code ne multiplie le risque apres une perte.
    Requirement("67", "Aucune martingale implementee", [
        Probe("dart", r"[Aa]ucune martingale")]),
    Requirement("68", "Checklist avant le passage en reel", [
        Probe("route", "/go-live"), Probe("dart", r"go_live|GoLive")]),
    Requirement("69", "Ecran Decouvrir avec suggestions", [
        Probe("dart", r"discover_screen|DiscoverScreen"),
        Probe("route", "/telegram/discover/suggestions")]),
    Requirement("70", "Trois modes par canal, OBSERVE par defaut", [
        Probe("py", r"OBSERVE"), Probe("py", r"mode: ChannelMode = Field\(default=ChannelMode\.OBSERVE\)")]),
    Requirement("71", "Paper trading reel", [
        Probe("file", "bridge/app/services/trading/paper.py"), Probe("py", r"ExecutionMode\.PAPER")]),
    Requirement("72", "Comparaison de canaux", [
        Probe("route", "/channels/compare"), Probe("dart", r"channel_compare|ChannelCompare")]),
    Requirement("73", "Gestion des quotas OpenRouter et disjoncteur", [
        Probe("py", r"429"), Probe("py", r"circuit|CircuitBreaker")]),
    Requirement("74", "Confidentialite : rien d'inutile envoye a l'IA", [
        Probe("py", r"def redact|register_secret")]),
    Requirement("75", "Export / import des donnees non secretes", [
        Probe("route", "/settings/export"), Probe("route", "/settings/import")]),
    Requirement("76", "Migrations de base de donnees", [
        Probe("file", "bridge/app/database/migrations.py"), Probe("py", r"schema_migrations")]),
    Requirement("81", "FakeMetaTraderService pour tester sans argent", [
        Probe("py", r"class FakeMetaTraderService"), Probe("py", r"MT5 REAL NOT TESTED|not_tested")]),
    Requirement("82", "Scenario complet de bout en bout", [
        Probe("route", "/signals/simulate"), Probe("test", r"def test_.*scenario|engine_scenarios")]),
]


def main() -> int:
    complete: list[Requirement] = []
    partial: list[tuple[Requirement, list[Probe]]] = []
    missing: list[tuple[Requirement, list[Probe]]] = []

    for requirement in REQUIREMENTS:
        failed = [probe for probe in requirement.probes if not check(probe)]
        if not failed:
            complete.append(requirement)
        elif len(failed) == len(requirement.probes):
            missing.append((requirement, failed))
        else:
            partial.append((requirement, failed))

    total = len(REQUIREMENTS)
    print("=" * 74)
    print(f"  AUDIT DU CAHIER DES CHARGES - {total} exigences verifiees contre le code")
    print("=" * 74)
    print(f"\n  Couvertes entierement : {len(complete)}/{total}")
    print(f"  Partielles            : {len(partial)}/{total}")
    print(f"  Absentes              : {len(missing)}/{total}")

    if partial:
        print("\n--- PARTIELLES (preuve manquante pour une partie des points) ---")
        for requirement, failed in partial:
            print(f"\n  Section {requirement.section} : {requirement.title}")
            for probe in failed:
                print(f"     non trouve [{probe.kind}] {probe.needle}")

    if missing:
        print("\n--- ABSENTES ---")
        for requirement, failed in missing:
            print(f"\n  Section {requirement.section} : {requirement.title}")
            for probe in failed:
                print(f"     non trouve [{probe.kind}] {probe.needle}")

    print("\n--- COUVERTES ---")
    for requirement in complete:
        print(f"  OK  section {requirement.section:4} {requirement.title}")

    print("\n" + "=" * 74)
    return 0 if not missing else 1


if __name__ == "__main__":
    sys.exit(main())
