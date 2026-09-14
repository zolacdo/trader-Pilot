import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_exception.dart';
import '../../../core/theme/app_colors.dart';
import '../../../core/theme/app_theme.dart';
import '../../../core/widgets/app_widgets.dart';
import '../models/channel.dart';
import '../providers/channels_providers.dart';

/// Réglages propres à un canal (CDC section 15).
///
/// Un champ laissé vide signifie « utiliser le réglage global » : la valeur
/// envoyée au Bridge est alors `null`, jamais une valeur devinée.
class ChannelSettingsForm extends ConsumerStatefulWidget {
  const ChannelSettingsForm({
    super.key,
    required this.channelId,
    required this.channelTitle,
    required this.settings,
  });

  final int channelId;
  final String channelTitle;
  final ChannelSettings settings;

  @override
  ConsumerState<ChannelSettingsForm> createState() => _ChannelSettingsFormState();
}

class _ChannelSettingsFormState extends ConsumerState<ChannelSettingsForm> {
  final GlobalKey<FormState> _formKey = GlobalKey<FormState>();

  late final TextEditingController _risk;
  late final TextEditingController _maxPositions;
  late final TextEditingController _maxLot;
  late final TextEditingController _maxSpread;
  late final TextEditingController _maxAge;
  late final TextEditingController _minConfidence;
  late final TextEditingController _allowedSymbols;

  late bool _copyBuy;
  late bool _copySell;
  late bool? _requireStopLoss;
  late bool? _requireTakeProfit;
  late String? _multiTpStrategy;
  bool _saving = false;

  @override
  void initState() {
    super.initState();
    final ChannelSettings settings = widget.settings;
    _risk = TextEditingController(text: _text(settings.riskPercent));
    _maxPositions = TextEditingController(text: _text(settings.maxPositions));
    _maxLot = TextEditingController(text: _text(settings.maxLot));
    _maxSpread = TextEditingController(text: _text(settings.maxSpreadPoints));
    _maxAge = TextEditingController(text: _text(settings.maxSignalAgeSeconds));
    _minConfidence = TextEditingController(
      text: settings.minConfidence == null ? '' : _text(settings.minConfidence! * 100),
    );
    _allowedSymbols = TextEditingController(text: settings.allowedSymbols.join(', '));
    _copyBuy = settings.copyBuy;
    _copySell = settings.copySell;
    _requireStopLoss = settings.requireStopLoss;
    _requireTakeProfit = settings.requireTakeProfit;
    _multiTpStrategy = settings.multiTpStrategy;
  }

  @override
  void dispose() {
    _risk.dispose();
    _maxPositions.dispose();
    _maxLot.dispose();
    _maxSpread.dispose();
    _maxAge.dispose();
    _minConfidence.dispose();
    _allowedSymbols.dispose();
    super.dispose();
  }

  static String _text(num? value) {
    if (value == null) return '';
    final String raw = value.toString();
    return raw.endsWith('.0') ? raw.substring(0, raw.length - 2) : raw;
  }

  static double? _parse(TextEditingController controller) {
    final String raw = controller.text.trim().replaceAll(',', '.');
    if (raw.isEmpty) return null;
    return double.tryParse(raw);
  }

  /// Valide une borne. `null` (champ vide) est toujours accepté.
  String? _range(String? value, {required num min, required num max, bool integer = false}) {
    final String raw = (value ?? '').trim().replaceAll(',', '.');
    if (raw.isEmpty) return null;
    final double? parsed = double.tryParse(raw);
    if (parsed == null) return 'Nombre invalide';
    if (integer && parsed != parsed.roundToDouble()) return 'Nombre entier attendu';
    if (parsed < min || parsed > max) {
      return 'Valeur attendue entre ${_fr(min)} et ${_fr(max)}';
    }
    return null;
  }

  /// Nombre écrit à la française dans les messages de validation.
  static String _fr(num value) {
    final String raw = value.toString();
    return (raw.endsWith('.0') ? raw.substring(0, raw.length - 2) : raw).replaceAll('.', ',');
  }

