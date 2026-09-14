import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/connection/connection_controller.dart';
import '../../../core/routing/app_router.dart';
import '../../../core/theme/app_theme.dart';
import '../../../core/utils/formatters.dart';
import '../../../core/widgets/app_widgets.dart';
import '../settings_providers.dart';
import 'settings_shell.dart';

Map<String, dynamic> _sub(Map<String, dynamic> source, String key) {
  final Object? value = source[key];
  return value is Map ? Map<String, dynamic>.from(value) : <String, dynamic>{};
}

/// Section Compte : l'appareil appairé et sa liaison avec le Bridge.
class AccountSection extends ConsumerWidget {
  const AccountSection({super.key, required this.status});

  final Map<String, dynamic> status;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final BridgeConnectionState connection = ref.watch(connectionProvider);
    final AsyncValue<List<Map<String, dynamic>>> devices = ref.watch(devicesProvider);
    final Map<String, dynamic> account = _sub(_sub(status, 'account'), 'account');
    final String kind = _sub(status, 'account')['kind']?.toString() ?? 'UNKNOWN';

    return SettingsSection(
      title: 'Compte',
      subtitle: 'Le téléphone, sa liaison avec le Bridge, et le compte de trading utilisé.',
      children: <Widget>[
        DetailRow(label: 'Adresse du Bridge', value: connection.baseUrl ?? '--'),
        DetailRow(
          label: 'Adresse de repli',
          value: connection.fallbackUrl ?? 'Aucune',
        ),
        DetailRow(label: 'Appairage', value: connection.paired ? 'Actif' : 'Non appairé'),
        devices.when(
          loading: () => const DetailRow(label: 'Appareils autorisés', value: '…'),
          error: (Object error, StackTrace stack) =>
              const DetailRow(label: 'Appareils autorisés', value: '--'),
          data: (List<Map<String, dynamic>> items) => DetailRow(
            label: 'Appareils autorisés',
            value: '${items.where((Map<String, dynamic> d) => d['revoked'] != true).length}',
          ),
        ),
        const Divider(height: AppSpacing.xl),
        DetailRow(label: 'Compte de trading', value: account['login']?.toString() ?? '--'),
        DetailRow(label: 'Serveur', value: account['server']?.toString() ?? '--'),
        DetailRow(
          label: 'Type de compte',
          value: switch (kind) {
            'DEMO' => 'Démo',
            'REAL' => 'Réel',
            _ => 'Indéterminé',
          },
        ),
        DetailRow(
          label: 'Solde',
          value: account['balance'] == null
              ? '--'
              : Fmt.money(
                  account['balance'] as num,
                  currency: account['currency']?.toString() ?? 'USD',
                ),
        ),
        Align(
          alignment: Alignment.centerLeft,
          child: TextButton.icon(
            onPressed: () => context.push(Routes.connections),
            icon: const Icon(Icons.hub_outlined, size: 18),
            label: const Text('Gérer les connexions'),
            style: TextButton.styleFrom(padding: EdgeInsets.zero),
          ),
        ),
      ],
    );
  }
}

/// Section Bridge : la machine Windows qui fait tout le travail.
class BridgeSection extends StatelessWidget {
  const BridgeSection({super.key, required this.status});

  final Map<String, dynamic> status;

  @override
  Widget build(BuildContext context) {
    final Map<String, dynamic> bridge = _sub(status, 'bridge');
    final Map<String, dynamic> tunnel = _sub(status, 'tunnel');
    final Object? uptime = bridge['uptimeSeconds'];

    return SettingsSection(
      title: 'Bridge',
      subtitle: 'Le programme installé sur le PC : il parle à Telegram et à MetaTrader.',
      children: <Widget>[
        DetailRow(label: 'État', value: connectionStateLabel(bridge['state']?.toString())),
        DetailRow(
          label: 'En fonctionnement depuis',
          value: Fmt.duration(uptime is num ? uptime.toInt() : null),
        ),
        DetailRow(label: 'Adresse publique', value: bridge['publicUrl']?.toString() ?? 'Aucune'),
        DetailRow(label: 'Tunnel', value: connectionStateLabel(tunnel['state']?.toString())),
        DetailRow(label: 'Système', value: bridge['platform']?.toString() ?? '--'),
        const SettingsNote(
          text: 'Si le PC est éteint ou en veille, aucun signal n\'est reçu et aucun ordre n\'est '
              'envoyé : l\'application le signale par un bandeau « Bridge hors ligne ».',
        ),
      ],
    );
  }
}

