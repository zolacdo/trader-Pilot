import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_client.dart';
import '../../../core/api/api_exception.dart';
import '../../../core/api/endpoints.dart';
import '../../../core/connection/connection_controller.dart';
import '../../bridge/models/bridge_json.dart';

/// Ce que l'arrêt d'urgence va réellement toucher.
///
/// Les compteurs viennent des routes `/positions` et `/orders` : ils décrivent
/// la situation réelle chez le broker. Lorsqu'une de ces routes ne répond pas,
/// le compteur reste `null` et l'écran affiche « -- » plutôt qu'un chiffre
/// inventé.
@immutable
class EmergencyOverview {
  const EmergencyOverview({
    required this.closeAllPhrase,
    this.positionCount,
    this.orderCount,
    this.executionMode,
    this.countsError,
  });

  /// Phrase exacte exigée par le Bridge pour fermer toutes les positions.
  final String closeAllPhrase;
  final int? positionCount;
  final int? orderCount;
  final String? executionMode;

  /// Message lisible quand les compteurs n'ont pas pu être lus.
  final String? countsError;
}

/// Charge la phrase de confirmation et l'inventaire réellement concerné.
final FutureProvider<EmergencyOverview> emergencyOverviewProvider =
    FutureProvider<EmergencyOverview>((Ref ref) async {
  final ApiClient api = ref.watch(apiClientProvider);
  final Map<String, dynamic> info = await api.getJson(Endpoints.emergencyInfo);

  int? positions;
  int? orders;
  String? mode;
  String? countsError;
  try {
    final Map<String, dynamic> positionsPayload = await api.getJson(Endpoints.positions);
    final Map<String, dynamic> ordersPayload = await api.getJson(Endpoints.orders);
    positions = Json.integer(positionsPayload['count']) ??
        Json.objects(positionsPayload['items']).length;
    orders = Json.integer(ordersPayload['count']) ?? Json.objects(ordersPayload['items']).length;
    mode = Json.text(positionsPayload['executionMode']);
  } on ApiException catch (error) {
    countsError = error.message;
  }

  return EmergencyOverview(
    closeAllPhrase: Json.text(info['closeAllPhrase']) ?? 'FERMER TOUTES LES POSITIONS',
    positionCount: positions,
    orderCount: orders,
    executionMode: mode,
    countsError: countsError,
  );
});
