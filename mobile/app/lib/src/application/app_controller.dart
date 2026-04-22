import 'package:flutter/foundation.dart';

import '../core/app_release.dart';
import '../core/date_display.dart';
import '../core/models/app_preferences.dart';
import '../core/models/auth_session.dart';
import '../core/models/connection_settings.dart';
import '../core/models/mobile_task.dart';
import '../core/models/saved_login.dart';
import '../core/models/task_cache_snapshot.dart';
import '../core/models/today_widget_snapshot.dart';
import '../data/api/api_exception.dart';
import '../data/api/homeflow_api_client.dart';
import '../platform/android_widget_bridge.dart';
import '../platform/task_notification_bridge.dart';
import 'app_services.dart';
import 'sync_coordinator.dart';

class AppController extends ChangeNotifier {
  AppController(this._services)
      : _syncCoordinator = SyncCoordinator(
          taskCacheRepository: _services.taskCacheRepository,
          clientFactory: (baseUrl) => HomeflowApiClient(
            baseUrl: baseUrl,
            httpClient: _services.httpClient,
          ),
        );

  final AppServices _services;
  final SyncCoordinator _syncCoordinator;

  AppPreferences _preferences = AppPreferences.defaults();
  ConnectionSettings? _connectionSettings;
  AuthSession? _session;
  SavedLogin? _savedLogin;
  TaskCacheSnapshot? _cacheSnapshot;
  String? _errorMessage;
  String? _initializationDiagnostics;
  bool _isInitializing = true;
  bool _isAuthenticating = false;
  bool _isRestoringSession = false;
  bool _isSyncing = false;
  int _selectedTabIndex = 0;
  final Set<int> _updatingTaskIds = <int>{};

  AppPreferences get preferences => _preferences;
  ConnectionSettings? get connectionSettings => _connectionSettings;
  AuthSession? get session => _session;
  TaskCacheSnapshot? get cacheSnapshot => _cacheSnapshot;
  String? get errorMessage => _errorMessage;
  String? get initializationDiagnostics => _initializationDiagnostics;
  bool get isInitializing => _isInitializing;
  bool get isAuthenticating => _isAuthenticating;
  bool get isRestoringSession => _isRestoringSession;
  bool get isSyncing => _isSyncing;
  int get selectedTabIndex => _selectedTabIndex;
  DateTime? get cacheWindowStart => _cacheSnapshot?.windowStart;
  DateTime? get cacheWindowEnd => _cacheSnapshot?.windowEnd;
  AppThemeMode get themeModePreference => _preferences.themeMode;

  bool get isAuthenticated => _session != null;
  bool get hasInitializationFailure => _initializationDiagnostics != null;

  String? get currentBaseUrl => _connectionSettings?.baseUrl;

  String? get currentUserEmail => _session?.user.email;

  bool get hasCachedTasks => (_cacheSnapshot?.tasks.length ?? 0) > 0;

  bool get hasAnyCache => _cacheSnapshot != null;

  bool get hasSavedLogin => _savedLogin != null;

  bool get hasActiveSession => _session != null && !(_session?.isExpired ?? true);

  bool get isShowingCachedData {
    final result =
        _cacheSnapshot?.lastSyncResult ?? SyncResultStatus.neverSynced;
    return result != SyncResultStatus.success && hasCachedTasks;
  }

  bool get needsReauth {
    if (_isRestoringSession || hasActiveSession || hasSavedLogin) {
      return false;
    }
    final result = _cacheSnapshot?.lastSyncResult;
    return result == SyncResultStatus.authRequired ||
        (_session?.isExpired ?? false);
  }

  bool get canRetrySync {
    if (_isSyncing || _connectionSettings == null) {
      return false;
    }
    return true;
  }

  bool get canChangeTaskStatus {
    if (_connectionSettings == null) {
      return false;
    }
    return _session != null || hasCachedTasks;
  }

  bool get isDataStale {
    final snapshot = _cacheSnapshot;
    if (snapshot == null) {
      return false;
    }
    final lastSuccess = snapshot.lastSuccessfulSyncAt;
    if (lastSuccess == null) {
      return snapshot.lastSyncResult != SyncResultStatus.success;
    }
    final age = DateTime.now().toUtc().difference(lastSuccess);
    return snapshot.lastSyncResult != SyncResultStatus.success ||
        age > const Duration(hours: 6);
  }

