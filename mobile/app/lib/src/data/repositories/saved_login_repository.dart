import 'dart:convert';

import '../../core/models/saved_login.dart';
import '../../core/storage/secure_store.dart';

class SavedLoginRepository {
  SavedLoginRepository(this._store);

  static const String storageKey = 'homeflow.saved_login';

  final SecureStore _store;

  Future<void> save(SavedLogin login) async {
    await _store.write(storageKey, jsonEncode(login.toJson()));
  }

  Future<SavedLogin?> load() async {
    final raw = await _store.read(storageKey);
    if (raw == null || raw.isEmpty) {
      return null;
    }
    return SavedLogin.fromJson(jsonDecode(raw) as Map<String, dynamic>);
  }

  Future<void> clear() async {
    await _store.delete(storageKey);
  }
}
