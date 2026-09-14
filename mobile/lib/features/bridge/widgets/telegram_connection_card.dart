import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/api/endpoints.dart';
import '../../../core/connection/connection_controller.dart';
import '../../../core/providers/bridge_data.dart';
import '../../../core/routing/app_router.dart';
import '../../../core/widgets/app_widgets.dart';
import '../models/bridge_action.dart';
import '../models/bridge_json.dart';
import '../models/bridge_labels.dart';
import 'connection_block.dart';

/// Liaison Telegram : compte connecté et pilotage de la session.
///
/// Le numéro affiché est déjà masqué par le Bridge et aucune information de
/// session ne transite par le téléphone.
class TelegramConnectionCard extends ConsumerStatefulWidget {
  const TelegramConnectionCard({super.key, required this.payload});

  final Map<String, dynamic> payload;

  @override
  ConsumerState<TelegramConnectionCard> createState() => _TelegramConnectionCardState();
}

class _TelegramConnectionCardState extends ConsumerState<TelegramConnectionCard> {
  String? _running;

  Future<void> _call(String key, String path, String successMessage) async {
    if (_running != null) return;
    setState(() => _running = key);
    await runBridgeAction(
      context,
      action: () => ref.read(apiClientProvider).postJson(path),
      successMessage: successMessage,
    );
    if (!mounted) return;
    setState(() => _running = null);
    refreshBridgeData(ref);
  }

  Future<void> _logout() async {
    final bool confirmed = await confirmAction(
      context,
      title: 'Se déconnecter définitivement',
      message: 'La session Telegram enregistrée sur le Bridge sera supprimée. '
          'Il faudra recommencer la connexion complète (code reçu par Telegram, '
          'puis mot de passe 2FA si vous en avez un).',
      confirmLabel: 'Supprimer la session',
      destructive: true,
    );
    if (!confirmed || !mounted) return;
    await _call('logout', Endpoints.telegramLogout, 'Session Telegram supprimée.');
  }

  @override
  Widget build(BuildContext context) {
    final Map<String, dynamic> telegram = Json.map(widget.payload['telegram']);
    final String? state = Json.text(telegram['state']);
    final bool authorized = Json.flag(telegram['authorized']);
    final String? username = Json.text(telegram['username']);
    final String? phone = Json.text(telegram['phone']);

    return ConnectionBlock(
      title: 'Telegram',
      icon: Icons.send_outlined,
      connected: authorized,
      stateLabel: authorized ? BridgeLabels.connection(state) : 'Non connecté',
      subtitle: 'Compte utilisateur qui lit les canaux de signaux.',
      errorMessage: Json.text(telegram['lastError']),
      rows: <Widget>[
        DetailRow(label: 'Compte', value: username == null ? '--' : '@$username'),
        DetailRow(label: 'Numéro', value: phone ?? '--'),
        DetailRow(label: 'État', value: BridgeLabels.connection(state)),
      ],
      actions: <Widget>[
        // Un compte jamais configuré n'a rien à reconnecter : il faut d'abord
        // saisir l'API ID, l'API Hash et le code reçu par Telegram, ce que
        // seule la configuration guidée propose.
        if (!authorized && phone == null)
          ConnectionAction(
            label: 'Configurer Telegram',
            icon: Icons.login,
            onPressed: _running != null ? null : () => context.push(Routes.onboarding),
          )
        else
          ConnectionAction(
            label: 'Reconnecter',
            icon: Icons.refresh,
            busy: _running == 'reconnect',
            onPressed: _running != null
                ? null
                : () => _call(
                      'reconnect',
                      Endpoints.telegramReconnect,
                      'Reconnexion Telegram demandée.',
                    ),
          ),
        ConnectionAction(
          label: 'Déconnecter',
          icon: Icons.pause_circle_outline,
          busy: _running == 'disconnect',
          onPressed: _running != null || !authorized
              ? null
              : () => _call(
                    'disconnect',
                    Endpoints.telegramDisconnect,
                    'Telegram déconnecté. La session reste enregistrée.',
                  ),
        ),
        ConnectionAction(
          label: 'Se déconnecter définitivement',
          icon: Icons.logout,
          destructive: true,
          busy: _running == 'logout',
          onPressed: _running != null ? null : _logout,
        ),
      ],
    );
  }
}