  List<MobileTask> get activeTodayTasks {
    final tasks = _cacheSnapshot?.tasks ?? const <MobileTask>[];
    return tasks
        .where((task) => task.displayBucket == 'today' && !task.isCompleted)
        .toList(growable: false);
  }

  List<MobileTask> get overdueTasks {
    final tasks = _cacheSnapshot?.tasks ?? const <MobileTask>[];
    return tasks
        .where((task) => task.displayBucket == 'overdue' && !task.isCompleted)
        .toList(growable: false);
  }

  List<MobileTask> get completedTodayTasks {
    final today = _todayUtc();
    final tasks = _cacheSnapshot?.tasks ?? const <MobileTask>[];
    return tasks.where((task) {
      if (task.displayBucket != 'completed') {
        return false;
      }
      final assignment = _dateOnly(task.assignmentDate ?? task.dueDate);
      return assignment.isAtSameMomentAs(today);
    }).toList(growable: false);
  }

  List<MobileTask> get upcomingTasks {
    final tasks = _cacheSnapshot?.tasks ?? const <MobileTask>[];
    return tasks
        .where((task) => task.displayBucket == 'upcoming')
        .toList(growable: false);
  }

  Map<DateTime, List<MobileTask>> get groupedUpcomingTasks {
    final Map<DateTime, List<MobileTask>> grouped =
        <DateTime, List<MobileTask>>{};
    for (final task in upcomingTasks) {
      final day = _dateOnly(task.assignmentDate ?? task.dueDate);
      grouped.putIfAbsent(day, () => <MobileTask>[]).add(task);
    }
    final sortedKeys = grouped.keys.toList()..sort();
    return <DateTime, List<MobileTask>>{
      for (final key in sortedKeys) key: grouped[key]!,
    };
  }

  List<DateTime> get upcomingDays {
    final now = DateTime.now().toUtc();
    final tomorrow = DateTime.utc(
      now.year,
      now.month,
      now.day,
    ).add(const Duration(days: 1));
    final snapshot = _cacheSnapshot;
    final maxDays = preferences.offlineTaskWindow.days < 5
        ? preferences.offlineTaskWindow.days
        : 5;
    if (snapshot == null) {
      return List<DateTime>.generate(
        maxDays,
        (index) => tomorrow.add(Duration(days: index)),
        growable: false,
      );
    }

    final lastDay =
        snapshot.windowEnd.isBefore(tomorrow.add(Duration(days: maxDays - 1)))
            ? snapshot.windowEnd
            : tomorrow.add(Duration(days: maxDays - 1));
    final days = <DateTime>[];
    var current = tomorrow;
    while (!current.isAfter(lastDay)) {
      days.add(current);
      current = current.add(const Duration(days: 1));
    }
    return days;
  }

  List<MobileTask> tasksForDate(DateTime day) {
    final target = _dateOnly(day);
    final tasks = _cacheSnapshot?.tasks ?? const <MobileTask>[];
    return tasks.where((task) {
      final assignment = _dateOnly(task.assignmentDate ?? task.dueDate);
      return assignment.isAtSameMomentAs(target);
    }).toList(growable: false);
  }

  bool isDayCached(DateTime day) {
    final snapshot = _cacheSnapshot;
    if (snapshot == null) {
      return false;
    }
    final target = _dateOnly(day);
    return !target.isBefore(snapshot.windowStart) &&
        !target.isAfter(snapshot.windowEnd);
  }

  String upcomingCoverageMessage() {
    final snapshot = _cacheSnapshot;
    if (snapshot == null) {
      return 'No cached upcoming days are available yet.';
    }
    final start = formatDateOnlyLabel(snapshot.windowStart, 'dd MMM');
    final end = formatDateOnlyLabel(snapshot.windowEnd, 'dd MMM');
    return 'Cached window: $start to $end.';
  }

  String messageForDay(DateTime day) {
    if (!isDayCached(day)) {
      if (needsReauth) {
        return 'No cached tasks available for ${formatWeekdayLabelLower(day)} yet. Sign in again to refresh this day.';
      }
      final result = _cacheSnapshot?.lastSyncResult;
      if (result == SyncResultStatus.serverUnreachable ||
          result == SyncResultStatus.networkUnavailable) {
        return 'No cached tasks available for ${formatWeekdayLabelLower(day)} yet because the server could not be reached.';
      }
      return 'No cached tasks available for ${formatWeekdayLabelLower(day)} yet.';
    }
    return 'No tasks for this day in the current cache window.';
  }

