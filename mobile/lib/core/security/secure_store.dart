import 'package:flutter_secure_storage/flutter_secure_storage.dart';

/// Stockage chiffre des elements sensibles du telephone.
///
/// Seuls l'adresse du Bridge et le jeton de peripherique y sont conserves.
/// Aucune cle OpenRouter, aucun identifiant MetaTrader et aucune session
/// Telegram ne transitent par le telephone : ils restent sur le Bridge.
class SecureStore {
  const SecureStore({FlutterSecureStorage? storage})
      : _storage = storage ??
            const FlutterSecureStorage(
              aOptions: AndroidOptions(encryptedSharedPreferences: true),
            );

  final FlutterSecureStorage _storage;

  static const String _keyBaseUrl = 'bridge.base_url';
  static const String _keyToken = 'bridge.device_token';
  static const String _keyDeviceId = 'bridge.device_id';
  static const String _keyFallbackUrl = 'bridge.fallback_url';

  Future<String?> readBaseUrl() => _storage.read(key: _keyBaseUrl);

  Future<void> writeBaseUrl(String value) => _storage.write(key: _keyBaseUrl, value: value);

  /// Adresse de repli : l'IP locale lorsque l'URL publique ne repond pas.
  Future<String?> readFallbackUrl() => _storage.read(key: _keyFallbackUrl);

  Future<void> writeFallbackUrl(String? value) async {
    if (value == null || value.isEmpty) {
      await _storage.delete(key: _keyFallbackUrl);
      return;
    }
    await _storage.write(key: _keyFallbackUrl, value: value);
  }

  Future<String?> readToken() => _storage.read(key: _keyToken);

  Future<void> writeToken(String value) => _storage.write(key: _keyToken, value: value);

  Future<String?> readDeviceId() => _storage.read(key: _keyDeviceId);

  Future<void> writeDeviceId(String value) => _storage.write(key: _keyDeviceId, value: value);

  /// Efface l'appairage. Les donnees en cache restent, sans valeur sensible.
  Future<void> clearPairing() async {
    await _storage.delete(key: _keyToken);
    await _storage.delete(key: _keyDeviceId);
  }

  Future<void> clearAll() async {
    await _storage.deleteAll();
  }
}
