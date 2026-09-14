import 'dart:io';

import 'package:dio/dio.dart';

/// Erreur d'appel au Bridge, traduite pour l'utilisateur.
///
/// L'application n'affiche jamais un message technique brut du type
/// `SocketException 10061` : elle montre une phrase claire et garde le detail
/// technique a part, consultable dans le diagnostic (CDC section 62).
class ApiException implements Exception {
  const ApiException({
    required this.message,
    this.technical,
    this.statusCode,
    this.kind = ApiErrorKind.unknown,
  });

  final String message;
  final String? technical;
  final int? statusCode;
  final ApiErrorKind kind;

  bool get isOffline => kind == ApiErrorKind.offline;

  bool get isUnauthorized => kind == ApiErrorKind.unauthorized;

  @override
  String toString() => 'ApiException($statusCode): $message';

  /// Construit un message comprehensible a partir d'une erreur Dio.
  factory ApiException.fromDio(DioException error) {
    final int? status = error.response?.statusCode;
    final String? detail = _extractDetail(error.response?.data);
    final String technical = _technical(error);

    switch (error.type) {
      case DioExceptionType.connectionTimeout:
      case DioExceptionType.sendTimeout:
      case DioExceptionType.receiveTimeout:
        return ApiException(
          message: 'Le Bridge met trop de temps à répondre.',
          technical: technical,
          kind: ApiErrorKind.timeout,
        );
      case DioExceptionType.connectionError:
      case DioExceptionType.unknown:
        if (error.error is SocketException || error.error is HandshakeException) {
          return ApiException(
            message: 'Impossible de joindre le Bridge.',
            technical: technical,
            kind: ApiErrorKind.offline,
          );
        }
        break;
      case DioExceptionType.cancel:
        return ApiException(
          message: 'Requête annulée.',
          technical: technical,
          kind: ApiErrorKind.cancelled,
        );
      default:
        break;
    }

    if (status == null) {
      return ApiException(
        message: 'Impossible de joindre le Bridge.',
        technical: technical,
        kind: ApiErrorKind.offline,
      );
    }

    return switch (status) {
      401 => ApiException(
          message: 'Ce téléphone n’est plus autorisé. Refaites l’appairage avec le Bridge.',
          technical: technical,
          statusCode: status,
          kind: ApiErrorKind.unauthorized,
        ),
      403 => ApiException(
          message: detail ?? 'Action refusée par le Bridge.',
          technical: technical,
          statusCode: status,
          kind: ApiErrorKind.forbidden,
        ),
      404 => ApiException(
          message: detail ?? 'Élément introuvable.',
          technical: technical,
          statusCode: status,
          kind: ApiErrorKind.notFound,
        ),
      409 => ApiException(
          message: detail ?? 'Action impossible dans l’état actuel.',
          technical: technical,
          statusCode: status,
          kind: ApiErrorKind.conflict,
        ),
      422 => ApiException(
          message: detail ?? 'Données invalides.',
          technical: technical,
          statusCode: status,
          kind: ApiErrorKind.validation,
        ),
      429 => ApiException(
          message: detail ?? 'Trop de requêtes : patientez quelques instants.',
          technical: technical,
          statusCode: status,
          kind: ApiErrorKind.rateLimited,
        ),
      502 || 503 || 504 => ApiException(
          message: detail ?? 'Un service externe est indisponible.',
          technical: technical,
          statusCode: status,
          kind: ApiErrorKind.upstream,
        ),
      _ => ApiException(
          message: detail ?? 'Le Bridge a rencontré une erreur.',
          technical: technical,
          statusCode: status,
          kind: ApiErrorKind.server,
        ),
    };
  }

  static String? _extractDetail(Object? data) {
    if (data is Map) {
      final Object? detail = data['detail'];
      if (detail is String && detail.trim().isNotEmpty) return detail;
      if (detail is List && detail.isNotEmpty) return detail.first.toString();
      final Object? message = data['message'];
      if (message is String && message.trim().isNotEmpty) return message;
    }
    return null;
  }

  static String _technical(DioException error) {
    final StringBuffer buffer = StringBuffer()
      ..write(error.type.name)
      ..write(' ')
      ..write(error.requestOptions.method)
      ..write(' ')
      ..write(error.requestOptions.path);
    if (error.response?.statusCode != null) {
      buffer.write(' -> HTTP ${error.response!.statusCode}');
    }
    if (error.error != null) {
      buffer.write(' | ${error.error}');
    }
    return buffer.toString();
  }
}

enum ApiErrorKind {
  offline,
  timeout,
  unauthorized,
  forbidden,
  notFound,
  conflict,
  validation,
  rateLimited,
  upstream,
  server,
  cancelled,
  unknown,
}
