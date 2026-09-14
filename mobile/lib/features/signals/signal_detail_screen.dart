import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api/api_exception.dart';
import '../../core/theme/app_theme.dart';
import '../../core/widgets/app_widgets.dart';
import 'models/signal.dart';
import 'providers/signals_providers.dart';
import 'widgets/pending_review_banner.dart';
import 'widgets/signal_decision.dart';
import 'widgets/signal_detail_sections.dart';
import 'widgets/signal_result_sections.dart';
import 'widgets/signal_timeline.dart';

/// Détail complet d'un signal (CDC section 34).
class SignalDetailScreen extends ConsumerWidget {
  const SignalDetailScreen({super.key, required this.signalId});

  final int signalId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    ref.watch(signalsLiveProvider);
    final AsyncValue<SignalDetail> detail = ref.watch(signalDetailProvider(signalId));
    final SignalDetail? value = detail.valueOrNull;

    return Scaffold(
      appBar: AppBar(title: Text('Signal n° $signalId')),
      body: switch (detail) {
        AsyncError(:final Object error) when value == null => ErrorView(
            message: error is ApiException ? error.message : 'Signal indisponible.',
            technical: error is ApiException ? error.technical : error.toString(),
            onRetry: () => ref.invalidate(signalDetailProvider(signalId)),
          ),
        AsyncLoading<SignalDetail>() when value == null =>
          const LoadingView(label: 'Chargement du signal…'),
        _ => _DetailBody(detail: value!),
      },
      bottomNavigationBar: value != null && value.signal.needsReview
          ? _DecisionBar(signal: value.signal)
          : null,
    );
  }
}

class _DetailBody extends ConsumerWidget {
  const _DetailBody({required this.detail});

  final SignalDetail detail;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final Signal signal = detail.signal;
    return RefreshIndicator(
      onRefresh: () async {
        ref.invalidate(signalDetailProvider(signal.id));
        await ref.read(signalDetailProvider(signal.id).future);
      },
      child: ListView(
        physics: const AlwaysScrollableScrollPhysics(),
        padding: AppSpacing.page,
        children: <Widget>[
          RawMessageSection(signal: signal),
          InterpretationSection(signal: signal),
          ValidationSection(signal: signal),
          RiskSection(signal: signal),
          OrderSection(signal: signal, pendingOrders: detail.pendingOrders),
          ResultSection(trades: detail.trades),
          DetailSection(
            title: 'Chronologie',
            subtitle: 'Du message reçu jusqu\'à la fermeture.',
            child: SignalTimeline(steps: _timeline(detail)),
          ),
          FollowUpsSection(followUps: detail.followUps),
          AuditSection(audit: detail.audit),
          const SizedBox(height: AppSpacing.xl),
        ],
      ),
    );
  }

  /// La réception du message ouvre la chronologie : sa date vient du signal.
  static List<SignalStep> _timeline(SignalDetail detail) {
    final Signal signal = detail.signal;
    return <SignalStep>[
      SignalStep(
        stage: 'received',
        success: true,
        message: signal.channelTitle == null
            ? 'Message reçu par le Bridge'
            : 'Message reçu du canal ${signal.channelTitle}',
        createdAt: signal.receivedAt,
      ),
      ...detail.timeline,
    ];
  }
}

/// Barre de décision affichée tant que le signal attend une validation.
class _DecisionBar extends StatelessWidget {
  const _DecisionBar({required this.signal});

  final Signal signal;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    return SafeArea(
      child: Container(
        padding: const EdgeInsets.all(AppSpacing.lg),
        decoration: BoxDecoration(
          color: theme.cardTheme.color,
          border: Border(top: BorderSide(color: theme.colorScheme.outline)),
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: <Widget>[
            Row(
              children: <Widget>[
                Expanded(
                  child: Text(
                    'Ce signal attend votre décision.',
                    style: theme.textTheme.bodySmall,
                  ),
                ),
                ExpiryCountdown(expiresAt: signal.expiresAt),
              ],
            ),
            const SizedBox(height: AppSpacing.md),
            SignalDecisionButtons(signal: signal),
          ],
        ),
      ),
    );
  }
}