  bool isUpdatingTask(int taskId) => _updatingTaskIds.contains(taskId);

  String get syncStatusMessage {
    if (needsReauth) {
      return 'Sign in again to refresh tasks. Showing cached data if available.';
    }
    final snapshot = _cacheSnapshot;
    if (snapshot == null) {
      return _errorMessage ?? 'No cached task data yet.';
    }
    switch (snapshot.lastSyncResult) {
      case SyncResultStatus.neverSynced:
        return 'No sync has been completed yet.';
      case SyncResultStatus.success:
        final lastSync = snapshot.lastSuccessfulSyncAt;
        if (lastSync == null) {
          return 'Sync completed.';
        }
        return 'Last synced ${_formatTimestamp(lastSync)}.';
      case SyncResultStatus.networkUnavailable:
        return 'No network available. Showing cached tasks from your last sync.';
      case SyncResultStatus.serverUnreachable:
        return 'Cannot reach your Homeflow server right now. Showing cached tasks.';
      case SyncResultStatus.authRequired:
        return hasSavedLogin || hasActiveSession
            ? 'Session will refresh automatically. Showing cached tasks for now.'
            : 'Sign in again to refresh tasks. Showing cached data if available.';
      case SyncResultStatus.serverError:
        return 'Server returned an error. Showing cached tasks from your last sync.';
      case SyncResultStatus.validationError:
        return 'The app request could not be completed. Showing cached tasks.';
      case SyncResultStatus.unknownError:
        return 'Refresh failed. Showing cached tasks from your last sync.';
    }
  }

  String get syncBannerTitle {
    if (_isSyncing || _isRestoringSession) {
      return 'Refreshing tasks';
    }
    if (needsReauth) {
      return 'Sign in again required';
    }
    final snapshot = _cacheSnapshot;
    if (snapshot == null) {
      return _errorMessage == null ? 'No cached data yet' : 'Sync unavailable';
    }
    switch (snapshot.lastSyncResult) {
      case SyncResultStatus.neverSynced:
        return 'No sync yet';
      case SyncResultStatus.success:
        return isDataStale ? 'Showing cached tasks' : 'Tasks are up to date';
      case SyncResultStatus.networkUnavailable:
        return 'No network';
      case SyncResultStatus.serverUnreachable:
        return 'Server unreachable';
      case SyncResultStatus.authRequired:
        return needsReauth ? 'Sign in again required' : 'Refresh needed';
      case SyncResultStatus.serverError:
        return 'Server error';
      case SyncResultStatus.validationError:
        return 'Sync request failed';
      case SyncResultStatus.unknownError:
        return 'Sync failed';
    }
  }

  String get syncBannerActionLabel {
    return 'Retry now';
  }

  bool get syncBannerIsWarning {
    if (_isSyncing || _isRestoringSession) {
      return false;
    }
    final snapshot = _cacheSnapshot;
    if (snapshot == null) {
      return _errorMessage != null;
    }
    return snapshot.lastSyncResult != SyncResultStatus.success || isDataStale;
  }

  bool get syncBannerIsError {
    if (_isSyncing || _isRestoringSession) {
      return false;
    }
    if (needsReauth) {
      return true;
    }
    final snapshot = _cacheSnapshot;
    if (snapshot == null) {
      return _errorMessage != null;
    }
    return (snapshot.lastSyncResult == SyncResultStatus.authRequired &&
            needsReauth) ||
        snapshot.lastSyncResult == SyncResultStatus.serverError ||
        snapshot.lastSyncResult == SyncResultStatus.validationError;
  }

  MobileTask? taskById(int id) {
    final tasks = _cacheSnapshot?.tasks ?? const <MobileTask>[];
    for (final task in tasks) {
      if (task.id == id) {
        return task;
      }
    }
    return null;
  }

