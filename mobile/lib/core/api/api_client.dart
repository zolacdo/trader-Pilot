import 'dart:async';

import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';

import 'api_exception.dart';

/// Client HTTP du Bridge TradePilot.
///
/// Toutes les routes sensibles exigent le jeton de peripherique obtenu lors de
/// l'appairage. Le jeton n'est jamais journalise ni affiche.
class ApiClient {
  ApiClient({Dio? dio}) : _dio = dio ?? Dio() {
    _dio
      ..options.connectTimeout = const Duration(seconds: 8)
      ..options.receiveTimeout = const Duration(seconds: 30)
      ..options.sendTimeout = const Duration(seconds: 30)
      ..options.headers['Accept'] = 'application/json'
      // Sans cet en-tete, ngrok peut renvoyer sa page d'avertissement au lieu
      // de la reponse du Bridge (ERR_NGROK_6024) : l'application recevrait du
      // HTML a la place du JSON attendu.
      ..options.headers['ngrok-skip-browser-warning'] = 'true'
      ..options.validateStatus = (status) => status != null && status < 400;
  }

  final Dio _dio;
  String? _baseUrl;
  String? _token;

  /// Notifie l'application quand le Bridge devient joignable ou non.
  final ValueNotifier<bool> reachable = ValueNotifier<bool>(false);

  /// Notifie quand le jeton a ete refuse : l'application doit reappairer.
  final ValueNotifier<bool> unauthorized = ValueNotifier<bool>(false);

  String? get baseUrl => _baseUrl;

  bool get hasToken => _token != null && _token!.isNotEmpty;

  bool get isConfigured => _baseUrl != null && _baseUrl!.isNotEmpty;

  void configure({required String baseUrl, String? token}) {
    _baseUrl = _normalizeBaseUrl(baseUrl);
    _token = token;
    _dio.options.baseUrl = _baseUrl!;
    unauthorized.value = false;
  }

  void setToken(String? token) {
    _token = token;
    unauthorized.value = false;
  }

  void clear() {
    _token = null;
    reachable.value = false;
  }

  /// Normalise ce que l'utilisateur saisit : `192.168.1.20:8787`,
  /// `http://192.168.1.20:8787/`, `https://mon-domaine.ngrok-free.app`.
  static String _normalizeBaseUrl(String raw) {
    String value = raw.trim();
    if (value.isEmpty) return value;
    if (!value.startsWith('http://') && !value.startsWith('https://')) {
      // Un nom de domaine passe forcement par HTTPS, une IP locale par HTTP.
      final bool looksLocal = RegExp(r'^(\d{1,3}\.){3}\d{1,3}(:\d+)?$').hasMatch(value) ||
          value.startsWith('localhost');
      value = '${looksLocal ? 'http' : 'https'}://$value';
    }
    while (value.endsWith('/')) {
      value = value.substring(0, value.length - 1);
    }
    return value;
  }

  Options _options({bool authenticated = true, String? contentType}) {
    final Map<String, dynamic> headers = <String, dynamic>{};
    if (authenticated && hasToken) {
      headers['Authorization'] = 'Bearer $_token';
    }
    return Options(headers: headers, contentType: contentType);
  }

  Future<T> _run<T>(Future<Response<dynamic>> Function() request, T Function(dynamic) parse) async {
    if (!isConfigured) {
      throw const ApiException(
        message: 'Aucun Bridge configuré. Terminez l’appairage depuis les Connexions.',
        kind: ApiErrorKind.offline,
      );
    }
    try {
      final Response<dynamic> response = await request();
      reachable.value = true;
      return parse(response.data);
    } on DioException catch (error) {
      final ApiException exception = ApiException.fromDio(error);
      if (exception.isOffline || exception.kind == ApiErrorKind.timeout) {
        reachable.value = false;
      }
      if (exception.isUnauthorized) {
        unauthorized.value = true;
      }
      throw exception;
    }
  }

  Future<Map<String, dynamic>> getJson(
    String path, {
    Map<String, dynamic>? query,
    bool authenticated = true,
  }) {
    return _run(
      () => _dio.get<dynamic>(path, queryParameters: query, options: _options(authenticated: authenticated)),
      (data) => _asMap(data),
    );
  }

  Future<List<dynamic>> getList(
    String path, {
    Map<String, dynamic>? query,
    bool authenticated = true,
  }) {
    return _run(
      () => _dio.get<dynamic>(path, queryParameters: query, options: _options(authenticated: authenticated)),
      (data) => data is List ? data : const <dynamic>[],
    );
  }

  Future<Map<String, dynamic>> postJson(
    String path, {
    Object? body,
    Map<String, dynamic>? query,
    bool authenticated = true,
  }) {
    return _run(
      () => _dio.post<dynamic>(
        path,
        data: body,
        queryParameters: query,
        options: _options(authenticated: authenticated),
      ),
      (data) => _asMap(data),
    );
  }

  Future<Map<String, dynamic>> patchJson(String path, {Object? body}) {
    return _run(
      () => _dio.patch<dynamic>(path, data: body, options: _options()),
      (data) => _asMap(data),
    );
  }

  Future<Map<String, dynamic>> putJson(String path, {Object? body}) {
    return _run(
      () => _dio.put<dynamic>(path, data: body, options: _options()),
      (data) => _asMap(data),
    );
  }

  Future<Map<String, dynamic>> deleteJson(String path, {Map<String, dynamic>? query}) {
    return _run(
      () => _dio.delete<dynamic>(path, queryParameters: query, options: _options()),
      (data) => _asMap(data),
    );
  }

  Future<Map<String, dynamic>> postMultipart(String path, FormData form) {
    return _run(
      () => _dio.post<dynamic>(path, data: form, options: _options(contentType: 'multipart/form-data')),
      (data) => _asMap(data),
    );
  }

  /// Verifie que le Bridge repond, sans exiger de jeton.
  Future<bool> ping({String? baseUrl}) async {
    final String? target = baseUrl == null ? _baseUrl : _normalizeBaseUrl(baseUrl);
    if (target == null || target.isEmpty) return false;
    try {
      final Response<dynamic> response = await Dio(
        BaseOptions(
          baseUrl: target,
          connectTimeout: const Duration(seconds: 6),
          receiveTimeout: const Duration(seconds: 6),
        ),
      ).get<dynamic>('/api/v1/health');
      final bool ok = response.statusCode == 200;
      if (baseUrl == null) reachable.value = ok;
      return ok;
    } on DioException {
      if (baseUrl == null) reachable.value = false;
      return false;
    }
  }

  static Map<String, dynamic> _asMap(dynamic data) {
    if (data is Map<String, dynamic>) return data;
    if (data is Map) return Map<String, dynamic>.from(data);
    return <String, dynamic>{'data': data};
  }
}
