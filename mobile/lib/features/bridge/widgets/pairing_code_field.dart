import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

/// Met en forme la saisie du code d'appairage au format `XXXX-XXXX`.
///
/// L'utilisateur peut taper en minuscules, avec ou sans tiret : la saisie est
/// normalisée en majuscules et le tiret est ajouté automatiquement.
class PairingCodeFormatter extends TextInputFormatter {
  const PairingCodeFormatter();

  static const int _blockLength = 4;
  static const int _codeLength = 8;

  /// Code sans tiret ni espace, en majuscules.
  static String compact(String raw) =>
      raw.toUpperCase().replaceAll(RegExp('[^A-Z0-9]'), '');

  /// Vrai quand le code a la longueur attendue par le Bridge.
  static bool isComplete(String raw) => compact(raw).length == _codeLength;

  @override
  TextEditingValue formatEditUpdate(TextEditingValue oldValue, TextEditingValue newValue) {
    String digits = compact(newValue.text);
    if (digits.length > _codeLength) {
      digits = digits.substring(0, _codeLength);
    }
    final String formatted = digits.length > _blockLength
        ? '${digits.substring(0, _blockLength)}-${digits.substring(_blockLength)}'
        : digits;
    return TextEditingValue(
      text: formatted,
      selection: TextSelection.collapsed(offset: formatted.length),
    );
  }
}

/// Champ de saisie du code d'appairage.
class PairingCodeField extends StatelessWidget {
  const PairingCodeField({
    super.key,
    required this.controller,
    required this.enabled,
    this.onSubmitted,
  });

  final TextEditingController controller;
  final bool enabled;
  final VoidCallback? onSubmitted;

  @override
  Widget build(BuildContext context) {
    return TextField(
      controller: controller,
      enabled: enabled,
      autocorrect: false,
      enableSuggestions: false,
      textCapitalization: TextCapitalization.characters,
      textInputAction: TextInputAction.done,
      keyboardType: TextInputType.visiblePassword,
      inputFormatters: const <TextInputFormatter>[PairingCodeFormatter()],
      style: const TextStyle(
        fontSize: 20,
        fontWeight: FontWeight.w600,
        letterSpacing: 3,
        fontFeatures: <FontFeature>[FontFeature.tabularFigures()],
      ),
      onSubmitted: onSubmitted == null ? null : (_) => onSubmitted!(),
      decoration: const InputDecoration(
        labelText: 'Code d\'appairage',
        hintText: 'XXXX-XXXX',
        prefixIcon: Icon(Icons.key_outlined),
      ),
    );
  }
}
