import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/api/api_exception.dart';
import '../../core/providers/bridge_data.dart';
import '../../core/routing/app_router.dart';
import '../../core/theme/app_theme.dart';
import '../../core/utils/formatters.dart';
import '../../core/widgets/app_widgets.dart';

/// Page « Plus » (CDC section 6) : accès aux écrans secondaires.
///
/// En tête, une carte rappelle l'état réel de l'automatisation pour qu'on ne
/// se trompe jamais sur ce que fait le Bridge à cet instant.
class MoreScreen extends ConsumerWidget {
  const MoreScreen({super.key});

  static const List<_MoreEntry> _entries = <_MoreEntry>[
    // Reste accessible en permanence : la configuration guidée contient les
    // seuls écrans permettant de connecter Telegram (API ID, code SMS, 2FA).
    // Sans cette entrée, une configuration interrompue serait irrattrapable.
    _MoreEntry(Routes.onboarding, Icons.playlist_add_check_circle_outlined, 'Configuration guidée',
        'Reprendre les 8 étapes : Telegram, OpenRouter, risque et mode.'),
    _MoreEntry(Routes.notifications, Icons.notifications_outlined, 'Notifications',
        'Tout ce que le Bridge a jugé digne d\'être signalé.'),
    _MoreEntry(Routes.opportunities, Icons.auto_awesome_outlined, 'Opportunités',
        'Setups détectés par le système lui-même, avec leur plan chiffré.'),
    _MoreEntry(Routes.markets, Icons.show_chart_outlined, 'Marchés',
        'Watchlist, régime de marché et structure multi-timeframes.'),
    _MoreEntry(Routes.news, Icons.public_outlined, 'Actualités et calendrier',
        'Dépêches qualifiées et publications économiques à venir.'),
    _MoreEntry(Routes.decisions, Icons.rule_outlined, 'Décisions',
        'Pourquoi le système a agi — et surtout pourquoi il s\'est abstenu.'),
    _MoreEntry(Routes.statistics, Icons.insights_outlined, 'Statistiques',
        'Résultats, taux de réussite et ventilation par canal.'),
    _MoreEntry(Routes.ai, Icons.image_search_outlined, 'Analyse d\'une capture',
        'Lecture informative d\'une capture de graphique. Aucun ordre envoyé.'),
    _MoreEntry(Routes.aiConfig, Icons.psychology_outlined, 'Moteurs d\'IA',
        'Moteur local et OpenRouter : mode, modèles et arbitrage.'),
    _MoreEntry(Routes.aiDiagnostic, Icons.troubleshoot_outlined, 'Diagnostic IA',
        'Disponibilité, latence et fiabilité mesurée de chaque moteur.'),
    _MoreEntry(Routes.journal, Icons.receipt_long_outlined, 'Journal',
        'Historique complet des événements du Bridge.'),
    _MoreEntry(Routes.risk, Icons.shield_outlined, 'Gestion du risque',
        'Limites appliquées avant chaque ordre : la dernière barrière.'),
    _MoreEntry(Routes.connections, Icons.hub_outlined, 'Connexions',
        'Bridge, Telegram et MetaTrader 5.'),
    _MoreEntry(Routes.settings, Icons.settings_outlined, 'Paramètres',
        'Trading, OpenRouter, notifications, sauvegarde.'),
    _MoreEntry(Routes.diagnostics, Icons.medical_services_outlined, 'Diagnostic système',
        'Vérifie chaque brique et explique ce qui bloque.'),
    _MoreEntry(Routes.symbols, Icons.swap_horiz, 'Correspondance des symboles',
        'Relie les noms des signaux aux symboles réels du broker.'),
    _MoreEntry(Routes.goLive, Icons.checklist_outlined, 'Checklist avant le réel',
        'Ce qui doit être vrai avant de passer sur un compte réel.'),
  ];

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return Scaffold(
      appBar: AppBar(title: const Text('Plus')),
      body: RefreshIndicator(
        onRefresh: () async {
          ref.invalidate(tradingStateProvider);
          await ref.read(tradingStateProvider.future);
        },
        child: ListView(
          padding: AppSpacing.page,
          physics: const AlwaysScrollableScrollPhysics(),
          children: <Widget>[
            const _TradingStateCard(),
            const SizedBox(height: AppSpacing.lg),
            for (final _MoreEntry entry in _entries) ...<Widget>[
              _MoreTile(entry: entry),
              const SizedBox(height: AppSpacing.sm),
            ],
          ],
        ),
      ),
    );
  }
}

