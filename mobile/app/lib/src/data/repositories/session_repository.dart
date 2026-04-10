import 'dart:convert';

import '../../core/models/auth_session.dart';
import '../../core/storage/secure_store.dart';

class SessionRepository {
  SessionRepository(this._store);

  static const String storageKey = 'homeflow.auth_session';

  final SecureStore _store;

  Future<void> save(AuthSession session) async {
    await _store.write(storageKey, jsonEncode(session.toJson()));
  }

  Future<AuthSession?> load() async {
    final raw = await _store.read(storageKey);
    if (raw == null || raw.isEmpty) {
      return null;
    }
    return AuthSession.fromJson(jsonDecode(raw) as Map<String, dynamic>);
  }

  Future<void> clear() async {
    await _store.delete(storageKey);
  }
}
