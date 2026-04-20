import 'package:shared_preferences/shared_preferences.dart';

import '../../core/storage/local_store.dart';

class SharedPreferencesStore implements LocalStore {
  SharedPreferencesStore(this._preferences);

  final SharedPreferences _preferences;
  final Map<String, String> _fallbackValues = <String, String>{};

  @override
  Future<void> delete(String key) async {
    _fallbackValues.remove(key);
    try {
      await _preferences.remove(key);
    } catch (_) {
      // Fall back to in-memory storage if preferences are unavailable.
    }
  }

  @override
  Future<String?> readString(String key) async {
    try {
      return _preferences.getString(key) ?? _fallbackValues[key];
    } catch (_) {
      return _fallbackValues[key];
    }
  }

  @override
  Future<void> writeString(String key, String value) async {
    _fallbackValues[key] = value;
    try {
      await _preferences.setString(key, value);
    } catch (_) {
      // Fall back to in-memory storage if preferences are unavailable.
    }
  }
}
