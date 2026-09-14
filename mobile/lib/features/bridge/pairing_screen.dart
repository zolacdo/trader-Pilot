import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/api/api_client.dart';
import '../../core/api/api_exception.dart';
import '../../core/api/endpoints.dart';
import '../../core/connection/connection_controller.dart';
import '../../core/routing/app_router.dart';
import '../../core/theme/app_colors.dart';
import '../../core/theme/app_theme.dart';
import '../../core/widgets/app_widgets.dart';
import 'models/bridge_json.dart';
import 'widgets/pairing_code_field.dart';

/// Résultat du dernier test d'adresse.
enum _AddressTest { untested, reachable, unreachable }

/// Écran d'appairage : premier écran tant que le téléphone n'est pas relié
/// à un Bridge (CDC section 41).
///
/// Aucune donnée de trading n'est accessible avant cet appairage : le jeton
/// obtenu ici authentifie toutes les routes sensibles.
class PairingScreen extends ConsumerStatefulWidget {
  const PairingScreen({super.key});

  @override
  ConsumerState<PairingScreen> createState() => _PairingScreenState();
}

class _PairingScreenState extends ConsumerState<PairingScreen> {
  final TextEditingController _address = TextEditingController();
  final TextEditingController _code = TextEditingController();

  bool _testing = false;
  bool _pairing = false;
  _AddressTest _test = _AddressTest.untested;
  String? _error;
  String? _technical;

  @override
  void initState() {
    super.initState();
    // Une adresse déjà enregistrée est proposée telle quelle.
    final String? known = ref.read(connectionProvider).baseUrl;
    if (known != null && known.isNotEmpty) {
      _address.text = known;
    }
    _address.addListener(_onAddressChanged);
    _code.addListener(_onCodeChanged);
  }

  @override
  void dispose() {
    _address
      ..removeListener(_onAddressChanged)
      ..dispose();
    _code
      ..removeListener(_onCodeChanged)
      ..dispose();
    super.dispose();
  }

  void _onAddressChanged() {
    if (_test != _AddressTest.untested) {
      setState(() => _test = _AddressTest.untested);
    }
  }

  void _onCodeChanged() => setState(() {});

  bool get _canPair =>
      !_pairing &&
      !_testing &&
      _address.text.trim().isNotEmpty &&
      PairingCodeFormatter.isComplete(_code.text);

  Future<void> _testAddress() async {
    final String url = _address.text.trim();
    if (url.isEmpty || _testing) return;
    FocusScope.of(context).unfocus();
    setState(() {
      _testing = true;
      _error = null;
      _technical = null;
    });
    final bool reachable = await ref.read(connectionProvider.notifier).testAddress(url);
    if (!mounted) return;
    setState(() {
      _testing = false;
      _test = reachable ? _AddressTest.reachable : _AddressTest.unreachable;
    });
  }

  Future<void> _pair() async {
    if (!_canPair) return;
    FocusScope.of(context).unfocus();
    setState(() {
      _pairing = true;
      _error = null;
      _technical = null;
    });
    try {
      await ref.read(connectionProvider.notifier).pair(
            baseUrl: _address.text.trim(),
            code: PairingCodeFormatter.compact(_code.text),
          );
      final bool completed = await _onboardingCompleted();
      if (!mounted) return;
      _code.clear();
      context.go(completed ? Routes.dashboard : Routes.onboarding);
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() {
        _pairing = false;
        _error = _pairingMessage(error);
        _technical = error.technical;
      });
    }
  }

  /// Le Bridge indique si la configuration guidée a déjà été terminée.
  /// En cas de doute, l'onboarding est proposé : il ne casse rien.
  Future<bool> _onboardingCompleted() async {
    try {
      final ApiClient api = ref.read(apiClientProvider);
      final Map<String, dynamic> state = await api.getJson(Endpoints.onboardingState);
      return Json.flag(state['completed']);
    } on ApiException {
      return false;
    }
  }

  String _pairingMessage(ApiException error) {
    if (error.statusCode == 403 || error.kind == ApiErrorKind.forbidden) {
      return 'Code invalide ou expiré. Un code n\'est valable que 15 minutes et '
          'ne sert qu\'une fois : lancez .\\scripts\\pairing_code.ps1 sur '
          'l\'ordinateur pour en obtenir un nouveau.';
    }
    if (error.isOffline || error.kind == ApiErrorKind.timeout) {
      return 'Bridge injoignable à cette adresse. Vérifiez que le Bridge est '
          'démarré et que le téléphone est sur le même réseau.';
    }
    return error.message;
  }

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    final bool busy = _testing || _pairing;

    return Scaffold(
      appBar: AppBar(title: const Text('Appairer le Bridge')),
      body: SafeArea(
        child: ListView(
          padding: AppSpacing.page,
          children: <Widget>[
            Text(
              'Reliez ce téléphone au Bridge installé sur votre ordinateur.',
              style: theme.textTheme.bodyLarge,
            ),
            const SizedBox(height: AppSpacing.xs),
            Text(
              'Tant que l\'appairage n\'est pas fait, aucune donnée de trading '
              'n\'est accessible depuis l\'application.',
              style: theme.textTheme.bodySmall,
            ),
            const SizedBox(height: AppSpacing.xl),
            _AddressSection(
              controller: _address,
              enabled: !busy,
              testing: _testing,
              result: _test,
              onTest: _testAddress,
            ),
            const SizedBox(height: AppSpacing.xl),
            const SectionHeader(
              title: 'Code d\'appairage',
              subtitle: 'Huit caractères affichés par le Bridge, au format XXXX-XXXX.',
            ),
            PairingCodeField(
              controller: _code,
              enabled: !busy,
              onSubmitted: _pair,
            ),
            const SizedBox(height: AppSpacing.md),
            const _WhereIsTheCodeCard(),
            if (_error != null) ...<Widget>[
              const SizedBox(height: AppSpacing.lg),
              ErrorView(message: _error!, technical: _technical),
            ],
            const SizedBox(height: AppSpacing.xl),
            FilledButton.icon(
              onPressed: _canPair ? _pair : null,
              icon: _pairing
                  ? const SizedBox(
                      width: 16,
                      height: 16,
                      child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white),
                    )
                  : const Icon(Icons.link, size: 18),
              label: Text(_pairing ? 'Appairage en cours…' : 'Appairer'),
            ),
            const SizedBox(height: AppSpacing.lg),
          ],
        ),
      ),
    );
  }
}

