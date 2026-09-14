import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:image_picker/image_picker.dart';

import '../../core/api/api_client.dart';
import '../../core/api/api_exception.dart';
import '../../core/api/endpoints.dart';
import '../../core/connection/connection_controller.dart';

/// Taille maximale acceptée par le Bridge pour une capture (CDC section 22).
const int maxChartImageBytes = 4 * 1024 * 1024;

/// Une analyse conservée en mémoire pour la durée de la session.
@immutable
class AiAnalysisEntry {
  const AiAnalysisEntry({
    required this.at,
    required this.result,
    this.instrument,
    this.question,
  });

  final DateTime at;
  final Map<String, dynamic> result;
  final String? instrument;
  final String? question;
}

/// État de l'écran d'analyse IA.
@immutable
class AiAnalysisState {
  const AiAnalysisState({
    this.imagePath,
    this.imageName,
    this.imageBytes,
    this.sending = false,
    this.errorMessage,
    this.errorTechnical,
    this.result,
    this.history = const <AiAnalysisEntry>[],
  });

  final String? imagePath;
  final String? imageName;
  final int? imageBytes;
  final bool sending;
  final String? errorMessage;
  final String? errorTechnical;
  final Map<String, dynamic>? result;
  final List<AiAnalysisEntry> history;

  bool get hasImage => imagePath != null;

  bool get imageTooLarge => (imageBytes ?? 0) > maxChartImageBytes;

  bool get canSend => hasImage && !sending && !imageTooLarge;

  AiAnalysisState copyWith({
    String? imagePath,
    String? imageName,
    int? imageBytes,
    bool? sending,
    String? errorMessage,
    String? errorTechnical,
    Map<String, dynamic>? result,
    List<AiAnalysisEntry>? history,
    bool clearImage = false,
    bool clearError = false,
    bool clearResult = false,
  }) {
    return AiAnalysisState(
      imagePath: clearImage ? null : (imagePath ?? this.imagePath),
      imageName: clearImage ? null : (imageName ?? this.imageName),
      imageBytes: clearImage ? null : (imageBytes ?? this.imageBytes),
      sending: sending ?? this.sending,
      errorMessage: clearError ? null : (errorMessage ?? this.errorMessage),
      errorTechnical: clearError ? null : (errorTechnical ?? this.errorTechnical),
      result: clearResult ? null : (result ?? this.result),
      history: history ?? this.history,
    );
  }
}

/// Pilote l'import d'image et l'appel `POST /api/v1/ai/chart`.
///
/// Cet écran est strictement informatif : il n'expose aucune action de
/// trading et n'appelle aucune route d'exécution.
class AiAnalysisController extends StateNotifier<AiAnalysisState> {
  AiAnalysisController({required ApiClient api, ImagePicker? picker})
      : _api = api,
        _picker = picker ?? ImagePicker(),
        super(const AiAnalysisState());

  final ApiClient _api;
  final ImagePicker _picker;

  Future<void> pickFromGallery() => _pick(ImageSource.gallery);

  Future<void> takePhoto() => _pick(ImageSource.camera);

  Future<void> _pick(ImageSource source) async {
    try {
      final XFile? file = await _picker.pickImage(
        source: source,
        maxWidth: 2400,
        imageQuality: 90,
      );
      if (file == null) return;
      final int length = await file.length();
      state = state.copyWith(
        imagePath: file.path,
        imageName: file.name,
        imageBytes: length,
        clearError: true,
        clearResult: true,
      );
    } catch (error) {
      state = state.copyWith(
        errorMessage: 'Impossible d\'ouvrir l\'image. Vérifiez les autorisations de l\'application.',
        errorTechnical: error.toString(),
      );
    }
  }

  void clearImage() => state = state.copyWith(clearImage: true, clearError: true, clearResult: true);

  /// Affiche une analyse déjà réalisée pendant la session.
  void showFromHistory(AiAnalysisEntry entry) {
    state = state.copyWith(result: entry.result, clearError: true);
  }

