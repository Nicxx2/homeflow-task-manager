import 'dart:convert';

import '../../core/models/task_cache_snapshot.dart';
import '../../core/storage/local_store.dart';

class TaskCacheRepository {
  TaskCacheRepository(this._store);

  final LocalStore _store;

  String _cacheKey({required String serverBaseUrl, required String userEmail}) {
    final normalized = '$serverBaseUrl::$userEmail'.toLowerCase().replaceAll(
      RegExp(r'[^a-z0-9]+'),
      '_',
    );
    return 'homeflow.cache.$normalized';
  }

  Future<TaskCacheSnapshot?> load({
    required String serverBaseUrl,
    required String userEmail,
  }) async {
    final raw = await _store.readString(
      _cacheKey(serverBaseUrl: serverBaseUrl, userEmail: userEmail),
    );
    if (raw == null || raw.isEmpty) {
      return null;
    }
    return TaskCacheSnapshot.fromJson(jsonDecode(raw) as Map<String, dynamic>);
  }

  Future<void> save(TaskCacheSnapshot snapshot) async {
    await _store.writeString(
      _cacheKey(
        serverBaseUrl: snapshot.serverBaseUrl,
        userEmail: snapshot.userEmail,
      ),
      jsonEncode(snapshot.toJson()),
    );
  }

  Future<void> clear({
    required String serverBaseUrl,
    required String userEmail,
  }) async {
    await _store.delete(
      _cacheKey(serverBaseUrl: serverBaseUrl, userEmail: userEmail),
    );
  }
}
