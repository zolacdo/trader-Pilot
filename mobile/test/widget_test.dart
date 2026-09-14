import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:tradepilot/core/theme/app_colors.dart';
import 'package:tradepilot/core/theme/app_theme.dart';
import 'package:tradepilot/core/widgets/app_widgets.dart';

void main() {
  group('Theme', () {
    test('l accent principal est bien #2563EB', () {
      expect(AppTheme.light().colorScheme.primary, AppColors.primary);
      expect(AppTheme.dark().colorScheme.primary, AppColors.primary);
    });

    test('la couleur d un montant suit son signe', () {
      expect(AppColors.forAmount(12.5), AppColors.profit);
      expect(AppColors.forAmount(-3), AppColors.loss);
      expect(AppColors.forAmount(0), AppColors.textSecondary);
    });
  });

  testWidgets('le bandeau hors ligne annonce clairement la coupure', (WidgetTester tester) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: const Scaffold(body: OfflineBanner()),
      ),
    );
    expect(find.textContaining('BRIDGE HORS LIGNE'), findsOneWidget);
  });

  testWidgets('la pastille de direction distingue BUY et SELL', (WidgetTester tester) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: Scaffold(
          body: Column(
            children: <Widget>[
              StatusChip.direction('BUY'),
              StatusChip.direction('SELL'),
            ],
          ),
        ),
      ),
    );
    expect(find.text('BUY'), findsOneWidget);
    expect(find.text('SELL'), findsOneWidget);
  });

  testWidgets('la confirmation par phrase reste bloquee tant que la saisie ne correspond pas',
      (WidgetTester tester) async {
    late BuildContext capturedContext;
    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: Builder(
          builder: (BuildContext context) {
            capturedContext = context;
            return const Scaffold(body: SizedBox.shrink());
          },
        ),
      ),
    );

    confirmWithPhrase(
      capturedContext,
      title: 'Fermer toutes les positions',
      message: 'Action irreversible.',
      phrase: 'FERMER TOUTES LES POSITIONS',
    );
    await tester.pumpAndSettle();

    final Finder confirmButton = find.widgetWithText(FilledButton, 'Confirmer');
    expect(tester.widget<FilledButton>(confirmButton).onPressed, isNull);

    await tester.enterText(find.byType(TextField), 'FERMER TOUTES LES POSITIONS');
    await tester.pumpAndSettle();
    expect(tester.widget<FilledButton>(confirmButton).onPressed, isNotNull);
  });
}
