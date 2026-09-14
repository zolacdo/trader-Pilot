import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../../core/theme/app_colors.dart';
import '../../../core/theme/app_theme.dart';
import '../../../core/widgets/app_widgets.dart';

/// Bloc thématique du formulaire de risque.
class RiskSection extends StatelessWidget {
  const RiskSection({
    super.key,
    required this.title,
    required this.subtitle,
    required this.children,
  });

  final String title;
  final String subtitle;
  final List<Widget> children;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: AppSpacing.lg),
      child: AppCard(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: <Widget>[
            SectionHeader(title: title, subtitle: subtitle),
            ...children,
          ],
        ),
      ),
    );
  }
}

/// Paragraphe d'explication ou d'avertissement à l'intérieur d'une section.
class RiskNote extends StatelessWidget {
  const RiskNote({super.key, required this.text, this.warning = false});

  final String text;
  final bool warning;

  @override
  Widget build(BuildContext context) {
    final bool dark = Theme.of(context).brightness == Brightness.dark;
    return Container(
      width: double.infinity,
      margin: const EdgeInsets.only(top: AppSpacing.sm, bottom: AppSpacing.sm),
      padding: const EdgeInsets.all(AppSpacing.md),
      decoration: BoxDecoration(
        color: warning
            ? (dark ? AppColors.warning.withValues(alpha: 0.14) : AppColors.warningSurface)
            : (dark ? AppColors.surfaceMutedDark : AppColors.surfaceMuted),
        borderRadius: BorderRadius.circular(AppSpacing.radiusSmall),
      ),
      child: Text(
        text,
        style: Theme.of(context).textTheme.bodySmall?.copyWith(
              color: warning
                  ? (dark ? const Color(0xFFFBBF24) : AppColors.warning)
                  : (dark ? AppColors.textSecondaryDark : AppColors.textSecondary),
            ),
      ),
    );
  }
}

/// Champ numérique accompagné de l'explication de ce qu'il protège.
class RiskNumberField extends StatefulWidget {
  const RiskNumberField({
    super.key,
    required this.label,
    required this.description,
    required this.value,
    required this.onChanged,
    this.suffix,
    this.decimal = true,
    this.example,
    this.enabled = true,
  });

  final String label;
  final String description;
  final num? value;
  final ValueChanged<num?> onChanged;
  final String? suffix;
  final bool decimal;

  /// Exemple chiffré affiché sous le champ.
  final String? example;
  final bool enabled;

  @override
  State<RiskNumberField> createState() => _RiskNumberFieldState();
}

class _RiskNumberFieldState extends State<RiskNumberField> {
  late final TextEditingController _controller = TextEditingController(text: _format(widget.value));

  String _format(num? value) {
    if (value == null) return '';
    if (!widget.decimal) return value.toInt().toString();
    final double asDouble = value.toDouble();
    return asDouble == asDouble.roundToDouble()
        ? asDouble.toStringAsFixed(asDouble.abs() >= 1000 ? 0 : 2)
        : asDouble.toString();
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  void _emit(String raw) {
    final String cleaned = raw.trim().replaceAll(',', '.');
    if (cleaned.isEmpty) {
      widget.onChanged(null);
      return;
    }
    final num? parsed = widget.decimal ? double.tryParse(cleaned) : int.tryParse(cleaned);
    widget.onChanged(parsed);
  }

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: AppSpacing.sm),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Text(widget.label, style: theme.textTheme.titleMedium),
          const SizedBox(height: 2),
          Text(widget.description, style: theme.textTheme.bodySmall),
          const SizedBox(height: AppSpacing.sm),
          TextField(
            controller: _controller,
            enabled: widget.enabled,
            keyboardType: TextInputType.numberWithOptions(decimal: widget.decimal),
            inputFormatters: <TextInputFormatter>[
              if (widget.decimal)
                FilteringTextInputFormatter.allow(RegExp(r'[0-9.,]'))
              else
                FilteringTextInputFormatter.digitsOnly,
            ],
            decoration: InputDecoration(suffixText: widget.suffix),
            onChanged: _emit,
          ),
          if (widget.example != null) ...<Widget>[
            const SizedBox(height: AppSpacing.sm),
            Text(
              widget.example!,
              style: theme.textTheme.bodySmall?.copyWith(
                color: AppColors.primary,
                fontWeight: FontWeight.w600,
              ),
            ),
          ],
        ],
      ),
    );
  }
}

/// Interrupteur avec explication.
class RiskSwitchField extends StatelessWidget {
  const RiskSwitchField({
    super.key,
    required this.label,
    required this.description,
    required this.value,
    required this.onChanged,
  });

  final String label;
  final String description;
  final bool value;
  final ValueChanged<bool> onChanged;

  @override
  Widget build(BuildContext context) {
    return SwitchListTile(
      contentPadding: EdgeInsets.zero,
      value: value,
      onChanged: onChanged,
      title: Text(label, style: Theme.of(context).textTheme.titleMedium),
      subtitle: Text(description, style: Theme.of(context).textTheme.bodySmall),
    );
  }
}

/// Option d'un choix exclusif.
class RiskOption<T> {
  const RiskOption({required this.value, required this.label, required this.description});

  final T value;
  final String label;
  final String description;
}

/// Choix exclusif présenté comme une liste d'options expliquées.
class RiskChoiceField<T> extends StatelessWidget {
  const RiskChoiceField({
    super.key,
    required this.label,
    required this.description,
    required this.options,
    required this.selected,
    required this.onChanged,
  });

  final String label;
  final String description;
  final List<RiskOption<T>> options;
  final T? selected;
  final ValueChanged<T> onChanged;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: AppSpacing.sm),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Text(label, style: theme.textTheme.titleMedium),
          const SizedBox(height: 2),
          Text(description, style: theme.textTheme.bodySmall),
          const SizedBox(height: AppSpacing.sm),
          for (final RiskOption<T> option in options)
            Padding(
              padding: const EdgeInsets.only(bottom: AppSpacing.sm),
              child: InkWell(
                borderRadius: BorderRadius.circular(AppSpacing.radiusSmall),
                onTap: () => onChanged(option.value),
                child: Container(
                  padding: const EdgeInsets.all(AppSpacing.md),
                  decoration: BoxDecoration(
                    borderRadius: BorderRadius.circular(AppSpacing.radiusSmall),
                    border: Border.all(
                      color: option.value == selected
                          ? AppColors.primary
                          : theme.colorScheme.outline,
                      width: option.value == selected ? 1.4 : 1,
                    ),
                  ),
                  child: Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: <Widget>[
                      Icon(
                        option.value == selected
                            ? Icons.radio_button_checked
                            : Icons.radio_button_unchecked,
                        size: 19,
                        color: option.value == selected
                            ? AppColors.primary
                            : AppColors.textTertiary,
                      ),
                      const SizedBox(width: AppSpacing.md),
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: <Widget>[
                            Text(
                              option.label,
                              style: theme.textTheme.bodyMedium
                                  ?.copyWith(fontWeight: FontWeight.w600),
                            ),
                            const SizedBox(height: 2),
                            Text(option.description, style: theme.textTheme.bodySmall),
                          ],
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ),
        ],
      ),
    );
  }
}
