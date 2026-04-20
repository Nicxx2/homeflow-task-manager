import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter/services.dart';

import '../../core/storage/secure_store.dart';

class FlutterSecureStoreAdapter implements SecureStore {
  FlutterSecureStoreAdapter(this._storage);

  final FlutterSecureStorage _storage;
  final Map<String, String> _fallbackValues = <String, String>{};

  @override
  Future<void> delete(String key) async {
    _fallbackValues.remove(key);
    try {
      await _storage.delete(key: key);
    } on PlatformException {
      // Fall back to in-memory storage on devices where secure storage is unavailable.
    } on MissingPluginException {
      // Fall back to in-memory storage on devices where secure storage is unavailable.
    }
  }

  @override
  Future<String?> read(String key) async {
    try {
      return await _storage.read(key: key);
    } on PlatformException {
      return _fallbackValues[key];
    } on MissingPluginException {
      return _fallbackValues[key];
    }
  }

  @override
  Future<void> write(String key, String value) async {
    _fallbackValues[key] = value;
    try {
      await _storage.write(key: key, value: value);
    } on PlatformException {
      // Fall back to in-memory storage on devices where secure storage is unavailable.
    } on MissingPluginException {
      // Fall back to in-memory storage on devices where secure storage is unavailable.
    }
  }
}
