import 'date_codec.dart';

class TaskNextAvailableResult {
  const TaskNextAvailableResult({
    required this.ok,
    required this.message,
    required this.assignmentDate,
  });

  factory TaskNextAvailableResult.fromJson(Map<String, dynamic> json) {
    return TaskNextAvailableResult(
      ok: json['ok'] as bool? ?? false,
      message: json['message'] as String? ?? 'No next available day found.',
      assignmentDate: json['assignment_date'] == null
          ? null
          : parseDateOnly(json['assignment_date'] as String),
    );
  }

  final bool ok;
  final String message;
  final DateTime? assignmentDate;
}
