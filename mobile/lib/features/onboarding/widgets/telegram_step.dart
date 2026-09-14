import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/theme/app_colors.dart';
import '../../../core/theme/app_theme.dart';
import '../../../core/widgets/app_widgets.dart';
import '../../bridge/models/bridge_json.dart';
import '../providers/onboarding_providers.dart';
import 'onboarding_step.dart';

/// Étape 4 : connexion réelle du compte Telegram.
///
/// L'api_id, l'api_hash, le code et le mot de passe 2FA ne sont jamais
/// enregistrés sur le téléphone : ils sont transmis au Bridge puis effacés des
/// champs de saisie. L'api_hash, le code et le mot de passe restent masqués.
class TelegramStep extends ConsumerStatefulWidget {
  const TelegramStep({super.key, required this.payload});

  final Map<String, dynamic> payload;

  @override
  ConsumerState<TelegramStep> createState() => _TelegramStepState();
}

class _TelegramStepState extends ConsumerState<TelegramStep> {
  final TextEditingController _apiId = TextEditingController();
  final TextEditingController _apiHash = TextEditingController();
  final TextEditingController _phone = TextEditingController();
  final TextEditingController _code = TextEditingController();
  final TextEditingController _password = TextEditingController();

  @override
  void dispose() {
    _apiId.dispose();
    _apiHash.dispose();
    _phone.dispose();
    _code.dispose();
    _password.dispose();
    super.dispose();
  }

  /// Efface immédiatement les secrets saisis après leur envoi au Bridge.
  void _clearSecrets() {
    _apiHash.clear();
    _code.clear();
    _password.clear();
  }

  Future<void> _start() async {
    FocusScope.of(context).unfocus();
    await ref.read(telegramLoginProvider.notifier).start(
          apiId: _apiId.text,
          apiHash: _apiHash.text,
          phone: _phone.text,
        );
    if (!mounted) return;
    _clearSecrets();
  }

  Future<void> _submitCode() async {
    FocusScope.of(context).unfocus();
    await ref.read(telegramLoginProvider.notifier).submitCode(_code.text);
    _afterAttempt();
  }

  Future<void> _submitPassword() async {
    FocusScope.of(context).unfocus();
    await ref.read(telegramLoginProvider.notifier).submitPassword(_password.text);
    _afterAttempt();
  }

  void _afterAttempt() {
    if (!mounted) return;
    _clearSecrets();
    if (ref.read(telegramLoginProvider).phase == TelegramLoginPhase.connected) {
      ref.invalidate(onboardingStateProvider);
    }
  }

  @override
  Widget build(BuildContext context) {
    final TelegramLoginState login = ref.watch(telegramLoginProvider);
    final Map<String, dynamic> step = OnboardingStep.stepByKey(widget.payload, 'telegram');
    final bool alreadyConnected = Json.flag(step['done']);

    return OnboardingStep(
      title: 'Connexion Telegram',
      intro: 'TradePilot lit les canaux de signaux avec votre propre compte '
          'Telegram. La session reste sur le Bridge, jamais sur le téléphone.',
      done: alreadyConnected,
      children: <Widget>[
        if (alreadyConnected && login.phase != TelegramLoginPhase.connected)
          const _ConnectedCard(message: 'Un compte Telegram est déjà connecté au Bridge.')
        else if (login.phase == TelegramLoginPhase.connected)
          _ConnectedCard(message: 'Compte connecté : ${login.account ?? 'compte Telegram'}.')
        else ...<Widget>[
          const _CredentialsHelpCard(),
          const SizedBox(height: AppSpacing.lg),
          _buildPhase(login),
        ],
        if (login.error != null) ...<Widget>[
          const SizedBox(height: AppSpacing.lg),
          ErrorView(message: login.error!, technical: login.technical),
        ],
      ],
    );
  }

  Widget _buildPhase(TelegramLoginState login) {
    return switch (login.phase) {
      TelegramLoginPhase.idle => _startForm(login),
      TelegramLoginPhase.awaitingCode => _codeForm(login),
      TelegramLoginPhase.awaitingPassword => _passwordForm(login),
      TelegramLoginPhase.connected => const SizedBox.shrink(),
    };
  }