  Future<bool> updateTaskStatus({
    required int taskId,
    required MobileTaskStatus status,
  }) async {
    final settings = _connectionSettings;
    final snapshot = _cacheSnapshot;
    if (settings == null || snapshot == null) {
      return false;
    }
    final session = await _ensureActiveSession();
    if (session == null) {
      _errorMessage = needsReauth
          ? 'Sign in again before changing task status.'
          : 'Task status changes are unavailable right now.';
      await _persistWidgetSnapshot();
      notifyListeners();
      return false;
    }

    _updatingTaskIds.add(taskId);
    _clearError();
    notifyListeners();

    final client = HomeflowApiClient(
      baseUrl: settings.baseUrl,
      httpClient: _services.httpClient,
    );

    try {
      final result = await client.updateTaskStatus(
        accessToken: session.accessToken,
        taskId: taskId,
        status: status,
      );

      if (result.refreshRequired || result.task == null) {
        await refreshTasks();
        return true;
      }

      final updatedTasks = snapshot.tasks
          .map((task) => task.id == taskId ? result.task! : task)
          .toList(growable: false)
        ..sort((a, b) => a.sortKey.compareTo(b.sortKey));
      final updatedSnapshot = snapshot.copyWith(
        lastAttemptAt: DateTime.now().toUtc(),
        lastSuccessfulSyncAt: DateTime.now().toUtc(),
        lastSyncResult: SyncResultStatus.success,
        tasks: updatedTasks,
      );
      _cacheSnapshot = updatedSnapshot;
      await _services.taskCacheRepository.save(updatedSnapshot);
      await _persistWidgetSnapshot();
      await _syncScheduledTaskReminders();
      notifyListeners();
      return true;
    } on ApiException catch (error) {
      _errorMessage = error.message;
      notifyListeners();
      return false;
    } finally {
      _updatingTaskIds.remove(taskId);
      notifyListeners();
    }
  }

  Future<void> initialize() async {
    _isInitializing = true;
    _initializationDiagnostics = null;
    notifyListeners();

    try {
      _preferences = await _services.preferencesRepository.load();
      _connectionSettings = await _services.connectionRepository.load();
      _savedLogin = await _services.savedLoginRepository.load();
      _session = await _services.sessionRepository.load();

      final settings = _connectionSettings;
      final session = _session;
      if (settings != null && session != null) {
        _cacheSnapshot = await _services.taskCacheRepository.load(
          serverBaseUrl: settings.baseUrl,
          userEmail: session.user.email,
        );
      }

      final restoredSession = await _ensureActiveSession(
        allowCachedSession: true,
      );
      if (settings != null &&
          restoredSession != null &&
          _preferences.autoRefreshOnOpen) {
        await refreshTasks();
      } else {
        await _syncScheduledTaskReminders();
      }
    } catch (error, stackTrace) {
      _errorMessage = 'Homeflow could not finish loading on this device.';
      _initializationDiagnostics = _buildInitializationDiagnostics(
        error,
        stackTrace,
      );
    } finally {
      _isInitializing = false;
      try {
        await _persistWidgetSnapshot();
      } catch (_) {
        // Widget sync should never block the main app from opening.
      }
      notifyListeners();
    }
  }

  Future<bool> testConnection(ConnectionSettings settings) async {
    _clearError();
    if (!settings.isValid) {
      _errorMessage = settings.validationError;
      notifyListeners();
      return false;
    }
    final client = HomeflowApiClient(
      baseUrl: settings.baseUrl,
      httpClient: _services.httpClient,
    );
    try {
      await client.testConnection();
      return true;
    } on ApiException catch (error) {
      _errorMessage = error.message;
      notifyListeners();
      return false;
    }
  }

  Future<bool> signIn({
    required String scheme,
    required String host,
    required int port,
    required String email,
    required String password,
  }) async {
    _isAuthenticating = true;
    _clearError();
    notifyListeners();

    final settings = ConnectionSettings(
      scheme: scheme,
      host: host.trim(),
      port: port,
    );
    if (!settings.isValid) {
      _isAuthenticating = false;
      _errorMessage = settings.validationError;
      notifyListeners();
      return false;
    }

    final client = HomeflowApiClient(
      baseUrl: settings.baseUrl,
      httpClient: _services.httpClient,
    );

    try {
      await client.testConnection();
      final savedLogin = SavedLogin(email: email.trim(), password: password);
      final session = await client.login(
        email: email.trim(),
        password: password,
      );

      await _services.connectionRepository.save(settings);
      await _services.sessionRepository.save(session);
      await _services.savedLoginRepository.save(savedLogin);
      _connectionSettings = settings;
      _savedLogin = savedLogin;
      _session = session;
      _cacheSnapshot = await _services.taskCacheRepository.load(
        serverBaseUrl: settings.baseUrl,
        userEmail: session.user.email,
      );
      _selectedTabIndex = 0;
      await refreshTasks();
      return true;
    } on ApiException catch (error) {
      _errorMessage = error.message;
      return false;
    } finally {
      _isAuthenticating = false;
      notifyListeners();
    }
  }

