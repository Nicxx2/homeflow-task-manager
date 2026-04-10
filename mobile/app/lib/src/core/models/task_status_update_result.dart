import 'mobile_task.dart';

class TaskStatusUpdateResult {
  const TaskStatusUpdateResult({
    required this.refreshRequired,
    required this.task,
  });

  final bool refreshRequired;
  final MobileTask? task;
}