class _MoreEntry {
  const _MoreEntry(this.route, this.icon, this.title, this.subtitle);

  final String route;
  final IconData icon;
  final String title;
  final String subtitle;
}

class _MoreTile extends StatelessWidget {
  const _MoreTile({required this.entry});

  final _MoreEntry entry;

  @override
  Widget build(BuildContext context) {
    return AppCard(
      padding: EdgeInsets.zero,
      child: ListTile(
        leading: Icon(entry.icon),
        title: Text(entry.title),
        subtitle: Text(entry.subtitle),
        trailing: const Icon(Icons.chevron_right, size: 20),
        onTap: () => context.push(entry.route),
      ),
    );
  }
}

/// Carte d'état : où partent les ordres, l'automatisation tourne-t-elle.
class _TradingStateCard extends ConsumerWidget {
  const _TradingStateCard();

  static String _modeLabel(String? mode) {
    return switch (mode) {
      'PAPER' => 'Paper trading',
      'MT5_DEMO' => 'MT5 démo',
      'MT5_LIVE' => 'MT5 réel',
      null => '--',
      _ => mode,
    };
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final AsyncValue<Map<String, dynamic>> state = ref.watch(tradingStateProvider);

    return state.when(
      loading: () => const AppCard(
        child: SizedBox(height: 96, child: LoadingView(label: 'Lecture de l\'état…')),
      ),
      error: (Object error, StackTrace stack) => AppCard(
        child: ErrorView(
          message: error is ApiException ? error.message : 'État du trading indisponible.',
          technical: error is ApiException ? error.technical : error.toString(),
          onRetry: () => ref.invalidate(tradingStateProvider),
        ),
      ),
      data: (Map<String, dynamic> data) {
        final String? mode = data['executionMode']?.toString();
        final bool live = mode == 'MT5_LIVE';
        final bool auto = data['autoTradingEnabled'] == true;
        final bool paused = data['paused'] == true;
        final String? reason = data['pauseReason']?.toString();
        final Object? pausedUntil = data['pausedUntil'];

        return AppCard(
          accent: live,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: <Widget>[
              const SectionHeader(
                title: 'État de l\'automatisation',
                subtitle: 'Ce que le Bridge fait réellement en ce moment.',
              ),
              DetailRow(label: 'Mode d\'exécution', value: _modeLabel(mode)),
              DetailRow(
                label: 'Trading automatique',
                value: auto ? 'Activé' : 'Désactivé',
              ),
              DetailRow(
                label: 'Pertes consécutives',
                value: '${data['consecutiveLosses'] ?? '--'}',
              ),
              const SizedBox(height: AppSpacing.sm),
              Wrap(
                spacing: AppSpacing.sm,
                runSpacing: AppSpacing.sm,
                children: <Widget>[
                  StatusChip(
                    label: live ? 'Compte réel' : 'Aucun ordre réel',
                    tone: live ? StatusTone.warning : StatusTone.neutral,
                    dense: true,
                  ),
                  StatusChip(
                    label: auto ? 'Auto trading actif' : 'Auto trading arrêté',
                    tone: auto ? StatusTone.good : StatusTone.neutral,
                    dense: true,
                  ),
                  if (paused)
                    const StatusChip(
                      label: 'En pause',
                      tone: StatusTone.warning,
                      icon: Icons.pause_circle_outline,
                      dense: true,
                    ),
                ],
              ),
              if (paused) ...<Widget>[
                const SizedBox(height: AppSpacing.sm),
                Text(
                  reason == null
                      ? 'Aucun nouveau trade n\'est ouvert pour le moment.'
                      : 'Motif : $reason',
                  style: Theme.of(context).textTheme.bodySmall,
                ),
                if (pausedUntil != null)
                  Text(
                    'Reprise prévue : ${Fmt.dayTime(pausedUntil)}',
                    style: Theme.of(context).textTheme.bodySmall,
                  ),
              ],
            ],
          ),
        );
      },
    );
  }
}
