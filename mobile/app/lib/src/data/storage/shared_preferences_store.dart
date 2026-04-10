import 'package:shared_preferences/shared_preferences.dart';

import '../../core/storage/local_store.dart';

class SharedPreferencesStore implements LocalStore {
  SharedPreferencesStore(this._preferences);

  final SharedPreferences _preferences;

  @override
  Future<void> delete(String key) async {
    await _preferences.remove(key);
  }

  @override
  Future<String?> readString(String key) async {
    return _preferences.getString(key);
  }

  @override
  Future<void> writeString(String key, String value) async {
    await _preferences.setString(key, value);
  }
}
