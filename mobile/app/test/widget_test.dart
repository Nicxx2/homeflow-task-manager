import 'package:flutter_test/flutter_test.dart';
import 'package:homeflow_mobile/src/core/models/app_preferences.dart';
import 'package:homeflow_mobile/src/core/models/saved_login.dart';

void main() {
  test('offline task window maps to expected day counts', () {
    expect(OfflineTaskWindow.days3.days, 3);
    expect(OfflineTaskWindow.days7.days, 7);
    expect(OfflineTaskWindow.days14.days, 14);
    expect(OfflineTaskWindow.days30.days, 30);
  });

  test('theme mode preferences serialize and restore correctly', () {
    const preferences = AppPreferences(
      offlineTaskWindow: OfflineTaskWindow.days14,
      autoRefreshOnOpen: false,
      themeMode: AppThemeMode.dark,
    );

    final restored = AppPreferences.fromJson(preferences.toJson());

    expect(restored.offlineTaskWindow, OfflineTaskWindow.days14);
    expect(restored.autoRefreshOnOpen, isFalse);
    expect(restored.themeMode, AppThemeMode.dark);
  });

  test('saved login serializes and restores correctly', () {
    const login = SavedLogin(
      email: 'user@example.com',
      password: 'secret-pass',
    );

    final restored = SavedLogin.fromJson(login.toJson());

    expect(restored.email, 'user@example.com');
    expect(restored.password, 'secret-pass');
  });
}
