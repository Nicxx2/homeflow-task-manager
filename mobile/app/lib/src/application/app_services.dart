import 'dart:io';

import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:http/http.dart' as http;
import 'package:path_provider/path_provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../data/storage/composite_local_store.dart';
import '../data/storage/file_local_store.dart';
import '../data/repositories/connection_repository.dart';
import '../data/repositories/preferences_repository.dart';
import '../data/repositories/pending_status_update_repository.dart';
import '../data/repositories/saved_login_repository.dart';
import '../data/repositories/session_repository.dart';
import '../data/repositories/task_cache_repository.dart';
import '../data/repositories/widget_state_repository.dart';
import '../data/storage/flutter_secure_store_adapter.dart';
import '../data/storage/in_memory_local_store.dart';
import '../data/storage/in_memory_secure_store.dart';
import '../data/storage/shared_preferences_store.dart';
import '../core/storage/local_store.dart';
import '../core/storage/secure_store.dart';

class AppServices {
  AppServices({
    required this.connectionRepository,
    required this.savedLoginRepository,
    required this.sessionRepository,
    required this.preferencesRepository,
    required this.pendingStatusUpdateRepository,
    required this.taskCacheRepository,
    required this.widgetStateRepository,
    required this.httpClient,
  });

  final ConnectionRepository connectionRepository;
  final SavedLoginRepository savedLoginRepository;
  final SessionRepository sessionRepository;
  final PreferencesRepository preferencesRepository;
  final PendingStatusUpdateRepository pendingStatusUpdateRepository;
  final TaskCacheRepository taskCacheRepository;
  final WidgetStateRepository widgetStateRepository;
  final http.Client httpClient;

  static Future<AppServices> bootstrap() async {
    final localStores = <LocalStore>[];

    try {
      final preferences = await SharedPreferences.getInstance();
      localStores.add(SharedPreferencesStore(preferences));
    } catch (_) {
      // Fall back to another local persistence backend if shared preferences fail.
    }

    try {
      final supportDirectory = await getApplicationSupportDirectory();
      localStores.add(
        FileLocalStore(
          File('${supportDirectory.path}/homeflow_local_store.json'),
        ),
      );
    } catch (_) {
      // Fall back to in-memory storage if no durable local storage is available.
    }

    final LocalStore localStore = switch (localStores.length) {
      0 => InMemoryLocalStore(),
      1 => localStores.first,
      _ => CompositeLocalStore(localStores),
    };

    late final SecureStore secureStore;
    try {
      secureStore = FlutterSecureStoreAdapter(const FlutterSecureStorage());
    } catch (_) {
      secureStore = InMemorySecureStore();
    }

    return AppServices(
      connectionRepository: ConnectionRepository(
        localStore,
        secureStore: secureStore,
      ),
      savedLoginRepository: SavedLoginRepository(secureStore),
      sessionRepository: SessionRepository(secureStore),
      preferencesRepository: PreferencesRepository(localStore),
      pendingStatusUpdateRepository: PendingStatusUpdateRepository(localStore),
      taskCacheRepository: TaskCacheRepository(localStore),
      widgetStateRepository: WidgetStateRepository(localStore),
      httpClient: http.Client(),
    );
  }
}