/// Section Telegram : état résumé, gestion détaillée dans les Connexions.
class TelegramSection extends StatelessWidget {
  const TelegramSection({super.key, required this.status});

  final Map<String, dynamic> status;

  @override
  Widget build(BuildContext context) {
    final Map<String, dynamic> telegram = _sub(status, 'telegram');
    final String? lastError = telegram['lastError']?.toString();

    return SettingsSection(
      title: 'Telegram',
      subtitle: 'La source des signaux.',
      children: <Widget>[
        Row(
          children: <Widget>[
            Expanded(
              child: Text(
                connectionStateLabel(telegram['state']?.toString()),
                style: Theme.of(context).textTheme.titleMedium,
              ),
            ),
            StatusChip.connection(
              connected: telegram['state'] == 'CONNECTED',
              labelOverride: telegram['state'] == 'CONNECTED' ? 'Connecté' : 'Non connecté',
            ),
          ],
        ),
        const SizedBox(height: AppSpacing.sm),
        DetailRow(label: 'Compte', value: telegram['username']?.toString() ?? '--'),
        DetailRow(label: 'Téléphone', value: telegram['phone']?.toString() ?? '--'),
        DetailRow(
          label: 'Session autorisée',
          value: telegram['authorized'] == true ? 'Oui' : 'Non',
        ),
        if (lastError != null && lastError.isNotEmpty)
          SettingsNote(text: 'Dernière erreur : $lastError', warning: true),
        Align(
          alignment: Alignment.centerLeft,
          child: TextButton.icon(
            onPressed: () => context.push(Routes.connections),
            icon: const Icon(Icons.chevron_right, size: 18),
            label: const Text('Connecter, reconnecter ou déconnecter'),
            style: TextButton.styleFrom(padding: EdgeInsets.zero),
          ),
        ),
      ],
    );
  }
}

/// Section MetaTrader : le terminal qui exécute réellement les ordres.
class MetaTraderSection extends StatelessWidget {
  const MetaTraderSection({super.key, required this.status});

  final Map<String, dynamic> status;

  @override
  Widget build(BuildContext context) {
    final Map<String, dynamic> mt5 = _sub(status, 'mt5');
    final Map<String, dynamic> account = _sub(mt5, 'account');
    final Map<String, dynamic> terminal = _sub(mt5, 'terminal');
    final String? error = mt5['error']?.toString();

    return SettingsSection(
      title: 'MetaTrader 5',
      subtitle: 'Le terminal qui envoie les ordres au broker.',
      children: <Widget>[
        Row(
          children: <Widget>[
            Expanded(
              child: Text(
                connectionStateLabel(mt5['state']?.toString()),
                style: Theme.of(context).textTheme.titleMedium,
              ),
            ),
            StatusChip.connection(
              connected: mt5['state'] == 'CONNECTED',
              labelOverride: mt5['state'] == 'CONNECTED' ? 'Connecté' : 'Non connecté',
            ),
          ],
        ),
        const SizedBox(height: AppSpacing.sm),
        DetailRow(label: 'Numéro de compte', value: account['login']?.toString() ?? '--'),
        DetailRow(label: 'Serveur', value: account['server']?.toString() ?? '--'),
        DetailRow(
          label: 'Type de compte',
          value: switch (account['kind']?.toString()) {
            'DEMO' => 'Démo',
            'REAL' => 'Réel',
            _ => 'Indéterminé',
          },
        ),
        DetailRow(
          label: 'Trading autorisé par le terminal',
          value: terminal['tradeAllowed'] == true ? 'Oui' : 'Non',
        ),
        DetailRow(label: 'Terminal installé', value: mt5['terminalPath']?.toString() ?? '--'),
        if (error != null && error.isNotEmpty)
          SettingsNote(text: 'Dernière erreur : $error', warning: true),
        Align(
          alignment: Alignment.centerLeft,
          child: TextButton.icon(
            onPressed: () => context.push(Routes.connections),
            icon: const Icon(Icons.chevron_right, size: 18),
            label: const Text('Reconnecter MetaTrader'),
            style: TextButton.styleFrom(padding: EdgeInsets.zero),
          ),
        ),
      ],
    );
  }
}
