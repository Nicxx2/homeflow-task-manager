import '../core/models/app_preferences.dart';
import '../core/models/auth_session.dart';
import '../core/models/connection_settings.dart';
import '../core/models/task_cache_snapshot.dart';
import '../data/api/api_exception.dart';
import '../data/api/homeflow_api_client.dart';
import '../data/repositories/task_cache_repository.dart';

class SyncOutcome {
  const SyncOutcome({required this.snapshot, this.error});

  final TaskCacheSnapshot snapshot;
  final ApiException? error;

  bool get isSuccess => error == null;
}

class SyncCoordinator {
  SyncCoordinator({
    required this.taskCacheRepository,
    required this.clientFactory,
  });

  final TaskCacheRepository taskCacheRepository;
  final HomeflowApiClient Function(String baseUrl) clientFactory;

  Future<SyncOutcome> refreshWindow({
    required ConnectionSettings connectionSettings,
    required AuthSession session,
    required AppPreferences preferences,
    TaskCacheSnapshot? previousSnapshot,
  }) async {
    final client = clientFactory(connectionSettings.baseUrl);
    final startDate = _dateOnly(
      DateTime.now().toUtc().subtract(const Duration(days: 1)),
    );
    final endDate = _dateOnly(
      DateTime.now().toUtc().add(
        Duration(days: preferences.offlineTaskWindow.days),
      ),
    );

    try {
      final remoteWindow = await client.fetchTaskWindow(
        accessToken: session.accessToken,
        startDate: startDate,
        endDate: endDate,
      );
      final snapshot = TaskCacheSnapshot(
        serverBaseUrl: connectionSettings.baseUrl,
        userEmail: session.user.email,
        windowStart: _dateOnly(remoteWindow.windowStart),
        windowEnd: _dateOnly(remoteWindow.windowEnd),
        lastSuccessfulSyncAt: remoteWindow.serverTime,
        lastAttemptAt: DateTime.now().toUtc(),
        lastSyncResult: SyncResultStatus.success,
        tasks: remoteWindow.tasks,
      );
      await taskCacheRepository.save(snapshot);
      return SyncOutcome(snapshot: snapshot);
    } on ApiException catch (error) {
      final fallback = _buildFailedSnapshot(
        connectionSettings: connectionSettings,
        session: session,
        previousSnapshot: previousSnapshot,
        preferences: preferences,
        error: error,
      );
      await taskCacheRepository.save(fallback);
      return SyncOutcome(snapshot: fallback, error: error);
    }
  }

  TaskCacheSnapshot _buildFailedSnapshot({
    required ConnectionSettings connectionSettings,
    required AuthSession session,
    required AppPreferences preferences,
    required ApiException error,
    TaskCacheSnapshot? previousSnapshot,
  }) {
    final now = DateTime.now().toUtc();
    final startDate = _dateOnly(now.subtract(const Duration(days: 1)));
    final endDate = _dateOnly(
      now.add(Duration(days: preferences.offlineTaskWindow.days)),
    );
    return TaskCacheSnapshot(
      serverBaseUrl: connectionSettings.baseUrl,
      userEmail: session.user.email,
      windowStart: previousSnapshot?.windowStart ?? startDate,
      windowEnd: previousSnapshot?.windowEnd ?? endDate,
      lastSuccessfulSyncAt: previousSnapshot?.lastSuccessfulSyncAt,
      lastAttemptAt: now,
      lastSyncResult: _mapSyncResult(error),
      tasks: previousSnapshot?.tasks ?? const [],
    );
  }

  SyncResultStatus _mapSyncResult(ApiException error) {
    switch (error.type) {
      case ApiErrorType.networkUnavailable:
        return SyncResultStatus.networkUnavailable;
      case ApiErrorType.serverUnreachable:
        return SyncResultStatus.serverUnreachable;
      case ApiErrorType.notAuthenticated:
      case ApiErrorType.invalidToken:
      case ApiErrorType.sessionExpired:
      case ApiErrorType.approvalPending:
      case ApiErrorType.registrationRejected:
      case ApiErrorType.invalidCredentials:
      case ApiErrorType.forbidden:
        return SyncResultStatus.authRequired;
      case ApiErrorType.invalidRequest:
      case ApiErrorType.validationError:
      case ApiErrorType.notFound:
        return SyncResultStatus.validationError;
      case ApiErrorType.serverError:
        return SyncResultStatus.serverError;
      case ApiErrorType.unknown:
        return SyncResultStatus.unknownError;
    }
  }

  DateTime _dateOnly(DateTime value) {
    final utc = value.toUtc();
    return DateTime.utc(utc.year, utc.month, utc.day);
  }
}