  Future<void> refreshTasks() async {
    final settings = _connectionSettings;
    if (settings == null) {
      return;
    }

    final session = await _ensureActiveSession();
    if (session == null) {
      _errorMessage = 'Sign in again to refresh tasks.';
      await _persistWidgetSnapshot();
      notifyListeners();
      return;
    }

    _isSyncing = true;
    _clearError();
    notifyListeners();

    final previous = await _services.taskCacheRepository.load(
      serverBaseUrl: settings.baseUrl,
      userEmail: session.user.email,
    );
    final outcome = await _syncCoordinator.refreshWindow(
      connectionSettings: settings,
      session: session,
      preferences: _preferences,
      previousSnapshot: previous,
    );

    _cacheSnapshot = outcome.snapshot;
    _errorMessage = outcome.error?.message;
    if (outcome.snapshot.lastSyncResult == SyncResultStatus.authRequired) {
      final restoredSession = await _ensureActiveSession(forceRefresh: true);
      if (restoredSession != null) {
        final retryOutcome = await _syncCoordinator.refreshWindow(
          connectionSettings: settings,
          session: restoredSession,
          preferences: _preferences,
          previousSnapshot: _cacheSnapshot,
        );
        _cacheSnapshot = retryOutcome.snapshot;
        _errorMessage = retryOutcome.error?.message;
      }
    }
    _isSyncing = false;
    await _persistWidgetSnapshot();
    await _syncScheduledTaskReminders();
    notifyListeners();
  }

  Future<void> handleAppResumed() async {
    if (_isInitializing || _isAuthenticating || _isSyncing) {
      return;
    }

    final settings = _connectionSettings;
    if (settings == null) {
      return;
    }

    final restoredSession = await _ensureActiveSession(
      allowCachedSession: true,
      forceRefresh: _cacheSnapshot?.lastSyncResult == SyncResultStatus.authRequired,
    );

    if (_preferences.autoRefreshOnOpen && restoredSession != null) {
      await refreshTasks();
      return;
    }

    await _persistWidgetSnapshot();
    await _syncScheduledTaskReminders();
    notifyListeners();
  }

  Future<void> updateOfflineWindow(OfflineTaskWindow value) async {
    _preferences = _preferences.copyWith(offlineTaskWindow: value);
    await _services.preferencesRepository.save(_preferences);
    await _syncScheduledTaskReminders();
    notifyListeners();
    if (isAuthenticated) {
      await refreshTasks();
    }
  }

  Future<void> setAutoRefreshOnOpen(bool value) async {
    _preferences = _preferences.copyWith(autoRefreshOnOpen: value);
    await _services.preferencesRepository.save(_preferences);
    notifyListeners();
  }

  Future<void> setShowOverdueTasksInTodayView(bool value) async {
    if (value == _preferences.showOverdueTasksInTodayView) {
      return;
    }
    _preferences = _preferences.copyWith(showOverdueTasksInTodayView: value);
    await _services.preferencesRepository.save(_preferences);
    notifyListeners();
  }

  Future<void> setDailyReminderEnabled(bool value) async {
    if (value == _preferences.dailyReminderEnabled) {
      return;
    }

    if (value) {
      final granted = await TaskNotificationBridge.requestPermission();
      if (!granted) {
        _errorMessage =
            'Notifications are disabled for this app on this device.';
        notifyListeners();
        return;
      }
    }

    _preferences = _preferences.copyWith(dailyReminderEnabled: value);
    await _services.preferencesRepository.save(_preferences);
    await _syncScheduledTaskReminders();
    notifyListeners();
  }

