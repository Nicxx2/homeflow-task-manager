import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import '../../core/storage/secure_store.dart';

class FlutterSecureStoreAdapter implements SecureStore {
  FlutterSecureStoreAdapter(this._storage);

  final FlutterSecureStorage _storage;

  @override
  Future<void> delete(String key) {
    return _storage.delete(key: key);
  }

  @override
  Future<String?> read(String key) {
    return _storage.read(key: key);
  }

  @override
  Future<void> write(String key, String value) {
    return _storage.write(key: key, value: value);
  }
}