  Future<void> _save() async {
    if (!(_formKey.currentState?.validate() ?? false)) return;
    setState(() => _saving = true);

    final double? confidence = _parse(_minConfidence);
    final String symbols = _allowedSymbols.text.trim();
    final Map<String, dynamic> changes = <String, dynamic>{
      'copyBuy': _copyBuy,
      'copySell': _copySell,
      'riskPercent': _parse(_risk),
      'maxPositions': _parse(_maxPositions)?.round(),
      'maxLot': _parse(_maxLot),
      'maxSpreadPoints': _parse(_maxSpread)?.round(),
      'maxSignalAgeSeconds': _parse(_maxAge)?.round(),
      'minConfidence': confidence == null ? null : confidence / 100,
      'requireStopLoss': _requireStopLoss,
      'requireTakeProfit': _requireTakeProfit,
      'multiTpStrategy': _multiTpStrategy,
      'allowedSymbols': symbols.isEmpty
          ? null
          : symbols
              .split(',')
              .map((String item) => item.trim().toUpperCase())
              .where((String item) => item.isNotEmpty)
              .toList(),
    };

    try {
      await ref.read(channelActionsProvider).updateSettings(widget.channelId, changes);
      if (!mounted) return;
      showToast(context, 'Réglages enregistrés pour « ${widget.channelTitle} ».');
    } on ApiException catch (error) {
      if (!mounted) return;
      showToast(context, error.message, error: true);
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    return AppCard(
      child: Form(
        key: _formKey,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: <Widget>[
            const SectionHeader(
              title: 'Réglages du canal',
              subtitle: 'Un champ laissé vide utilise le réglage global de l\'application.',
            ),
            SwitchListTile(
              value: _copyBuy,
              onChanged: (bool value) => setState(() => _copyBuy = value),
              contentPadding: EdgeInsets.zero,
              title: const Text('Copier les signaux BUY'),
            ),
            SwitchListTile(
              value: _copySell,
              onChanged: (bool value) => setState(() => _copySell = value),
              contentPadding: EdgeInsets.zero,
              title: const Text('Copier les signaux SELL'),
            ),
            const Divider(height: AppSpacing.xl),
            _NumberField(
              controller: _risk,
              label: 'Risque par trade (%)',
              helper: 'Entre 0,01 et 10. Vide : risque global.',
              validator: (String? value) => _range(value, min: 0.01, max: 10),
            ),
            _NumberField(
              controller: _maxPositions,
              label: 'Positions simultanées maximum',
              helper: 'Entre 1 et 50. Vide : limite globale.',
              integer: true,
              validator: (String? value) => _range(value, min: 1, max: 50, integer: true),
            ),
            _NumberField(
              controller: _maxLot,
              label: 'Lot maximum',
              helper: 'Jusqu\'à 100. Vide : limite globale.',
              validator: (String? value) => _range(value, min: 0.01, max: 100),
            ),
            _NumberField(
              controller: _maxSpread,
              label: 'Spread maximum (points)',
              helper: 'Entre 0 et 1000. Vide : limite globale.',
              integer: true,
              validator: (String? value) => _range(value, min: 0, max: 1000, integer: true),
            ),
            _NumberField(
              controller: _maxAge,
              label: 'Âge maximum d\'un signal (secondes)',
              helper: 'Entre 10 et 86 400. Vide : durée globale.',
              integer: true,
              validator: (String? value) => _range(value, min: 10, max: 86400, integer: true),
            ),
            _NumberField(
              controller: _minConfidence,
              label: 'Score de confiance minimum (%)',
              helper: 'Entre 0 et 100. Vide : seuil global.',
              validator: (String? value) => _range(value, min: 0, max: 100),
            ),
            const Divider(height: AppSpacing.xl),
            _TriStateRow(
              label: 'Stop loss obligatoire',
              value: _requireStopLoss,
              onChanged: (bool? value) => setState(() => _requireStopLoss = value),
            ),
            _TriStateRow(
              label: 'Take profit obligatoire',
              value: _requireTakeProfit,
              onChanged: (bool? value) => setState(() => _requireTakeProfit = value),
            ),
            const SizedBox(height: AppSpacing.md),
            DropdownButtonFormField<String?>(
              initialValue: _multiTpStrategy,
              isExpanded: true,
              decoration: const InputDecoration(
                labelText: 'Stratégie de TP multiples',
                helperText: 'Non défini : stratégie globale.',
              ),
              items: <DropdownMenuItem<String?>>[
                const DropdownMenuItem<String?>(value: null, child: Text('Réglage global')),
                for (final String code in const <String>[
                  'FIRST_TP_ONLY',
                  'SPLIT_POSITIONS',
                  'PARTIAL_CLOSE',
                  'LAST_TP_ONLY',
                ])
                  DropdownMenuItem<String?>(value: code, child: Text(multiTpStrategyLabel(code))),
              ],
              onChanged: (String? value) => setState(() => _multiTpStrategy = value),
            ),
            const SizedBox(height: AppSpacing.lg),
            TextFormField(
              controller: _allowedSymbols,
              textCapitalization: TextCapitalization.characters,
              decoration: const InputDecoration(
                labelText: 'Instruments autorisés',
                hintText: 'XAUUSD, EURUSD',
                helperText: 'Séparés par des virgules. Vide : tous les instruments autorisés '
                    'par les réglages globaux.',
                helperMaxLines: 3,
              ),
            ),
            const SizedBox(height: AppSpacing.lg),
            Text(
              'Les protections globales du Bridge s\'appliquent toujours, même en mode '
              'automatique : ces réglages ne peuvent que les restreindre.',
              style: theme.textTheme.bodySmall,
            ),
            const SizedBox(height: AppSpacing.md),
            SizedBox(
              width: double.infinity,
              child: FilledButton(
                onPressed: _saving ? null : _save,
                child: Text(_saving ? 'Enregistrement…' : 'Enregistrer les réglages'),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _NumberField extends StatelessWidget {
  const _NumberField({
    required this.controller,
    required this.label,
    required this.helper,
    required this.validator,
    this.integer = false,
  });

  final TextEditingController controller;
  final String label;
  final String helper;
  final FormFieldValidator<String> validator;
  final bool integer;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: AppSpacing.lg),
      child: TextFormField(
        controller: controller,
        validator: validator,
        keyboardType: TextInputType.numberWithOptions(decimal: !integer),
        inputFormatters: <TextInputFormatter>[
          FilteringTextInputFormatter.allow(integer ? RegExp(r'[0-9]') : RegExp(r'[0-9.,]')),
        ],
        decoration: InputDecoration(
          labelText: label,
          helperText: helper,
          helperMaxLines: 2,
          hintText: 'Réglage global',
        ),
      ),
    );
  }
}

/// Trois états : réglage global, oui, non.
class _TriStateRow extends StatelessWidget {
  const _TriStateRow({required this.label, required this.value, required this.onChanged});

  final String label;
  final bool? value;
  final ValueChanged<bool?> onChanged;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.only(bottom: AppSpacing.md),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Text(label, style: theme.textTheme.bodyMedium),
          const SizedBox(height: AppSpacing.sm),
          Wrap(
            spacing: AppSpacing.sm,
            children: <Widget>[
              for (final ({bool? value, String label}) option in const <({bool? value, String label})>[
                (value: null, label: 'Réglage global'),
                (value: true, label: 'Oui'),
                (value: false, label: 'Non'),
              ])
                ChoiceChip(
                  label: Text(option.label),
                  selected: value == option.value,
                  showCheckmark: false,
                  selectedColor: AppColors.primarySurface,
                  onSelected: (_) => onChanged(option.value),
                ),
            ],
          ),
        ],
      ),
    );
  }
}
