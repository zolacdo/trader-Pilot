import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api/api_exception.dart';
import '../../core/api/ws_client.dart';
import '../../core/connection/connection_controller.dart';
import '../../core/theme/app_colors.dart';
import '../../core/theme/app_theme.dart';
import '../../core/utils/formatters.dart';
import '../../core/widgets/app_widgets.dart';
import 'diagnostics_providers.dart';
import 'widgets/diagnostics_widgets.dart';

/// Diagnostic système (CDC section 60).
///
/// Aucun bouton de cet écran n'envoie d'ordre : les cibles de test se limitent
/// à des vérifications de connexion.
class DiagnosticsScreen extends ConsumerWidget {
  const DiagnosticsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final AsyncValue<Map<String, dynamic>> diagnostics = ref.watch(diagnosticsProvider);

    return Scaffold(
      appBar: AppBar(
        title: const Text('Diagnostic système'),
        actions: <Widget>[
          IconButton(
            tooltip: 'Actualiser',
            onPressed: () => ref.invalidate(diagnosticsProvider),
            icon: const Icon(Icons.refresh),
          ),
        ],
      ),
      body: diagnostics.when(
        loading: () => const LoadingView(label: 'Interrogation du Bridge…'),
        error: (Object error, StackTrace stack) => ErrorView(
          message: error is ApiException ? error.message : 'Diagnostic indisponible.',
          technical: error is ApiException ? error.technical : error.toString(),
          onRetry: () => ref.invalidate(diagnosticsProvider),
        ),
        data: (Map<String, dynamic> data) => RefreshIndicator(
          onRefresh: () async => ref.invalidate(diagnosticsProvider),
          child: ListView(
            padding: AppSpacing.page,
            children: <Widget>[
              SecurityWarningsCard(warnings: diagnosticStrings(data, 'warnings')),
              if (diagnosticStrings(data, 'warnings').isNotEmpty)
                const SizedBox(height: AppSpacing.lg),
              _ChecksCard(data: data),
              const SizedBox(height: AppSpacing.lg),
              _AccountCard(data: data),
              const SizedBox(height: AppSpacing.lg),
              const _TestsCard(),
              const SizedBox(height: AppSpacing.lg),
              _EnvironmentCard(data: data),
              const SizedBox(height: AppSpacing.xl),
            ],
          ),
        ),
      ),
    );
  }
}

/// Liste des contrôles renvoyés par le Bridge, précédée de l'application.
class _ChecksCard extends ConsumerWidget {
  const _ChecksCard({required this.data});

  final Map<String, dynamic> data;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final List<Map<String, dynamic>> checks = diagnosticRows(data, 'checks');
    final WsClient ws = ref.watch(wsClientProvider);

    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          const SectionHeader(
            title: 'Contrôles',
            subtitle: 'État de chaque brique nécessaire au fonctionnement.',
          ),
          // L'application elle-même répond puisqu'elle affiche cet écran.
          const CheckTile(
            label: 'Flutter (application)',
            ok: true,
            detail: 'L\'application fonctionne : c\'est elle qui affiche cet écran.',
          ),
          for (final Map<String, dynamic> check in checks)
            CheckTile(
              label: (check['label'] ?? check['key'] ?? '--').toString(),
              ok: check['ok'] == true,
              detail: check['detail']?.toString(),
            ),
          const Divider(height: AppSpacing.xl),
          ValueListenableBuilder<WsStatus>(
            valueListenable: ws.status,
            builder: (BuildContext context, WsStatus status, Widget? child) => CheckTile(
              label: 'WebSocket du téléphone',
              ok: status == WsStatus.connected,
              detail: switch (status) {
                WsStatus.connected => 'Connecté · dernier message ${Fmt.relative(ws.lastMessageAt)}',
                WsStatus.connecting => 'Connexion en cours…',
                WsStatus.disconnected => 'Déconnecté : aucune donnée temps réel.',
              },
            ),
          ),
        ],
      ),
    );
  }
}

/// Mode d'exécution, type de compte, dernier signal et dernier trade.
class _AccountCard extends StatelessWidget {
  const _AccountCard({required this.data});

