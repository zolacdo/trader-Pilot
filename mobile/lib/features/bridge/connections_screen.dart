import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/providers/bridge_data.dart';
import '../../core/theme/app_colors.dart';
import '../../core/theme/app_theme.dart';
import '../../core/utils/formatters.dart';
import '../../core/widgets/app_widgets.dart';
import 'widgets/bridge_connection_card.dart';
import 'widgets/bridge_error_view.dart';
import 'widgets/mt5_connection_card.dart';
import 'widgets/openrouter_connection_card.dart';
import 'widgets/telegram_connection_card.dart';

/// État et pilotage des quatre liaisons : Bridge, Telegram, MetaTrader 5
/// et OpenRouter.
class ConnectionsScreen extends ConsumerWidget {
  const ConnectionsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final AsyncValue<BridgeData<Map<String, dynamic>>> status = ref.watch(statusProvider);

    return Scaffold(
      appBar: AppBar(
        title: const Text('Connexions'),
        actions: <Widget>[
          IconButton(
            tooltip: 'Actualiser',
            onPressed: () => refreshBridgeData(ref),
            icon: const Icon(Icons.refresh),
          ),
        ],
      ),
      body: status.when(
        loading: () => const LoadingView(label: 'Lecture de l\'état des connexions…'),
        error: (Object error, StackTrace _) => BridgeErrorView(
          error: error,
          onRetry: () => refreshBridgeData(ref),
        ),
        data: (BridgeData<Map<String, dynamic>> data) => RefreshIndicator(
          color: AppColors.primary,
          onRefresh: () async => refreshBridgeData(ref),
          child: ListView(
            physics: const AlwaysScrollableScrollPhysics(),
            padding: AppSpacing.page,
            children: <Widget>[
              if (data.stale) ...<Widget>[
                _StaleNotice(updatedAt: data.updatedAt),
                const SizedBox(height: AppSpacing.lg),
              ],
              BridgeConnectionCard(payload: data.value),
              const SizedBox(height: AppSpacing.lg),
              TelegramConnectionCard(payload: data.value),
              const SizedBox(height: AppSpacing.lg),
              Mt5ConnectionCard(payload: data.value),
              const SizedBox(height: AppSpacing.lg),
              OpenRouterConnectionCard(payload: data.value),
              const SizedBox(height: AppSpacing.xxl),
            ],
          ),
        ),
      ),
    );
  }
}

/// Signale que les états affichés proviennent du dernier instantané connu.
class _StaleNotice extends StatelessWidget {
  const _StaleNotice({this.updatedAt});

  final DateTime? updatedAt;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    return Row(
      children: <Widget>[
        const Icon(Icons.history_toggle_off, size: 16, color: AppColors.warning),
        const SizedBox(width: AppSpacing.sm),
        Expanded(
          child: Text(
            updatedAt == null
                ? 'États en cache — Bridge hors ligne'
                : 'États du ${Fmt.time(updatedAt)} — Bridge hors ligne',
            style: theme.textTheme.bodySmall?.copyWith(color: AppColors.warning),
          ),
        ),
      ],
    );
  }
}
