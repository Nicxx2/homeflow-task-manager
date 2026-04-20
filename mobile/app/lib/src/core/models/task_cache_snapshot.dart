import 'mobile_task.dart';
import 'date_codec.dart';

enum SyncResultStatus {
  neverSynced,
  success,
  networkUnavailable,
  serverUnreachable,
  authRequired,
  serverError,
  validationError,
  unknownError;

  static SyncResultStatus fromValue(String? value) {
    return SyncResultStatus.values.firstWhere(
      (status) => status.name == value,
      orElse: () => SyncResultStatus.neverSynced,
    );
  }
}

class TaskCacheSnapshot {
  const TaskCacheSnapshot({
    required this.serverBaseUrl,
    required this.userEmail,
    required this.windowStart,
    required this.windowEnd,
    required this.lastSuccessfulSyncAt,
    required this.lastAttemptAt,
    required this.lastSyncResult,
    required this.tasks,
  });

  factory TaskCacheSnapshot.fromJson(Map<String, dynamic> json) {
    final rawTasks = json['tasks'] as List<dynamic>? ?? const <dynamic>[];
    return TaskCacheSnapshot(
      serverBaseUrl: json['serverBaseUrl'] as String,
      userEmail: json['userEmail'] as String,
      windowStart: parseDateOnly(json['windowStart'] as String),
      windowEnd: parseDateOnly(json['windowEnd'] as String),
      lastSuccessfulSyncAt: json['lastSuccessfulSyncAt'] == null
          ? null
          : DateTime.parse(json['lastSuccessfulSyncAt'] as String).toUtc(),
      lastAttemptAt: json['lastAttemptAt'] == null
          ? null
          : DateTime.parse(json['lastAttemptAt'] as String).toUtc(),
      lastSyncResult: SyncResultStatus.fromValue(
        json['lastSyncResult'] as String?,
      ),
      tasks: rawTasks
          .map((item) => MobileTask.fromJson(item as Map<String, dynamic>))
          .toList(growable: false),
    );
  }

  final String serverBaseUrl;
  final String userEmail;
  final DateTime windowStart;
  final DateTime windowEnd;
  final DateTime? lastSuccessfulSyncAt;
  final DateTime? lastAttemptAt;
  final SyncResultStatus lastSyncResult;
  final List<MobileTask> tasks;

  Map<String, dynamic> toJson() {
    return <String, dynamic>{
      'serverBaseUrl': serverBaseUrl,
      'userEmail': userEmail,
      'windowStart': formatDateOnly(windowStart),
      'windowEnd': formatDateOnly(windowEnd),
      'lastSuccessfulSyncAt': lastSuccessfulSyncAt?.toIso8601String(),
      'lastAttemptAt': lastAttemptAt?.toIso8601String(),
      'lastSyncResult': lastSyncResult.name,
      'tasks': tasks.map((task) => task.toJson()).toList(growable: false),
    };
  }

  TaskCacheSnapshot copyWith({
    String? serverBaseUrl,
    String? userEmail,
    DateTime? windowStart,
    DateTime? windowEnd,
    DateTime? lastSuccessfulSyncAt,
    DateTime? lastAttemptAt,
    SyncResultStatus? lastSyncResult,
    List<MobileTask>? tasks,
  }) {
    return TaskCacheSnapshot(
      serverBaseUrl: serverBaseUrl ?? this.serverBaseUrl,
      userEmail: userEmail ?? this.userEmail,
      windowStart: windowStart ?? this.windowStart,
      windowEnd: windowEnd ?? this.windowEnd,
      lastSuccessfulSyncAt: lastSuccessfulSyncAt ?? this.lastSuccessfulSyncAt,
      lastAttemptAt: lastAttemptAt ?? this.lastAttemptAt,
      lastSyncResult: lastSyncResult ?? this.lastSyncResult,
      tasks: tasks ?? this.tasks,
    );
  }
}