  Future<void> setDailyReminderMinutesAfterMidnight(int value) async {
    final normalized = value.clamp(0, (24 * 60) - 1);
    if (normalized == _preferences.dailyReminderMinutesAfterMidnight) {
      return;
    }

    _preferences = _preferences.copyWith(
      dailyReminderMinutesAfterMidnight: normalized,
    );
    await _services.preferencesRepository.save(_preferences);
    await _syncScheduledTaskReminders();
    notifyListeners();
  }

  Future<void> setThemeMode(AppThemeMode value) async {
    if (_preferences.themeMode == value) {
      return;
    }
    _preferences = _preferences.copyWith(themeMode: value);
    await _services.preferencesRepository.save(_preferences);
    notifyListeners();
  }

  Future<void> clearCachedData() async {
    final settings = _connectionSettings;
    final session = _session;
    if (settings != null && session != null) {
      await _services.taskCacheRepository.clear(
        serverBaseUrl: settings.baseUrl,
        userEmail: session.user.email,
      );
    }
    _cacheSnapshot = null;
    await _persistWidgetSnapshot();
    await _syncScheduledTaskReminders();
    notifyListeners();
  }

  Future<void> logout() async {
    final settings = _connectionSettings;
    final session = _session;
    if (settings != null && session != null) {
      await _services.taskCacheRepository.clear(
        serverBaseUrl: settings.baseUrl,
        userEmail: session.user.email,
      );
    }
    await _services.sessionRepository.clear();
    await _services.savedLoginRepository.clear();
    _savedLogin = null;
    _session = null;
    _cacheSnapshot = null;
    _selectedTabIndex = 0;
    _clearError();
    await _persistWidgetSnapshot();
    await _syncScheduledTaskReminders();
    notifyListeners();
  }

  Future<AuthSession?> _ensureActiveSession({
    bool allowCachedSession = false,
    bool forceRefresh = false,
  }) async {
    final settings = _connectionSettings;
    if (settings == null) {
      return null;
    }

    final currentSession = _session;
    if (!forceRefresh && currentSession != null && !currentSession.isExpired) {
      return currentSession;
    }

    final savedLogin = _savedLogin ?? await _services.savedLoginRepository.load();
    _savedLogin = savedLogin;
    if (savedLogin == null) {
      if (!allowCachedSession) {
        _session = currentSession;
      }
      return currentSession != null && !currentSession.isExpired
          ? currentSession
          : null;
    }

    _isRestoringSession = true;
    notifyListeners();
    try {
      final refreshedSession = await _signInWithSavedLogin(
        settings,
        savedLogin,
      );
      _session = refreshedSession;
      await _services.sessionRepository.save(refreshedSession);
      _clearError();
      return refreshedSession;
    } on ApiException catch (error) {
      if (error.type == ApiErrorType.invalidCredentials) {
        await _services.savedLoginRepository.clear();
        await _services.sessionRepository.clear();
        _savedLogin = null;
        _session = null;
      }
      _errorMessage = error.message;
      return currentSession != null && !currentSession.isExpired
          ? currentSession
          : null;
    } finally {
      _isRestoringSession = false;
      notifyListeners();
    }
  }

  Future<AuthSession> _signInWithSavedLogin(
    ConnectionSettings settings,
    SavedLogin savedLogin,
  ) async {
    final client = HomeflowApiClient(
      baseUrl: settings.baseUrl,
      httpClient: _services.httpClient,
    );
    return client.login(email: savedLogin.email, password: savedLogin.password);
  }

  void selectTab(int index) {
    _selectedTabIndex = index;
    notifyListeners();
  }

  void clearError() {
    _clearError();
    notifyListeners();
  }

  void _clearError() {
    _errorMessage = null;
  }

  DateTime _todayUtc() {
    final now = DateTime.now().toUtc();
    return DateTime.utc(now.year, now.month, now.day);
  }

  DateTime _dateOnly(DateTime value) {
    final utc = value.toUtc();
    return DateTime.utc(utc.year, utc.month, utc.day);
  }

  String _formatTimestamp(DateTime value) {
    final local = value.toLocal();
    final month = local.month.toString().padLeft(2, '0');
    final day = local.day.toString().padLeft(2, '0');
    final hour = local.hour.toString().padLeft(2, '0');
    final minute = local.minute.toString().padLeft(2, '0');
    return '$month/$day ${local.year} $hour:$minute';
  }

