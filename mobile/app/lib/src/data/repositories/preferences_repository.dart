import 'dart:convert';

import '../../core/models/app_preferences.dart';
import '../../core/storage/local_store.dart';

class PreferencesRepository {
  PreferencesRepository(this._store);

  static const String storageKey = 'homeflow.app_preferences';

  final LocalStore _store;

  Future<void> save(AppPreferences preferences) async {
    await _store.writeString(storageKey, jsonEncode(preferences.toJson()));
  }

  Future<AppPreferences> load() async {
    final raw = await _store.readString(storageKey);
    if (raw == null || raw.isEmpty) {
      return AppPreferences.defaults();
    }
    return AppPreferences.fromJson(jsonDecode(raw) as Map<String, dynamic>);
  }
}