  final Map<String, dynamic> data;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    final String? accountKind = data['accountKind']?.toString();
    final Map<String, dynamic>? lastSignal = diagnosticMap(data, 'lastSignal');
    final Map<String, dynamic>? lastTrade = diagnosticMap(data, 'lastTrade');
    final Object? profit = lastTrade?['profit'];

    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          const SectionHeader(title: 'Compte et activité'),
          Row(
            children: <Widget>[
              Expanded(
                child: Text('Type de compte', style: theme.textTheme.bodySmall),
              ),
              StatusChip(
                label: switch (accountKind) {
                  'DEMO' => 'DÉMO',
                  'REAL' => 'RÉEL',
                  null => 'INCONNU',
                  _ => accountKind,
                },
                tone: switch (accountKind) {
                  'DEMO' => StatusTone.good,
                  'REAL' => StatusTone.bad,
                  _ => StatusTone.warning,
                },
              ),
            ],
          ),
          const SizedBox(height: AppSpacing.sm),
          DetailRow(
            label: 'Mode d\'exécution',
            value: diagnosticExecutionModeLabel(data['executionMode']?.toString()),
          ),
          DetailRow(
            label: 'Positions ouvertes',
            value: data['openPositions']?.toString() ?? '--',
          ),
          const Divider(height: AppSpacing.xl),
          Text('DERNIER SIGNAL', style: theme.textTheme.labelSmall),
          const SizedBox(height: AppSpacing.xs),
          if (lastSignal == null)
            Text('Aucun signal reçu pour le moment.', style: theme.textTheme.bodySmall)
          else ...<Widget>[
            DetailRow(
              label: 'Instrument',
              value: '${lastSignal['symbol'] ?? '--'} · ${lastSignal['direction'] ?? '--'}',
            ),
            DetailRow(
              label: 'Statut',
              value: Fmt.signalStatus(lastSignal['status']?.toString()),
            ),
            DetailRow(label: 'Reçu le', value: Fmt.full(lastSignal['receivedAt'])),
          ],
          const SizedBox(height: AppSpacing.lg),
          Text('DERNIER TRADE', style: theme.textTheme.labelSmall),
          const SizedBox(height: AppSpacing.xs),
          if (lastTrade == null)
            Text('Aucun trade fermé pour le moment.', style: theme.textTheme.bodySmall)
          else ...<Widget>[
            DetailRow(label: 'Instrument', value: (lastTrade['symbol'] ?? '--').toString()),
            DetailRow(
              label: 'Résultat',
              value: Fmt.signedMoney(profit is num ? profit : null),
              valueColor: profit is num ? AppColors.forAmount(profit) : null,
            ),
            DetailRow(label: 'Fermé le', value: Fmt.full(lastTrade['closedAt'])),
          ],
        ],
      ),
    );
  }
}

/// Tests unitaires de connexion : aucun n'envoie d'ordre.
class _TestsCard extends ConsumerWidget {
  const _TestsCard();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final Map<String, DiagnosticTestResult> results = ref.watch(diagnosticTestsProvider);
    final DiagnosticTestsController controller = ref.read(diagnosticTestsProvider.notifier);

    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          const SectionHeader(
            title: 'Tests de connexion',
            subtitle: 'Chaque test vérifie une liaison et affiche son résultat.',
          ),
          for (final ({String hint, String label, String target}) test in diagnosticTests)
            DiagnosticTestRow(
              label: test.label,
              hint: test.hint,
              result: results[test.target],
              onRun: () => controller.run(test.target),
            ),
          const SizedBox(height: AppSpacing.md),
          Container(
            width: double.infinity,
            padding: const EdgeInsets.all(AppSpacing.md),
            decoration: BoxDecoration(
              color: Theme.of(context).brightness == Brightness.dark
                  ? AppColors.surfaceMutedDark
                  : AppColors.surfaceMuted,
              borderRadius: BorderRadius.circular(AppSpacing.radiusSmall),
            ),
            child: Text(
              'Aucun de ces boutons n\'envoie d\'ordre. Le test d\'exécution d\'un ordre passe '
              'uniquement par le simulateur (Paper Trading) ou par un compte MetaTrader 5 '
              'explicitement détecté comme démo.',
              style: Theme.of(context).textTheme.bodySmall,
            ),
          ),
        ],
      ),
    );
  }
}

/// Environnement du Bridge et informations d'exécution.
class _EnvironmentCard extends StatelessWidget {
  const _EnvironmentCard({required this.data});

  final Map<String, dynamic> data;

  @override
  Widget build(BuildContext context) {
    final Map<String, dynamic> environment =
        diagnosticMap(data, 'environment') ?? const <String, dynamic>{};
    final Map<String, dynamic> runtime =
        diagnosticMap(data, 'runtime') ?? const <String, dynamic>{};

    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          const SectionHeader(title: 'Environnement du Bridge'),
          DetailRow(label: 'Version', value: (runtime['version'] ?? '--').toString()),
          DetailRow(label: 'Version de l\'API', value: (runtime['apiVersion'] ?? '--').toString()),
          DetailRow(
            label: 'Durée de fonctionnement',
            value: Fmt.duration(
              runtime['uptimeSeconds'] is num ? (runtime['uptimeSeconds'] as num).round() : null,
            ),
          ),
          DetailRow(label: 'Plateforme', value: (runtime['platform'] ?? '--').toString()),
          DetailRow(label: 'Python', value: (runtime['python'] ?? '--').toString()),
          const Divider(height: AppSpacing.xl),
          DetailRow(
            label: 'Adresse d\'écoute',
            value: '${environment['host'] ?? '--'}:${environment['port'] ?? '--'}',
          ),
          DetailRow(label: 'Dossier de données', value: (environment['dataDir'] ?? '--').toString()),
          DetailRow(label: 'Niveau de journal', value: (environment['logLevel'] ?? '--').toString()),
          DetailRow(
            label: 'Accès distant (ngrok)',
            value: environment['ngrokEnabled'] == true ? 'activé' : 'désactivé',
          ),
        ],
      ),
    );
  }
}