  Future<void> _persistWidgetSnapshot() async {
    final snapshot = _buildWidgetSnapshot();
    await _services.widgetStateRepository.saveToday(snapshot);
    await AndroidWidgetBridge.updateTodaySnapshot(snapshot);
  }

  TodayWidgetSnapshot _buildWidgetSnapshot() {
    final now = DateTime.now().toUtc();
    final session = _session;
    final snapshot = _cacheSnapshot;
    final activeTodayTasks = this.activeTodayTasks;
    final previewTitles = activeTodayTasks
        .take(3)
        .map((task) => task.title)
        .toList(growable: false);

    if (session == null) {
      return TodayWidgetSnapshot(
        state: TodayWidgetState.signedOut,
        title: 'Homeflow',
        subtitle: 'Sign in to view today\'s tasks.',
        taskCount: 0,
        taskTitles: const <String>[],
        isStale: false,
        actionRoute: '/',
        generatedAt: now,
        lastSuccessfulSyncAt: null,
        userEmail: null,
      );
    }

    if (needsReauth) {
      return TodayWidgetSnapshot(
        state: TodayWidgetState.authRequired,
        title: 'Sign in again',
        subtitle: 'Session expired. Open the app to refresh cached tasks.',
        taskCount: activeTodayTasks.length,
        taskTitles: previewTitles,
        isStale: true,
        actionRoute: '/',
        generatedAt: now,
        lastSuccessfulSyncAt: snapshot?.lastSuccessfulSyncAt,
        userEmail: session.user.email,
      );
    }

    if (snapshot == null) {
      return TodayWidgetSnapshot(
        state: TodayWidgetState.noCache,
        title: 'No cached tasks yet',
        subtitle: 'Open the app to sync today\'s view.',
        taskCount: 0,
        taskTitles: const <String>[],
        isStale: false,
        actionRoute: '/',
        generatedAt: now,
        lastSuccessfulSyncAt: null,
        userEmail: session.user.email,
      );
    }

    final state = _widgetStateForSnapshot(
      snapshot: snapshot,
      activeTaskCount: activeTodayTasks.length,
    );
    return TodayWidgetSnapshot(
      state: state,
      title: _widgetTitleForState(
        state: state,
        activeTaskCount: activeTodayTasks.length,
      ),
      subtitle: _widgetSubtitleForSnapshot(snapshot),
      taskCount: activeTodayTasks.length,
      taskTitles: previewTitles,
      isStale:
          state == TodayWidgetState.stale || state == TodayWidgetState.error,
      actionRoute: '/',
      generatedAt: now,
      lastSuccessfulSyncAt: snapshot.lastSuccessfulSyncAt,
      userEmail: session.user.email,
    );
  }

  TodayWidgetState _widgetStateForSnapshot({
    required TaskCacheSnapshot snapshot,
    required int activeTaskCount,
  }) {
    if (snapshot.lastSyncResult == SyncResultStatus.serverError ||
        snapshot.lastSyncResult == SyncResultStatus.validationError) {
      return TodayWidgetState.error;
    }
    if (isDataStale ||
        snapshot.lastSyncResult == SyncResultStatus.authRequired ||
        snapshot.lastSyncResult == SyncResultStatus.networkUnavailable ||
        snapshot.lastSyncResult == SyncResultStatus.serverUnreachable ||
        snapshot.lastSyncResult == SyncResultStatus.unknownError ||
        snapshot.lastSyncResult == SyncResultStatus.neverSynced) {
      return TodayWidgetState.stale;
    }
    return activeTaskCount == 0
        ? TodayWidgetState.empty
        : TodayWidgetState.ready;
  }

  String _widgetTitleForState({
    required TodayWidgetState state,
    required int activeTaskCount,
  }) {
    switch (state) {
      case TodayWidgetState.signedOut:
        return 'Homeflow';
      case TodayWidgetState.noCache:
        return 'No cached tasks yet';
      case TodayWidgetState.authRequired:
        return 'Sign in again';
      case TodayWidgetState.error:
        return activeTaskCount == 0
            ? 'Today is unavailable'
            : '$activeTaskCount tasks for today';
      case TodayWidgetState.empty:
        return 'All caught up';
      case TodayWidgetState.stale:
      case TodayWidgetState.ready:
        if (activeTaskCount == 0) {
          return 'All caught up';
        }
        return activeTaskCount == 1
            ? '1 task for today'
            : '$activeTaskCount tasks for today';
    }
  }

