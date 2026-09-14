import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/api/api_exception.dart';
import '../../core/providers/bridge_data.dart';
import '../../core/routing/app_router.dart';
import '../../core/theme/app_theme.dart';
import '../../core/utils/formatters.dart';
import '../../core/widgets/app_widgets.dart';
import 'settings_providers.dart';
import 'widgets/connection_sections.dart';
import 'widgets/data_sections.dart';
import 'widgets/device_sections.dart';
import 'widgets/openrouter_section.dart';
import 'widgets/settings_shell.dart';
import 'widgets/trading_section.dart';

/// Paramètres (CDC section 46).
///
/// Toutes les sections demandées, dans l'ordre : compte, bridge, telegram,
/// metatrader, openrouter, trading, notifications, apparence, données, logs,
/// à propos.
class SettingsScreen extends ConsumerWidget {
  const SettingsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final AsyncValue<BridgeData<Map<String, dynamic>>> status = ref.watch(statusProvider);

    return Scaffold(
      appBar: AppBar(title: const Text('Paramètres')),
      body: RefreshIndicator(
        onRefresh: () async {
          ref.invalidate(statusProvider);
          ref.invalidate(tradingStateProvider);
          ref.invalidate(openrouterStatusProvider);
          ref.invalidate(openrouterModelsProvider);
          ref.invalidate(devicesProvider);
          await ref.read(statusProvider.future);
        },
        child: status.when(
          loading: () => const LoadingView(label: 'Lecture de la configuration…'),
          error: (Object error, StackTrace stack) => ErrorView(
            message: error is ApiException ? error.message : 'Configuration indisponible.',
            technical: error is ApiException ? error.technical : error.toString(),
            onRetry: () => ref.invalidate(statusProvider),
          ),
          data: (BridgeData<Map<String, dynamic>> data) => _SettingsBody(data: data),
        ),
      ),
    );
  }
}

class _SettingsBody extends StatelessWidget {
  const _SettingsBody({required this.data});

  final BridgeData<Map<String, dynamic>> data;

  @override
  Widget build(BuildContext context) {
    return ListView(
      padding: AppSpacing.page,
      physics: const AlwaysScrollableScrollPhysics(),
      children: <Widget>[
        if (data.stale)
          Padding(
            padding: const EdgeInsets.only(bottom: AppSpacing.lg),
            child: SettingsNote(
              text: 'Le Bridge ne répond pas : ces informations datent de '
                  '${Fmt.dayTime(data.updatedAt)}. Aucune modification ne peut être enregistrée '
                  'tant que la liaison n\'est pas rétablie.',
              warning: true,
            ),
          ),
        AccountSection(status: data.value),
        BridgeSection(status: data.value),
        TelegramSection(status: data.value),
        MetaTraderSection(status: data.value),
        const OpenRouterSection(),
        const TradingSection(),
        const _RiskShortcutSection(),
        const NotificationsSection(),
        const AppearanceSection(),
        const DataSection(),
        const LogsSection(),
        AboutSection(status: data.value),
        const SizedBox(height: AppSpacing.xl),
      ],
    );
  }
}

/// Renvoi vers la gestion du risque, qui a son écran dédié.
class _RiskShortcutSection extends StatelessWidget {
  const _RiskShortcutSection();

  @override
  Widget build(BuildContext context) {
    return SettingsSection(
      title: 'Gestion du risque',
      subtitle: 'Les limites appliquées avant chaque ordre.',
      children: <Widget>[
        ListTile(
          contentPadding: EdgeInsets.zero,
          leading: const Icon(Icons.shield_outlined),
          title: const Text('Ouvrir la gestion du risque'),
          subtitle: const Text(
            'Risque par trade, limites journalières, break even, trailing stop.',
          ),
          trailing: const Icon(Icons.chevron_right, size: 20),
          onTap: () => context.push(Routes.risk),
        ),
        ListTile(
          contentPadding: EdgeInsets.zero,
          leading: const Icon(Icons.swap_horiz),
          title: const Text('Correspondance des symboles'),
          subtitle: const Text('Relier les noms des signaux aux symboles réels du broker.'),
          trailing: const Icon(Icons.chevron_right, size: 20),
          onTap: () => context.push(Routes.symbols),
        ),
      ],
    );
  }
}
