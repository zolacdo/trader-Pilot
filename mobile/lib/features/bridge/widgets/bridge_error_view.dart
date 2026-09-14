import 'package:flutter/material.dart';

import '../../../core/api/api_exception.dart';
import '../../../core/widgets/app_widgets.dart';

/// Affiche une erreur du Bridge sans jamais montrer la trace technique brute.
///
/// Le message lisible vient de [ApiException.message] ; le détail technique
/// reste consultable en dépliant la section prévue par [ErrorView].
class BridgeErrorView extends StatelessWidget {
  const BridgeErrorView({super.key, required this.error, this.onRetry});

  final Object error;
  final VoidCallback? onRetry;

  /// Message lisible et détail technique associés à une erreur quelconque.
  static ({String message, String? technical}) describe(Object error) {
    if (error is ApiException) {
      return (message: error.message, technical: error.technical);
    }
    return (
      message: 'Une erreur inattendue est survenue dans l\'application.',
      technical: error.toString(),
    );
  }

  @override
  Widget build(BuildContext context) {
    final ({String message, String? technical}) described = describe(error);
    return ErrorView(
      message: described.message,
      technical: described.technical,
      onRetry: onRetry,
    );
  }
}
