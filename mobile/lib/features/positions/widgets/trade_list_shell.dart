import 'package:flutter/material.dart';

/// Rend un contenu court (vide, erreur) défilable, pour que le geste
/// « tirer pour rafraîchir » reste disponible même sans liste.
class FillViewport extends StatelessWidget {
  const FillViewport({super.key, required this.child});

  final Widget child;

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (BuildContext context, BoxConstraints constraints) {
        return SingleChildScrollView(
          physics: const AlwaysScrollableScrollPhysics(),
          child: ConstrainedBox(
            constraints: BoxConstraints(minHeight: constraints.maxHeight),
            child: child,
          ),
        );
      },
    );
  }
}
