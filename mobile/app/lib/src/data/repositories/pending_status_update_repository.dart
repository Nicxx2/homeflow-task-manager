import 'dart:convert';

import '../../core/models/pending_status_update.dart';
import '../../core/storage/local_store.dart';

class PendingStatusUpdateRepository {
  PendingStatusUpdateRepository(this._store);

  final LocalStore _store;

  String _queueKey({required String serverBaseUrl, required String userEmail}) {
    final normalized = '$serverBaseUrl::$userEmail'.toLowerCase().replaceAll(
          RegExp(r'[^a-z0-9]+'),
          '_',
        );
    return 'homeflow.pending_status.$normalized';
  }

  Future<List<PendingStatusUpdate>> load({
    required String serverBaseUrl,
    required String userEmail,
  }) async {
    final raw = await _store.readString(
      _queueKey(serverBaseUrl: serverBaseUrl, userEmail: userEmail),
    );
    if (raw == null || raw.isEmpty) {
      return const <PendingStatusUpdate>[];
    }
    final decoded = jsonDecode(raw) as List<dynamic>;
    return decoded
        .map((item) =>
            PendingStatusUpdate.fromJson(item as Map<String, dynamic>))
        .toList(growable: false);
  }

  Future<void> save({
    required String serverBaseUrl,
    required String userEmail,
    required List<PendingStatusUpdate> updates,
  }) async {
    final key = _queueKey(serverBaseUrl: serverBaseUrl, userEmail: userEmail);
    if (updates.isEmpty) {
      await _store.delete(key);
      return;
    }
    await _store.writeString(
      key,
      jsonEncode(updates.map((update) => update.toJson()).toList()),
    );
  }

  Future<void> clear({
    required String serverBaseUrl,
    required String userEmail,
  }) async {
    await _store.delete(
      _queueKey(serverBaseUrl: serverBaseUrl, userEmail: userEmail),
    );
  }
}