  Widget _startForm(TelegramLoginState login) {
    final Map<String, dynamic> defaults =
        (widget.payload['envDefaults'] as Map<String, dynamic>?) ?? <String, dynamic>{};
    final bool hasEnvDefaults = defaults['apiId'] != null &&
        defaults['phone'] != null &&
        defaults['apiHashAvailable'] == true;

    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          if (hasEnvDefaults) ...<Widget>[
            // Les identifiants sont deja dans bridge/.env : inutile de les
            // retaper sur le telephone, le Bridge les complete lui-meme.
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: <Widget>[
                const Icon(Icons.check_circle_outline, size: 18, color: AppColors.profit),
                const SizedBox(width: AppSpacing.sm),
                Expanded(
                  child: Text(
                    'Identifiants déjà configurés sur l\'ordinateur '
                    '(API ID ${defaults['apiId']}, ${defaults['phone']}). '
                    'Laissez les champs vides et touchez « Recevoir le code ».',
                    style: Theme.of(context).textTheme.bodySmall,
                  ),
                ),
              ],
            ),
            const SizedBox(height: AppSpacing.md),
          ],
          TextField(
            controller: _apiId,
            enabled: !login.busy,
            keyboardType: TextInputType.number,
            decoration: const InputDecoration(
              labelText: 'API ID',
              hintText: '1234567',
              prefixIcon: Icon(Icons.tag),
            ),
          ),
          const SizedBox(height: AppSpacing.md),
          TextField(
            controller: _apiHash,
            enabled: !login.busy,
            obscureText: true,
            autocorrect: false,
            enableSuggestions: false,
            decoration: const InputDecoration(
              labelText: 'API Hash',
              prefixIcon: Icon(Icons.password_outlined),
            ),
          ),
          const SizedBox(height: AppSpacing.md),
          TextField(
            controller: _phone,
            enabled: !login.busy,
            keyboardType: TextInputType.phone,
            decoration: const InputDecoration(
              labelText: 'Numéro de téléphone',
              hintText: '+33612345678',
              prefixIcon: Icon(Icons.phone_outlined),
            ),
          ),
          const SizedBox(height: AppSpacing.lg),
          SizedBox(
            width: double.infinity,
            child: FilledButton(
              onPressed: login.busy ? null : _start,
              child: Text(login.busy ? 'Envoi en cours…' : 'Recevoir le code'),
            ),
          ),
        ],
      ),
    );
  }

  Widget _codeForm(TelegramLoginState login) {
    return _SecretForm(
      title: 'Code reçu par Telegram',
      description: 'Telegram vient d\'envoyer un code dans votre application. '
          'Saisissez-le ci-dessous.',
      controller: _code,
      label: 'Code de connexion',
      icon: Icons.sms_outlined,
      keyboardType: TextInputType.number,
      busy: login.busy,
      submitLabel: 'Valider le code',
      onSubmit: _submitCode,
      onRestart: () => ref.read(telegramLoginProvider.notifier).reset(),
    );
  }

  Widget _passwordForm(TelegramLoginState login) {
    return _SecretForm(
      title: 'Vérification en deux étapes',
      description: 'Ce compte est protégé par un mot de passe 2FA. '
          'Il est transmis au Bridge et n\'est jamais conservé ici.',
      controller: _password,
      label: 'Mot de passe 2FA',
      icon: Icons.lock_outline,
      keyboardType: TextInputType.text,
      busy: login.busy,
      submitLabel: 'Valider le mot de passe',
      onSubmit: _submitPassword,
      onRestart: () => ref.read(telegramLoginProvider.notifier).reset(),
    );
  }
}

/// Formulaire d'une valeur secrète : saisie masquée et envoi unique.
class _SecretForm extends StatelessWidget {
  const _SecretForm({
    required this.title,
    required this.description,
    required this.controller,
    required this.label,
    required this.icon,
    required this.keyboardType,
    required this.busy,
    required this.submitLabel,
    required this.onSubmit,
    required this.onRestart,
  });

  final String title;
  final String description;
  final TextEditingController controller;
  final String label;
  final IconData icon;
  final TextInputType keyboardType;
  final bool busy;
  final String submitLabel;
  final VoidCallback onSubmit;
  final VoidCallback onRestart;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Text(title, style: theme.textTheme.titleMedium),
          const SizedBox(height: AppSpacing.sm),
          Text(description, style: theme.textTheme.bodySmall),
          const SizedBox(height: AppSpacing.lg),
          TextField(
            controller: controller,
            enabled: !busy,
            obscureText: true,
            autocorrect: false,
            enableSuggestions: false,
            keyboardType: keyboardType,
            decoration: InputDecoration(labelText: label, prefixIcon: Icon(icon)),
          ),
          const SizedBox(height: AppSpacing.lg),
          SizedBox(
            width: double.infinity,
            child: FilledButton(
              onPressed: busy ? null : onSubmit,
              child: Text(busy ? 'Vérification…' : submitLabel),
            ),
          ),
          const SizedBox(height: AppSpacing.sm),
          TextButton(
            onPressed: busy ? null : onRestart,
            child: const Text('Recommencer la connexion'),
          ),
        ],
      ),
    );
  }
}

/// Explique où obtenir l'API ID et l'API Hash.
class _CredentialsHelpCard extends StatelessWidget {
  const _CredentialsHelpCard();

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Text('Où trouver ces identifiants ?', style: theme.textTheme.titleMedium),
          const SizedBox(height: AppSpacing.md),
          const OnboardingBullet(
            icon: Icons.looks_one_outlined,
            text: 'Ouvrez https://my.telegram.org depuis un navigateur et '
                'connectez-vous avec votre numéro.',
          ),
          const OnboardingBullet(
            icon: Icons.looks_two_outlined,
            text: 'Choisissez « API development tools » et créez une application.',
          ),
          const OnboardingBullet(
            icon: Icons.looks_3_outlined,
            text: 'Recopiez « App api_id » et « App api_hash » ci-dessous.',
          ),
          Text(
            'Ces valeurs sont envoyées au Bridge pour ouvrir la session, puis '
            'effacées de l\'application. Elles ne sont jamais stockées sur le '
            'téléphone ni réaffichées.',
            style: theme.textTheme.bodySmall,
          ),
        ],
      ),
    );
  }
}

/// Confirmation visuelle qu'un compte est bien relié.
class _ConnectedCard extends StatelessWidget {
  const _ConnectedCard({required this.message});

  final String message;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    return AppCard(
      child: Row(
        children: <Widget>[
          const StatusChip(
            label: 'Connecté',
            tone: StatusTone.good,
            icon: Icons.check_circle_outline,
            dense: true,
          ),
          const SizedBox(width: AppSpacing.md),
          Expanded(child: Text(message, style: theme.textTheme.bodyMedium)),
        ],
      ),
    );
  }
}
