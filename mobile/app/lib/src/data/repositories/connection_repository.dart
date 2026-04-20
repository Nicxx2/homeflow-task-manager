import 'dart:convert';

import '../../core/models/connection_settings.dart';
import '../../core/storage/local_store.dart';
import '../../core/storage/secure_store.dart';

class ConnectionRepository {
  ConnectionRepository(this._store, {SecureStore? secureStore})
      : _secureStore = secureStore;

  static const String storageKey = 'homeflow.connection_settings';

  final LocalStore _store;
  final SecureStore? _secureStore;

  Future<void> save(ConnectionSettings settings) async {
    final encoded = jsonEncode(settings.toJson());
    await _store.writeString(storageKey, encoded);
    final secureStore = _secureStore;
    if (secureStore != null) {
      await secureStore.write(storageKey, encoded);
    }
  }

  Future<ConnectionSettings?> load() async {
    var raw = await _store.readString(storageKey);
    if ((raw == null || raw.isEmpty) && _secureStore != null) {
      raw = await _secureStore.read(storageKey);
      if (raw != null && raw.isNotEmpty) {
        try {
          await _store.writeString(storageKey, raw);
        } catch (_) {
          // Best-effort repair only.
        }
      }
    }
    if (raw == null || raw.isEmpty) {
      return null;
    }
    return ConnectionSettings.fromJson(jsonDecode(raw) as Map<String, dynamic>);
  }

  Future<void> clear() async {
    await _store.delete(storageKey);
    final secureStore = _secureStore;
    if (secureStore != null) {
      await secureStore.delete(storageKey);
    }
  }
}
