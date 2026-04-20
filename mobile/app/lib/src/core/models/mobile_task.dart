import 'date_codec.dart';

enum MobileTaskStatus {
  pending('pending', 'Pending'),
  inProgress('in_progress', 'In progress'),
  completed('completed', 'Completed');

  const MobileTaskStatus(this.value, this.label);

  final String value;
  final String label;

  static MobileTaskStatus fromValue(String value) {
    return MobileTaskStatus.values.firstWhere(
      (status) => status.value == value,
      orElse: () => MobileTaskStatus.pending,
    );
  }
}

enum EffortLevel {
  low('low'),
  medium('medium'),
  high('high');

  const EffortLevel(this.value);

  final String value;

  static EffortLevel fromValue(String value) {
    return EffortLevel.values.firstWhere(
      (level) => level.value == value,
      orElse: () => EffortLevel.medium,
    );
  }
}

class MobileTask {
  const MobileTask({
    required this.id,
    required this.title,
    required this.description,
    required this.status,
    required this.dueDate,
    required this.assignmentDate,
    required this.assigneeId,
    required this.effortLevel,
    required this.pointsValue,
    required this.updatedAt,
    required this.isOverdue,
    required this.isCompleted,
    required this.displayBucket,
    required this.sortKey,
    required this.recurrenceParentId,
    required this.recurrenceSummary,
  });

  factory MobileTask.fromJson(Map<String, dynamic> json) {
    return MobileTask(
      id: json['id'] as int,
      title: json['title'] as String,
      description: json['description'] as String,
      status: MobileTaskStatus.fromValue(json['status'] as String),
      dueDate: parseDateOnly(json['due_date'] as String),
      assignmentDate: json['assignment_date'] == null
          ? null
          : parseDateOnly(json['assignment_date'] as String),
      assigneeId: json['assignee_id'] as int?,
      effortLevel: EffortLevel.fromValue(json['effort_level'] as String),
      pointsValue: json['points_value'] as int,
      updatedAt: DateTime.parse(json['updated_at'] as String).toUtc(),
      isOverdue: json['is_overdue'] as bool? ?? false,
      isCompleted: json['is_completed'] as bool? ?? false,
      displayBucket: json['display_bucket'] as String? ?? 'today',
      sortKey: json['sort_key'] as String? ?? '',
      recurrenceParentId: json['recurrence_parent_id'] as int?,
      recurrenceSummary: json['recurrence_summary'] as String?,
    );
  }

  final int id;
  final String title;
  final String description;
  final MobileTaskStatus status;
  final DateTime dueDate;
  final DateTime? assignmentDate;
  final int? assigneeId;
  final EffortLevel effortLevel;
  final int pointsValue;
  final DateTime updatedAt;
  final bool isOverdue;
  final bool isCompleted;
  final String displayBucket;
  final String sortKey;
  final int? recurrenceParentId;
  final String? recurrenceSummary;

  Map<String, dynamic> toJson() {
    return <String, dynamic>{
      'id': id,
      'title': title,
      'description': description,
      'status': status.value,
      'due_date': formatDateOnly(dueDate),
      'assignment_date': assignmentDate == null
          ? null
          : formatDateOnly(assignmentDate!),
      'assignee_id': assigneeId,
      'effort_level': effortLevel.value,
      'points_value': pointsValue,
      'updated_at': updatedAt.toIso8601String(),
      'is_overdue': isOverdue,
      'is_completed': isCompleted,
      'display_bucket': displayBucket,
      'sort_key': sortKey,
      'recurrence_parent_id': recurrenceParentId,
      'recurrence_summary': recurrenceSummary,
    };
  }
}
