import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../../core/theme/app_colors.dart';
import '../../../core/theme/app_theme.dart';

/// Heure au format `HH:MM`, saisie via l'horloge du système.
class RiskTimeField extends StatelessWidget {
  const RiskTimeField({
    super.key,
    required this.label,
    required this.description,
    required this.value,
    required this.onChanged,
  });

  final String label;
  final String description;
  final String? value;
  final ValueChanged<String> onChanged;

  static TimeOfDay _parse(String? raw) {
    final List<String> parts = (raw ?? '').split(':');
    if (parts.length != 2) return const TimeOfDay(hour: 0, minute: 0);
    return TimeOfDay(
      hour: int.tryParse(parts.first) ?? 0,
      minute: int.tryParse(parts.last) ?? 0,
    );
  }

  static String _format(TimeOfDay time) =>
      '${time.hour.toString().padLeft(2, '0')}:${time.minute.toString().padLeft(2, '0')}';

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: AppSpacing.xs),
      child: ListTile(
        contentPadding: EdgeInsets.zero,
        title: Text(label, style: theme.textTheme.titleMedium),
        subtitle: Text(description, style: theme.textTheme.bodySmall),
        trailing: Text(
          value ?? '--',
          style: theme.textTheme.titleMedium?.copyWith(color: AppColors.primary),
        ),
        onTap: () async {
          final TimeOfDay? picked = await showTimePicker(
            context: context,
            initialTime: _parse(value),
          );
          if (picked != null) onChanged(_format(picked));
        },
      ),
    );
  }
}

/// Jours autorisés : 0 = lundi … 6 = dimanche, comme attendu par le Bridge.
class RiskDaysField extends StatelessWidget {
  const RiskDaysField({super.key, required this.selected, required this.onChanged});

  static const List<String> _labels = <String>[
    'Lundi',
    'Mardi',
    'Mercredi',
    'Jeudi',
    'Vendredi',
    'Samedi',
    'Dimanche',
  ];

  final List<int> selected;
  final ValueChanged<List<int>> onChanged;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: AppSpacing.sm),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Text('Jours autorisés', style: theme.textTheme.titleMedium),
          const SizedBox(height: 2),
          Text(
            'Un signal reçu un jour non coché est refusé. Le week-end reste décoché tant que '
            'le marché est fermé.',
            style: theme.textTheme.bodySmall,
          ),
          const SizedBox(height: AppSpacing.sm),
          Wrap(
            spacing: AppSpacing.sm,
            runSpacing: AppSpacing.sm,
            children: <Widget>[
              for (int day = 0; day < _labels.length; day++)
                FilterChip(
                  label: Text(_labels[day]),
                  selected: selected.contains(day),
                  onSelected: (bool value) {
                    final List<int> updated = List<int>.from(selected);
                    if (value) {
                      if (!updated.contains(day)) updated.add(day);
                    } else {
                      updated.remove(day);
                    }
                    updated.sort();
                    onChanged(updated);
                  },
                ),
            ],
          ),
        ],
      ),
    );
  }
}

/// Instruments autorisés. Une liste vide signifie « tous les instruments ».
class RiskSymbolsField extends StatefulWidget {
  const RiskSymbolsField({super.key, required this.symbols, required this.onChanged});

  final List<String> symbols;
  final ValueChanged<List<String>> onChanged;

  @override
  State<RiskSymbolsField> createState() => _RiskSymbolsFieldState();
}