  /// Envoie la capture au Bridge en multipart.
  Future<void> analyze({String? instrument, String? question}) async {
    final String? path = state.imagePath;
    if (path == null || state.sending) return;
    if (state.imageTooLarge) {
      state = state.copyWith(
        errorMessage: 'Cette image dépasse 4 Mo. Recadrez la capture ou réduisez sa qualité.',
      );
      return;
    }

    final String cleanInstrument = (instrument ?? '').trim();
    final String cleanQuestion = (question ?? '').trim();
    state = state.copyWith(sending: true, clearError: true, clearResult: true);

    try {
      final FormData form = FormData.fromMap(<String, dynamic>{
        'image': await MultipartFile.fromFile(
          path,
          filename: state.imageName ?? 'chart.png',
          contentType: _mediaTypeFor(state.imageName ?? path),
        ),
        if (cleanInstrument.isNotEmpty) 'instrument': cleanInstrument,
        if (cleanQuestion.isNotEmpty) 'question': cleanQuestion,
      });
      final Map<String, dynamic> result = await _api.postMultipart(Endpoints.aiChart, form);
      final AiAnalysisEntry entry = AiAnalysisEntry(
        at: DateTime.now(),
        result: result,
        instrument: cleanInstrument.isEmpty ? null : cleanInstrument,
        question: cleanQuestion.isEmpty ? null : cleanQuestion,
      );
      state = state.copyWith(
        sending: false,
        result: result,
        history: <AiAnalysisEntry>[entry, ...state.history].take(15).toList(growable: false),
      );
    } on ApiException catch (error) {
      state = state.copyWith(
        sending: false,
        errorMessage: describeChartError(error),
        errorTechnical: error.technical,
      );
    } catch (error) {
      state = state.copyWith(
        sending: false,
        errorMessage: 'L\'analyse n\'a pas pu être envoyée.',
        errorTechnical: error.toString(),
      );
    }
  }

  /// Devine le type MIME à partir de l'extension du fichier choisi.
  static DioMediaType _mediaTypeFor(String name) {
    final String lower = name.toLowerCase();
    if (lower.endsWith('.jpg') || lower.endsWith('.jpeg')) return DioMediaType('image', 'jpeg');
    if (lower.endsWith('.webp')) return DioMediaType('image', 'webp');
    return DioMediaType('image', 'png');
  }
}

/// Traduit une erreur du Bridge en phrase compréhensible (CDC section 62).
String describeChartError(ApiException error) {
  if (error.statusCode == 413) {
    return 'Cette image dépasse la taille maximale de 4 Mo acceptée par le Bridge. '
        'Recadrez la capture ou réduisez sa qualité.';
  }
  if (error.statusCode == 400) {
    return 'L\'image envoyée est vide ou illisible.';
  }
  if (error.statusCode == 502) {
    final String detail = error.message.toLowerCase();
    if (detail.contains('cle') || detail.contains('clé') || detail.contains('key')) {
      return 'Aucune clé OpenRouter n\'est configurée sur le Bridge. '
          'Renseignez-la depuis les Paramètres avant d\'analyser une image.';
    }
    if (detail.contains('aucun modele gratuit') || detail.contains('aucun modèle gratuit')) {
      return 'Aucun modèle vision gratuit n\'est disponible chez OpenRouter pour le moment. '
          'L\'application n\'utilise que des modèles gratuits : réessayez plus tard.';
    }
    if (detail.contains('format')) {
      return 'Ce format d\'image n\'est pas accepté. Utilisez une capture PNG, JPEG ou WebP.';
    }
    return 'OpenRouter est indisponible pour le moment : l\'analyse n\'a pas pu être réalisée.';
  }
  return error.message;
}

final StateNotifierProvider<AiAnalysisController, AiAnalysisState> aiAnalysisProvider =
    StateNotifierProvider<AiAnalysisController, AiAnalysisState>((Ref ref) {
  return AiAnalysisController(api: ref.watch(apiClientProvider));
});
