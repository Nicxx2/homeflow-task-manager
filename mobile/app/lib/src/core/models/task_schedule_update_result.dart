import 'mobile_task.dart';
import 'task_schedule_feedback.dart';

class TaskScheduleUpdateResult {
  const TaskScheduleUpdateResult({
    required this.serverTime,
    required this.task,
    required this.feedback,
  });

  factory TaskScheduleUpdateResult.fromJson(Map<String, dynamic> json) {
    return TaskScheduleUpdateResult(
      serverTime: DateTime.parse(json['server_time'] as String).toUtc(),
      task: MobileTask.fromJson(json['task'] as Map<String, dynamic>),
      feedback: TaskScheduleFeedback.fromJson(
        json['feedback'] as Map<String, dynamic>,
      ),
    );
  }

  final DateTime serverTime;
  final MobileTask task;
  final TaskScheduleFeedback feedback;
}
