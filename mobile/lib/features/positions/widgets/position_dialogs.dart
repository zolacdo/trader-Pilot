import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../../core/theme/app_colors.dart';
import '../../../core/theme/app_theme.dart';
import '../../../core/utils/formatters.dart';
import '../../../core/widgets/app_widgets.dart';
import '../trades_models.dart';

/// Choix de fermeture partielle : soit un pourcentage, soit un volume exact.
class PartialChoice {
  const PartialChoice({this.percentage, this.volume});

  final double? percentage;
  final double? volume;
}

/// Saisie d'une fermeture partielle, avec raccourcis 25 / 50 / 75 %.
class PartialCloseDialog extends StatefulWidget {
  const PartialCloseDialog({super.key, required this.position});

  final OpenPosition position;

  @override
  State<PartialCloseDialog> createState() => _PartialCloseDialogState();
}

class _PartialCloseDialogState extends State<PartialCloseDialog> {
  static const List<double> _shortcuts = <double>[25, 50, 75];

  double? _percentage = 50;
  final TextEditingController _volume = TextEditingController();

  @override
  void dispose() {
    _volume.dispose();
    super.dispose();
  }

  double? get _typedVolume => double.tryParse(_volume.text.trim().replaceAll(',', '.'));

  @override
  Widget build(BuildContext context) {
    final double? open = widget.position.volume;
    final bool canValidate = _percentage != null || (_typedVolume != null && _typedVolume! > 0);
    return AlertDialog(
      title: const Text('Fermer partiellement'),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Text('Volume ouvert : ${Fmt.lots(open)} lot',
              style: Theme.of(context).textTheme.bodySmall),
          const SizedBox(height: AppSpacing.md),
          Wrap(
            spacing: AppSpacing.sm,
            children: <Widget>[
              for (final double value in _shortcuts)
                ChoiceChip(
                  label: Text('${value.toStringAsFixed(0)} %'),
                  selected: _percentage == value,
                  onSelected: (bool selected) => setState(() {
                    _percentage = selected ? value : null;
                    if (selected) _volume.clear();
                  }),
                ),
            ],
          ),
          const SizedBox(height: AppSpacing.lg),
          Text('Ou un volume exact', style: Theme.of(context).textTheme.bodySmall),
          const SizedBox(height: AppSpacing.sm),
          TextField(
            controller: _volume,
            keyboardType: const TextInputType.numberWithOptions(decimal: true),
            inputFormatters: <TextInputFormatter>[
              FilteringTextInputFormatter.allow(RegExp(r'[0-9.,]')),
            ],
            decoration: const InputDecoration(hintText: 'Par exemple 0,05', suffixText: 'lot'),
            onChanged: (String value) => setState(() {
              if (value.trim().isNotEmpty) _percentage = null;
            }),
          ),
          const SizedBox(height: AppSpacing.sm),
          Text(
            'Si le volume demandé est inférieur au minimum du broker, le Bridge ferme la position '
            'entièrement.',
            style: Theme.of(context).textTheme.bodySmall,
          ),
        ],
      ),
      actions: <Widget>[
        TextButton(
          onPressed: () => Navigator.of(context).pop(),
          style: TextButton.styleFrom(foregroundColor: AppColors.textSecondary),
          child: const Text('Annuler'),
        ),
        FilledButton(
          onPressed: canValidate
              ? () => Navigator.of(context).pop(
                    _percentage != null
                        ? PartialChoice(percentage: _percentage)
                        : PartialChoice(volume: _typedVolume),
                  )
              : null,
          child: const Text('Continuer'),
        ),
      ],
    );
  }
}

/// Saisie d'un prix (stop loss ou take profit), avec les repères de la position.
class PriceDialog extends StatefulWidget {
  const PriceDialog({
    super.key,
    required this.title,
    required this.helper,
    required this.current,
    required this.openPrice,
    required this.currentPrice,
  });

  final String title;
  final String helper;
  final double? current;
  final double? openPrice;
  final double? currentPrice;

  @override
  State<PriceDialog> createState() => _PriceDialogState();
}

class _PriceDialogState extends State<PriceDialog> {
  late final TextEditingController _controller =
      TextEditingController(text: widget.current == null ? '' : Fmt.price(widget.current));

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  double? get _value => double.tryParse(_controller.text.trim().replaceAll(',', '.'));

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: Text(widget.title),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Text(widget.helper, style: Theme.of(context).textTheme.bodySmall),
          const SizedBox(height: AppSpacing.lg),
          TextField(
            controller: _controller,
            autofocus: true,
            keyboardType: const TextInputType.numberWithOptions(decimal: true),
            inputFormatters: <TextInputFormatter>[
              FilteringTextInputFormatter.allow(RegExp(r'[0-9.,]')),
            ],
            decoration: const InputDecoration(hintText: 'Prix'),
            onChanged: (_) => setState(() {}),
          ),
          const SizedBox(height: AppSpacing.md),
          DetailRow(label: 'Prix d\'entrée', value: Fmt.price(widget.openPrice), monospace: true),
          DetailRow(label: 'Prix actuel', value: Fmt.price(widget.currentPrice), monospace: true),
        ],
      ),
      actions: <Widget>[
        TextButton(
          onPressed: () => Navigator.of(context).pop(),
          style: TextButton.styleFrom(foregroundColor: AppColors.textSecondary),
          child: const Text('Annuler'),
        ),
        FilledButton(
          onPressed:
              (_value != null && _value! > 0) ? () => Navigator.of(context).pop(_value) : null,
          child: const Text('Continuer'),
        ),
      ],
    );
  }
}

/// Saisie de la marge appliquée lors d'une mise à break even.
class BreakEvenDialog extends StatefulWidget {
  const BreakEvenDialog({super.key});

  @override
  State<BreakEvenDialog> createState() => _BreakEvenDialogState();
}

class _BreakEvenDialogState extends State<BreakEvenDialog> {
  final TextEditingController _controller = TextEditingController(text: '0');

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  int? get _value => int.tryParse(_controller.text.trim());

  @override
  Widget build(BuildContext context) {
    final int? value = _value;
    return AlertDialog(
      title: const Text('Break even'),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Text(
            'Le stop loss est déplacé sur le prix d\'entrée. La marge en points laisse de quoi '
            'couvrir le spread et les frais : 0 place le stop exactement au prix d\'entrée.',
            style: Theme.of(context).textTheme.bodySmall,
          ),
          const SizedBox(height: AppSpacing.lg),
          TextField(
            controller: _controller,
            keyboardType: TextInputType.number,
            inputFormatters: <TextInputFormatter>[FilteringTextInputFormatter.digitsOnly],
            decoration: const InputDecoration(labelText: 'Marge', suffixText: 'points'),
            onChanged: (_) => setState(() {}),
          ),
        ],
      ),
      actions: <Widget>[
        TextButton(
          onPressed: () => Navigator.of(context).pop(),
          style: TextButton.styleFrom(foregroundColor: AppColors.textSecondary),
          child: const Text('Annuler'),
        ),
        FilledButton(
          onPressed: (value != null && value >= 0 && value <= 1000)
              ? () => Navigator.of(context).pop(value)
              : null,
          child: const Text('Continuer'),
        ),
      ],
    );
  }
}