  String _widgetSubtitleForSnapshot(TaskCacheSnapshot snapshot) {
    final lastSync = snapshot.lastSuccessfulSyncAt;
    switch (snapshot.lastSyncResult) {
      case SyncResultStatus.success:
        if (lastSync == null) {
          return 'Up to date.';
        }
        return 'Last synced ${_formatWidgetTime(lastSync)}.';
      case SyncResultStatus.networkUnavailable:
        return 'Offline. Showing cached tasks.';
      case SyncResultStatus.serverUnreachable:
        return 'Server unreachable. Showing cached tasks.';
      case SyncResultStatus.authRequired:
        return hasSavedLogin || hasActiveSession
            ? 'Session will refresh automatically. Showing cached tasks.'
            : 'Sign in again to refresh tasks.';
      case SyncResultStatus.serverError:
        return 'Server error. Showing cached tasks.';
      case SyncResultStatus.validationError:
        return 'Refresh failed. Showing cached tasks.';
      case SyncResultStatus.unknownError:
        return 'Refresh failed. Showing cached tasks.';
      case SyncResultStatus.neverSynced:
        return 'Open the app to complete your first sync.';
    }
  }

  String _formatWidgetTime(DateTime value) {
    final local = value.toLocal();
    final hour = local.hour.toString().padLeft(2, '0');
    final minute = local.minute.toString().padLeft(2, '0');
    return '$hour:$minute';
  }

  String _buildInitializationDiagnostics(
    Object error,
    StackTrace stackTrace,
  ) {
    return [
      'Homeflow Mobile startup diagnostics',
      'stage: controller_initialize',
      'release: $appReleaseLabel',
      'timestamp_utc: ${DateTime.now().toUtc().toIso8601String()}',
      'error_type: ${error.runtimeType}',
      'error: $error',
      'stack_trace:',
      stackTrace.toString(),
    ].join('\n');
  }

  Future<void> _syncScheduledTaskReminders() async {
    if (kIsWeb || defaultTargetPlatform != TargetPlatform.android) {
      return;
    }

    try {
      if (!_preferences.dailyReminderEnabled || _cacheSnapshot == null) {
        await TaskNotificationBridge.cancelTaskNotifications();
        return;
      }

      final reminders = _buildScheduledTaskReminders(_cacheSnapshot!);
      await TaskNotificationBridge.scheduleTaskNotifications(reminders);
    } catch (_) {
      // Notification scheduling should never break the main task flow.
    }
  }

  List<ScheduledTaskReminder> _buildScheduledTaskReminders(
    TaskCacheSnapshot snapshot,
  ) {
    final reminders = <ScheduledTaskReminder>[];
    final now = DateTime.now();
    final end = DateTime(
      snapshot.windowEnd.year,
      snapshot.windowEnd.month,
      snapshot.windowEnd.day,
    );
    final reminderHour = _preferences.dailyReminderMinutesAfterMidnight ~/ 60;
    final reminderMinute = _preferences.dailyReminderMinutesAfterMidnight % 60;

    var currentDay = DateTime(now.year, now.month, now.day);
    while (!currentDay.isAfter(end)) {
      final activeCount = _activeTaskCountForReminderDay(currentDay);
      final scheduledFor = DateTime(
        currentDay.year,
        currentDay.month,
        currentDay.day,
        reminderHour,
        reminderMinute,
      );
      if (activeCount > 0 && scheduledFor.isAfter(now)) {
        reminders.add(
          ScheduledTaskReminder(
            id: _notificationIdForDay(currentDay),
            scheduledFor: scheduledFor,
            title: 'Homeflow',
            body: activeCount == 1
                ? 'You have 1 active task today.'
                : 'You have $activeCount active tasks today.',
          ),
        );
      }
      currentDay = currentDay.add(const Duration(days: 1));
    }

    return reminders;
  }

  int _activeTaskCountForReminderDay(DateTime day) {
    final target = DateTime.utc(day.year, day.month, day.day);
    if (target.isAtSameMomentAs(_todayUtc())) {
      return activeTodayTasks.length;
    }
    return tasksForDate(target).where((task) => !task.isCompleted).length;
  }

  int _notificationIdForDay(DateTime day) {
    return (day.year * 10000) + (day.month * 100) + day.day;
  }
}
