import 'package:flutter/material.dart';

import '../../../core/api/api_exception.dart';
import '../../../core/widgets/app_widgets.dart';

/// Exécute une action envoyée au Bridge et rend compte à l'utilisateur.
///
/// Une erreur réseau est présentée avec [ApiException.message] : jamais une
/// trace technique brute. Retourne vrai quand l'action a abouti.
Future<bool> runBridgeAction(
  BuildContext context, {
  required Future<void> Function() action,
  required String successMessage,
}) async {
  try {
    await action();
    if (!context.mounted) return true;
    showToast(context, successMessage);
    return true;
  } on ApiException catch (error) {
    if (!context.mounted) return false;
    showToast(context, error.message, error: true);
    return false;
  }
}
