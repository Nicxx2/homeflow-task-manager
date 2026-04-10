import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';

import '../data/repositories/connection_repository.dart';
import '../data/repositories/preferences_repository.dart';
import '../data/repositories/saved_login_repository.dart';
import '../data/repositories/session_repository.dart';
import '../data/repositories/task_cache_repository.dart';
import '../data/repositories/widget_state_repository.dart';
import '../data/storage/flutter_secure_store_adapter.dart';
import '../data/storage/shared_preferences_store.dart';

class AppServices {
  AppServices({
    required this.connectionRepository,
    required this.savedLoginRepository,
    required this.sessionRepository,
    required this.preferencesRepository,
    required this.taskCacheRepository,
    required this.widgetStateRepository,
    required this.httpClient,
  });

  final ConnectionRepository connectionRepository;
  final SavedLoginRepository savedLoginRepository;
  final SessionRepository sessionRepository;
  final PreferencesRepository preferencesRepository;
  final TaskCacheRepository taskCacheRepository;
  final WidgetStateRepository widgetStateRepository;
  final http.Client httpClient;

  static Future<AppServices> bootstrap() async {
    final preferences = await SharedPreferences.getInstance();
    final localStore = SharedPreferencesStore(preferences);
    final secureStore = FlutterSecureStoreAdapter(const FlutterSecureStorage());
    return AppServices(
      connectionRepository: ConnectionRepository(localStore),
      savedLoginRepository: SavedLoginRepository(secureStore),
      sessionRepository: SessionRepository(secureStore),
      preferencesRepository: PreferencesRepository(localStore),
      taskCacheRepository: TaskCacheRepository(localStore),
      widgetStateRepository: WidgetStateRepository(localStore),
      httpClient: http.Client(),
    );
  }
}