/// Saisie de l'adresse du Bridge et test de joignabilité.
class _AddressSection extends StatelessWidget {
  const _AddressSection({
    required this.controller,
    required this.enabled,
    required this.testing,
    required this.result,
    required this.onTest,
  });

  final TextEditingController controller;
  final bool enabled;
  final bool testing;
  final _AddressTest result;
  final VoidCallback onTest;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        const SectionHeader(
          title: 'Adresse du Bridge',
          subtitle: 'Adresse locale (192.168.1.20:8787) ou adresse publique '
              '(https://mon-domaine.ngrok-free.app).',
        ),
        TextField(
          controller: controller,
          enabled: enabled,
          autocorrect: false,
          enableSuggestions: false,
          keyboardType: TextInputType.url,
          textInputAction: TextInputAction.next,
          decoration: const InputDecoration(
            labelText: 'Adresse',
            hintText: '192.168.1.20:8787',
            prefixIcon: Icon(Icons.dns_outlined),
          ),
        ),
        const SizedBox(height: AppSpacing.md),
        Row(
          children: <Widget>[
            OutlinedButton.icon(
              onPressed: enabled && controller.text.trim().isNotEmpty ? onTest : null,
              icon: testing
                  ? const SizedBox(
                      width: 16,
                      height: 16,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  : const Icon(Icons.wifi_tethering, size: 18),
              label: Text(testing ? 'Test en cours…' : 'Tester la connexion'),
            ),
            const SizedBox(width: AppSpacing.md),
            Expanded(child: _testFeedback(theme)),
          ],
        ),
      ],
    );
  }

  Widget _testFeedback(ThemeData theme) {
    return switch (result) {
      _AddressTest.untested => const SizedBox.shrink(),
      _AddressTest.reachable => const StatusChip(
          label: 'Bridge joignable',
          tone: StatusTone.good,
          icon: Icons.check_circle_outline,
          dense: true,
        ),
      _AddressTest.unreachable => Text(
          'Aucune réponse à cette adresse.',
          style: theme.textTheme.bodySmall?.copyWith(color: AppColors.loss),
        ),
    };
  }
}

/// Explique où lire le code d'appairage, en clair et sans jargon.
class _WhereIsTheCodeCard extends StatelessWidget {
  const _WhereIsTheCodeCard();

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Row(
            children: <Widget>[
              const Icon(Icons.help_outline, size: 18, color: AppColors.primary),
              const SizedBox(width: AppSpacing.sm),
              Text('Où trouver ce code ?', style: theme.textTheme.titleMedium),
            ],
          ),
          const SizedBox(height: AppSpacing.md),
          Text(
            'Le code s\'affiche dans la console du Bridge au démarrage, sur '
            'l\'ordinateur qui exécute MetaTrader 5.',
            style: theme.textTheme.bodyMedium,
          ),
          const SizedBox(height: AppSpacing.sm),
          Text(
            'Il reste valable 15 minutes et ne sert qu\'une fois. Pour en '
            'obtenir un nouveau sans redémarrer le Bridge, lancez '
            '.\\scripts\\pairing_code.ps1 sur l\'ordinateur.',
            style: theme.textTheme.bodySmall,
          ),
        ],
      ),
    );
  }
}
