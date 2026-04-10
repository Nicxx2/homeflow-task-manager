import 'mobile_task.dart';
import 'date_codec.dart';

class RemoteTaskWindow {
  const RemoteTaskWindow({
    required this.serverTime,
    required this.windowStart,
    required this.windowEnd,
    required this.tasks,
  });

  factory RemoteTaskWindow.fromJson(Map<String, dynamic> json) {
    final rawTasks = json['tasks'] as List<dynamic>? ?? const <dynamic>[];
    return RemoteTaskWindow(
      serverTime: DateTime.parse(json['server_time'] as String).toUtc(),
      windowStart: parseDateOnly(json['window_start'] as String),
      windowEnd: parseDateOnly(json['window_end'] as String),
      tasks: rawTasks
          .map((item) => MobileTask.fromJson(item as Map<String, dynamic>))
          .toList(growable: false),
    );
  }

  final DateTime serverTime;
  final DateTime windowStart;
  final DateTime windowEnd;
  final List<MobileTask> tasks;
}
