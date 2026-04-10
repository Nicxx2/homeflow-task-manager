import 'dart:convert';

import '../../core/models/connection_settings.dart';
import '../../core/storage/local_store.dart';

class ConnectionRepository {
  ConnectionRepository(this._store);

  static const String storageKey = 'homeflow.connection_settings';

  final LocalStore _store;

  Future<void> save(ConnectionSettings settings) async {
    await _store.writeString(storageKey, jsonEncode(settings.toJson()));
  }

  Future<ConnectionSettings?> load() async {
    final raw = await _store.readString(storageKey);
    if (raw == null || raw.isEmpty) {
      return null;
    }
    return ConnectionSettings.fromJson(jsonDecode(raw) as Map<String, dynamic>);
  }
}