class _RiskSymbolsFieldState extends State<RiskSymbolsField> {
  final TextEditingController _controller = TextEditingController();

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  void _add() {
    final String value = _controller.text.trim().toUpperCase();
    if (value.isEmpty || widget.symbols.contains(value)) {
      _controller.clear();
      return;
    }
    widget.onChanged(<String>[...widget.symbols, value]);
    _controller.clear();
  }

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: AppSpacing.sm),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Text('Instruments autorisés', style: theme.textTheme.titleMedium),
          const SizedBox(height: 2),
          Text(
            'Seuls ces instruments peuvent être tradés. Laisser la liste vide autorise tous les '
            'instruments reconnus par le broker.',
            style: theme.textTheme.bodySmall,
          ),
          const SizedBox(height: AppSpacing.sm),
          if (widget.symbols.isEmpty)
            Text('Aucune restriction : tous les instruments sont autorisés.',
                style: theme.textTheme.bodySmall)
          else
            Wrap(
              spacing: AppSpacing.sm,
              runSpacing: AppSpacing.sm,
              children: <Widget>[
                for (final String symbol in widget.symbols)
                  InputChip(
                    label: Text(symbol),
                    onDeleted: () => widget.onChanged(
                      widget.symbols.where((String item) => item != symbol).toList(),
                    ),
                  ),
              ],
            ),
          const SizedBox(height: AppSpacing.sm),
          Row(
            children: <Widget>[
              Expanded(
                child: TextField(
                  controller: _controller,
                  textCapitalization: TextCapitalization.characters,
                  decoration: const InputDecoration(hintText: 'Par exemple XAUUSD'),
                  onSubmitted: (_) => _add(),
                ),
              ),
              const SizedBox(width: AppSpacing.sm),
              OutlinedButton(onPressed: _add, child: const Text('Ajouter')),
            ],
          ),
        ],
      ),
    );
  }
}

/// Répartition du volume entre les take profits, en pourcentage.
class RiskRatiosField extends StatefulWidget {
  const RiskRatiosField({super.key, required this.ratios, required this.onChanged});

  final List<double> ratios;
  final ValueChanged<List<double>> onChanged;

  @override
  State<RiskRatiosField> createState() => _RiskRatiosFieldState();
}

class _RiskRatiosFieldState extends State<RiskRatiosField> {
  late final TextEditingController _controller = TextEditingController(
    text: widget.ratios.map((double value) => value.toStringAsFixed(0)).join(' / '),
  );

  List<double> _parse(String raw) {
    return raw
        .split(RegExp(r'[^0-9.,]+'))
        .map((String part) => double.tryParse(part.replaceAll(',', '.')))
        .whereType<double>()
        .where((double value) => value > 0)
        .toList(growable: false);
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    final List<double> parsed = _parse(_controller.text);
    final double total = parsed.fold<double>(0, (double sum, double value) => sum + value);

    return Padding(
      padding: const EdgeInsets.symmetric(vertical: AppSpacing.sm),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Text('Répartition entre les objectifs', style: theme.textTheme.titleMedium),
          const SizedBox(height: 2),
          Text(
            'Part du volume affectée à chaque take profit, dans l\'ordre TP1, TP2, TP3. '
            'Séparez les valeurs par une barre oblique.',
            style: theme.textTheme.bodySmall,
          ),
          const SizedBox(height: AppSpacing.sm),
          TextField(
            controller: _controller,
            keyboardType: const TextInputType.numberWithOptions(decimal: true),
            inputFormatters: <TextInputFormatter>[
              FilteringTextInputFormatter.allow(RegExp(r'[0-9./, ]')),
            ],
            decoration: const InputDecoration(hintText: '40 / 30 / 30', suffixText: '%'),
            onChanged: (String raw) {
              setState(() {});
              widget.onChanged(_parse(raw));
            },
          ),
          const SizedBox(height: AppSpacing.xs),
          Text(
            parsed.isEmpty
                ? 'Aucune répartition saisie : le Bridge conservera la répartition actuelle.'
                : 'Total : ${total.toStringAsFixed(0)} %'
                    '${(total - 100).abs() < 0.01 ? '' : ' — la somme devrait faire 100 %.'}',
            style: theme.textTheme.bodySmall?.copyWith(
              color: parsed.isNotEmpty && (total - 100).abs() >= 0.01 ? AppColors.warning : null,
            ),
          ),
        ],
      ),
    );
  }
}
