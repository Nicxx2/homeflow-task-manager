import 'mobile_task.dart';

class PendingStatusUpdate {
  const PendingStatusUpdate({
    required this.taskId,
    required this.status,
    required this.updatedAt,
  });

  factory PendingStatusUpdate.fromJson(Map<String, dynamic> json) {
    return PendingStatusUpdate(
      taskId: json['taskId'] as int,
      status: MobileTaskStatus.fromValue(json['status'] as String),
      updatedAt: DateTime.parse(json['updatedAt'] as String).toUtc(),
    );
  }

  final int taskId;
  final MobileTaskStatus status;
  final DateTime updatedAt;

  Map<String, dynamic> toJson() {
    return <String, dynamic>{
      'taskId': taskId,
      'status': status.value,
      'updatedAt': updatedAt.toIso8601String(),
    };
  }
}
