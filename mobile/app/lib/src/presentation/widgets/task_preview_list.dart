import 'package:flutter/material.dart';

import '../../core/date_display.dart';
import '../../core/models/mobile_task.dart';

class TaskPreviewList extends StatelessWidget {
  const TaskPreviewList({
    required this.tasks,
    required this.emptyMessage,
    this.onTaskTap,
    this.onStatusSelected,
    this.isUpdatingTask,
    this.showAssignmentDate = false,
    this.showDisplayBucketChip = false,
    super.key,
  });

  final List<MobileTask> tasks;
  final String emptyMessage;
  final ValueChanged<MobileTask>? onTaskTap;
  final Future<void> Function(MobileTask task, MobileTaskStatus status)?
  onStatusSelected;
  final bool Function(int taskId)? isUpdatingTask;
  final bool showAssignmentDate;
  final bool showDisplayBucketChip;

  @override
  Widget build(BuildContext context) {
    if (tasks.isEmpty) {
      return Padding(
        padding: const EdgeInsets.symmetric(vertical: 16),
        child: Text(
          emptyMessage,
          style: Theme.of(context).textTheme.bodyMedium,
        ),
      );
    }

    return Column(
      children: tasks
          .map((task) {
            final updating = isUpdatingTask?.call(task.id) ?? false;
            final subtitleParts = <String>[
              task.status.label,
              if (showAssignmentDate && task.assignmentDate != null)
                'assigned ${formatDateOnlyLabel(task.assignmentDate!, 'dd MMM')}',
              'due ${formatDateOnlyLabel(task.dueDate, 'dd MMM')}',
            ];
            return Card(
              margin: const EdgeInsets.only(bottom: 10),
              child: ListTile(
                onTap: onTaskTap == null ? null : () => onTaskTap!(task),
                title: Text(task.title),
                subtitle: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const SizedBox(height: 4),
                    Text(subtitleParts.join(' - ')),
                    const SizedBox(height: 6),
                    Wrap(
                      spacing: 8,
                      runSpacing: 4,
                      children: [
                        _TaskChip(label: '${task.pointsValue} pts'),
                        if (showDisplayBucketChip)
                          _TaskChip(label: task.displayBucket),
                        if (task.recurrenceSummary != null)
                          _TaskChip(label: task.recurrenceSummary!),
                      ],
                    ),
                  ],
                ),
                trailing: updating
                    ? const SizedBox(
                        width: 20,
                        height: 20,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      )
                    : onStatusSelected == null
                    ? Text('${task.pointsValue} pts')
                    : PopupMenuButton<MobileTaskStatus>(
                        tooltip: 'Change status',
                        onSelected: (status) => onStatusSelected!(task, status),
                        itemBuilder: (context) => MobileTaskStatus.values
                            .map(
                              (status) => PopupMenuItem(
                                value: status,
                                child: Text(status.label),
                              ),
                            )
                            .toList(growable: false),
                        child: const Icon(Icons.more_horiz),
                      ),
              ),
            );
          })
          .toList(growable: false),
    );
  }
}

class _TaskChip extends StatelessWidget {
  const _TaskChip({required this.label});

  final String label;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
      decoration: BoxDecoration(
        color: Theme.of(context).colorScheme.surfaceContainerHighest,
        borderRadius: BorderRadius.circular(999),
      ),
      child: Text(label, style: Theme.of(context).textTheme.labelSmall),
    );
  }
}
