enum TodayWidgetState {
  signedOut,
  noCache,
  ready,
  stale,
  authRequired,
  empty,
  error;

  static TodayWidgetState fromValue(String? value) {
    return TodayWidgetState.values.firstWhere(
      (state) => state.name == value,
      orElse: () => TodayWidgetState.noCache,
    );
  }
}

class TodayWidgetSnapshot {
  const TodayWidgetSnapshot({
    required this.state,
    required this.title,
    required this.subtitle,
    required this.taskCount,
    required this.taskTitles,
    required this.isStale,
    required this.actionRoute,
    required this.generatedAt,
    required this.lastSuccessfulSyncAt,
    required this.userEmail,
  });

  factory TodayWidgetSnapshot.fromJson(Map<String, dynamic> json) {
    final rawTitles =
        json['task_titles'] as List<dynamic>? ?? const <dynamic>[];
    return TodayWidgetSnapshot(
      state: TodayWidgetState.fromValue(json['state'] as String?),
      title: json['title'] as String? ?? 'Today',
      subtitle: json['subtitle'] as String? ?? '',
      taskCount: json['task_count'] as int? ?? 0,
      taskTitles: rawTitles
          .map((item) => item as String)
          .toList(growable: false),
      isStale: json['is_stale'] as bool? ?? false,
      actionRoute: json['action_route'] as String? ?? '/',
      generatedAt: DateTime.parse(json['generated_at'] as String).toUtc(),
      lastSuccessfulSyncAt: json['last_successful_sync_at'] == null
          ? null
          : DateTime.parse(json['last_successful_sync_at'] as String).toUtc(),
      userEmail: json['user_email'] as String?,
    );
  }

  final TodayWidgetState state;
  final String title;
  final String subtitle;
  final int taskCount;
  final List<String> taskTitles;
  final bool isStale;
  final String actionRoute;
  final DateTime generatedAt;
  final DateTime? lastSuccessfulSyncAt;
  final String? userEmail;

  Map<String, dynamic> toJson() {
    return <String, dynamic>{
      'state': state.name,
      'title': title,
      'subtitle': subtitle,
      'task_count': taskCount,
      'task_titles': taskTitles,
      'is_stale': isStale,
      'action_route': actionRoute,
      'generated_at': generatedAt.toIso8601String(),
      'last_successful_sync_at': lastSuccessfulSyncAt?.toIso8601String(),
      'user_email': userEmail,
    };
  }
}
