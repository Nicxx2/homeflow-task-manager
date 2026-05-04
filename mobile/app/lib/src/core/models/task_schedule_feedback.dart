import 'date_codec.dart';

class TaskScheduleFeedback {
  const TaskScheduleFeedback({
    required this.valid,
    required this.message,
    required this.date,
    required this.taskPoints,
    required this.currentPoints,
    required this.projectedPoints,
    required this.capacity,
    required this.isPastDate,
    required this.taskTooLarge,
    required this.blockedByPolicy,
    required this.nextAvailableDate,
  });

  factory TaskScheduleFeedback.fromJson(Map<String, dynamic> json) {
    return TaskScheduleFeedback(
      valid: json['valid'] as bool? ?? false,
      message: json['message'] as String? ?? 'Schedule could not be checked.',
      date: json['date'] == null ? null : parseDateOnly(json['date'] as String),
      taskPoints: json['task_points'] as int?,
      currentPoints: json['current_points'] as int?,
      projectedPoints: json['projected_points'] as int?,
      capacity: json['capacity'] as int?,
      isPastDate: json['is_past_date'] as bool? ?? false,
      taskTooLarge: json['task_too_large'] as bool? ?? false,
      blockedByPolicy: json['blocked_by_policy'] as bool? ?? false,
      nextAvailableDate: json['next_available_date'] == null
          ? null
          : parseDateOnly(json['next_available_date'] as String),
    );
  }

  final bool valid;
  final String message;
  final DateTime? date;
  final int? taskPoints;
  final int? currentPoints;
  final int? projectedPoints;
  final int? capacity;
  final bool isPastDate;
  final bool taskTooLarge;
  final bool blockedByPolicy;
  final DateTime? nextAvailableDate;
}
