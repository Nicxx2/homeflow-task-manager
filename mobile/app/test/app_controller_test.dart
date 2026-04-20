import 'package:flutter_test/flutter_test.dart';
import 'package:homeflow_mobile/src/application/app_controller.dart';
import 'package:homeflow_mobile/src/application/app_services.dart';
import 'package:homeflow_mobile/src/core/models/app_preferences.dart';
import 'package:homeflow_mobile/src/core/models/auth_session.dart';
import 'package:homeflow_mobile/src/core/models/connection_settings.dart';
import 'package:homeflow_mobile/src/core/models/task_cache_snapshot.dart';
import 'package:homeflow_mobile/src/data/repositories/connection_repository.dart';
import 'package:homeflow_mobile/src/data/repositories/preferences_repository.dart';
import 'package:homeflow_mobile/src/data/repositories/saved_login_repository.dart';
import 'package:homeflow_mobile/src/data/repositories/session_repository.dart';
import 'package:homeflow_mobile/src/data/repositories/task_cache_repository.dart';
import 'package:homeflow_mobile/src/data/repositories/widget_state_repository.dart';
import 'package:homeflow_mobile/src/data/storage/in_memory_local_store.dart';
import 'package:homeflow_mobile/src/data/storage/in_memory_secure_store.dart';
import 'package:homeflow_mobile/src/presentation/widgets/sync_status_strip.dart';
import 'package:http/http.dart' as http;

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test(
    'initialize keeps cached auth-required state out of manual sign-in status when session is still active',
    () async {
      final services = _buildServices();
      const settings = ConnectionSettings(
        scheme: 'https',
        host: 'example.com',
        port: 443,
      );
      final session = AuthSession(
        accessToken: 'token',
        expiresAt: DateTime.now().toUtc().add(const Duration(hours: 2)),
        user: const AuthUser(
          id: 1,
          email: 'user@example.com',
          fullName: 'Test User',
          isAdmin: false,
          isActive: true,
          approvalStatus: 'approved',
          showInMemberLists: true,
        ),
      );
      final snapshot = TaskCacheSnapshot(
        serverBaseUrl: settings.baseUrl,
        userEmail: session.user.email,
        windowStart: DateTime.utc(2026, 4, 20),
        windowEnd: DateTime.utc(2026, 4, 26),
        lastSuccessfulSyncAt: DateTime.now().toUtc().subtract(
          const Duration(minutes: 20),
        ),
        lastAttemptAt: DateTime.now().toUtc().subtract(
          const Duration(minutes: 2),
        ),
        lastSyncResult: SyncResultStatus.authRequired,
        tasks: const [],
      );

      await services.connectionRepository.save(settings);
      await services.sessionRepository.save(session);
      await services.taskCacheRepository.save(snapshot);
      await services.preferencesRepository.save(
        const AppPreferences(
          offlineTaskWindow: OfflineTaskWindow.days7,
          autoRefreshOnOpen: false,
          themeMode: AppThemeMode.system,
          dailyReminderEnabled: true,
          dailyReminderMinutesAfterMidnight: 8 * 60,
        ),
      );

      final controller = AppController(services);
      await controller.initialize();

      expect(controller.needsReauth, isFalse);
      expect(controller.preferences.dailyReminderEnabled, isTrue);

      final status = HeaderStatus.fromController(controller);
      expect(status.label, 'Cached');
      expect(status.tone, StatusTone.warning);
      controller.dispose();
    },
  );

  test('initialize restores persisted notification preferences', () async {
    final services = _buildServices();
    const savedPreferences = AppPreferences(
      offlineTaskWindow: OfflineTaskWindow.days14,
      autoRefreshOnOpen: false,
      themeMode: AppThemeMode.dark,
      dailyReminderEnabled: true,
      dailyReminderMinutesAfterMidnight: 9 * 60 + 45,
    );

    await services.preferencesRepository.save(savedPreferences);

    final controller = AppController(services);
    await controller.initialize();

    expect(
      controller.preferences.offlineTaskWindow,
      OfflineTaskWindow.days14,
    );
    expect(controller.preferences.autoRefreshOnOpen, isFalse);
    expect(controller.preferences.themeMode, AppThemeMode.dark);
    expect(controller.preferences.dailyReminderEnabled, isTrue);
    expect(
      controller.preferences.dailyReminderMinutesAfterMidnight,
      9 * 60 + 45,
    );
    controller.dispose();
  });
}

AppServices _buildServices() {
  final localStore = InMemoryLocalStore();
  final secureStore = InMemorySecureStore();

  return AppServices(
    connectionRepository: ConnectionRepository(
      localStore,
      secureStore: secureStore,
    ),
    savedLoginRepository: SavedLoginRepository(secureStore),
    sessionRepository: SessionRepository(secureStore),
    preferencesRepository: PreferencesRepository(localStore),
    taskCacheRepository: TaskCacheRepository(localStore),
    widgetStateRepository: WidgetStateRepository(localStore),
    httpClient: http.Client(),
  );
}
