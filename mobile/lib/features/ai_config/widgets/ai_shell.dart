import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../../core/theme/app_colors.dart';
import '../../../core/theme/app_theme.dart';
import '../../../core/widgets/app_widgets.dart';

/// Bloc thématique de l'écran IA : titre, phrase d'explication, contenu.
class AiSection extends StatelessWidget {
  const AiSection({
    super.key,
    required this.title,
    required this.subtitle,
    required this.children,
    this.action,
    this.accent = false,
  });

  final String title;
  final String subtitle;
  final List<Widget> children;
  final Widget? action;
  final bool accent;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: AppSpacing.lg),
      child: AppCard(
        accent: accent,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: <Widget>[
            SectionHeader(title: title, subtitle: subtitle, action: action),
            ...children,
          ],
        ),
      ),
    );
  }
}

/// Encadré explicatif ou avertissement.
class AiNote extends StatelessWidget {
  const AiNote({super.key, required this.text, this.warning = false});

  final String text;
  final bool warning;

  @override
  Widget build(BuildContext context) {
    final bool dark = Theme.of(context).brightness == Brightness.dark;
    return Container(
      width: double.infinity,
      margin: const EdgeInsets.symmetric(vertical: AppSpacing.sm),
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

/// Interrupteur accompagné d'une explication.
class AiSwitchField extends StatelessWidget {
  const AiSwitchField({
    super.key,
    required this.label,
    required this.description,
    required this.value,
    required this.onChanged,
  });

  final String label;
  final String description;
  final bool value;
  final ValueChanged<bool>? onChanged;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    return SwitchListTile(
      contentPadding: EdgeInsets.zero,
      value: value,
      onChanged: onChanged,
      title: Text(label, style: theme.textTheme.titleMedium),
      subtitle: Text(description, style: theme.textTheme.bodySmall),
    );
  }
}

/// Option d'un choix exclusif expliqué.
class AiOption<T> {
  const AiOption({required this.value, required this.label, required this.description});

  final T value;
  final String label;
  final String description;
}

/// Choix exclusif : chaque option porte sa propre explication.
class AiChoiceField<T> extends StatelessWidget {
  const AiChoiceField({
    super.key,
    required this.options,
    required this.selected,
    required this.onChanged,
    this.enabled = true,
  });

  final List<AiOption<T>> options;
  final T? selected;
  final ValueChanged<T> onChanged;
  final bool enabled;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    return Column(
      children: <Widget>[
        for (final AiOption<T> option in options)
          Padding(
            padding: const EdgeInsets.only(bottom: AppSpacing.sm),
            child: InkWell(
              borderRadius: BorderRadius.circular(AppSpacing.radiusSmall),
              onTap: enabled ? () => onChanged(option.value) : null,
              child: Container(
                padding: const EdgeInsets.all(AppSpacing.md),
                decoration: BoxDecoration(
                  borderRadius: BorderRadius.circular(AppSpacing.radiusSmall),
                  border: Border.all(
                    color: option.value == selected ? AppColors.primary : theme.colorScheme.outline,
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
                      color: option.value == selected ? AppColors.primary : AppColors.textTertiary,
                    ),
                    const SizedBox(width: AppSpacing.md),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: <Widget>[
                          Text(
                            option.label,
                            style:
                                theme.textTheme.bodyMedium?.copyWith(fontWeight: FontWeight.w600),
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
    );
  }
}

/// Champ texte libre (adresse, nom de modèle), avec explication.
class AiTextField extends StatefulWidget {
  const AiTextField({
    super.key,
    required this.label,
    required this.description,
    required this.value,
    required this.onChanged,
    this.hint,
    this.enabled = true,
    this.trailing,
  });

  final String label;
  final String description;
  final String value;
  final ValueChanged<String> onChanged;
  final String? hint;
  final bool enabled;

  /// Bouton affiché sous le champ (choisir un modèle détecté, par exemple).
  final Widget? trailing;

  @override
  State<AiTextField> createState() => _AiTextFieldState();
}

class _AiTextFieldState extends State<AiTextField> {
  late final TextEditingController _controller = TextEditingController(text: widget.value);

  @override
  void didUpdateWidget(AiTextField oldWidget) {
    super.didUpdateWidget(oldWidget);
    // Le brouillon a changé ailleurs (choix dans la liste des modèles détectés).
    if (widget.value != _controller.text) {
      _controller.value = TextEditingValue(
        text: widget.value,
        selection: TextSelection.collapsed(offset: widget.value.length),
      );
    }
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
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
            autocorrect: false,
            decoration: InputDecoration(hintText: widget.hint),
            onChanged: widget.onChanged,
          ),
          if (widget.trailing != null) ...<Widget>[
            const SizedBox(height: AppSpacing.sm),
            Align(alignment: Alignment.centerLeft, child: widget.trailing!),
          ],
        ],
      ),
    );
  }
}

/// Champ numérique borné, avec explication de ce qu'il protège.
class AiNumberField extends StatefulWidget {
  const AiNumberField({
    super.key,
    required this.label,
    required this.description,
    required this.value,
    required this.onChanged,
    this.suffix,
    this.decimal = false,
    this.enabled = true,
  });

  final String label;
  final String description;
  final num? value;
  final ValueChanged<num?> onChanged;
  final String? suffix;
  final bool decimal;
  final bool enabled;

  @override
  State<AiNumberField> createState() => _AiNumberFieldState();
}

class _AiNumberFieldState extends State<AiNumberField> {
  late final TextEditingController _controller =
      TextEditingController(text: _format(widget.value));

  String _format(num? value) {
    if (value == null) return '';
    if (!widget.decimal) return value.toInt().toString();
    final double asDouble = value.toDouble();
    return asDouble == asDouble.roundToDouble()
        ? asDouble.toInt().toString()
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
    widget.onChanged(widget.decimal ? double.tryParse(cleaned) : int.tryParse(cleaned));
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
        ],
      ),
    );
  }
}
