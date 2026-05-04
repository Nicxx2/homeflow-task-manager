import 'package:flutter/material.dart';

import '../../core/date_display.dart';
import '../../core/models/mobile_task.dart';

class TaskPreviewList extends StatelessWidget {
  const TaskPreviewList({
    required this.tasks,
    required this.emptyMessage,
    this.onTaskTap,
    this.onScheduleTap,
    this.onStatusSelected,
    this.isUpdatingTask,
    this.isStatusPending,
    this.showAssignmentDate = false,
    this.showDisplayBucketChip = false,
    this.showMetadata = true,
    this.showMinimalOverdueChip = false,
    super.key,
  });

  final List<MobileTask> tasks;
  final String emptyMessage;
  final ValueChanged<MobileTask>? onTaskTap;
  final ValueChanged<MobileTask>? onScheduleTap;
  final Future<void> Function(MobileTask task, MobileTaskStatus status)?
      onStatusSelected;
  final bool Function(int taskId)? isUpdatingTask;
  final bool Function(int taskId)? isStatusPending;
  final bool showAssignmentDate;
  final bool showDisplayBucketChip;
  final bool showMetadata;
  final bool showMinimalOverdueChip;

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
      children: tasks.map((task) {
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
            subtitle: _TaskSubtitle(
              task: task,
              subtitle: subtitleParts.join(' - '),
              showMetadata: showMetadata,
              showMinimalOverdueChip: showMinimalOverdueChip,
              showDisplayBucketChip: showDisplayBucketChip,
              isStatusPending: isStatusPending?.call(task.id) ?? false,
            ),
            trailing: _TaskActions(
              task: task,
              updating: updating,
              onScheduleTap: onScheduleTap,
              onStatusSelected: onStatusSelected,
            ),
          ),
        );
      }).toList(growable: false),
    );
  }
}

class _TaskSubtitle extends StatelessWidget {
  const _TaskSubtitle({
    required this.task,
    required this.subtitle,
    required this.showMetadata,
    required this.showMinimalOverdueChip,
    required this.showDisplayBucketChip,
    required this.isStatusPending,
  });

  final MobileTask task;
  final String subtitle;
  final bool showMetadata;
  final bool showMinimalOverdueChip;
  final bool showDisplayBucketChip;
  final bool isStatusPending;

  @override
  Widget build(BuildContext context) {
    if (!showMetadata && !(showMinimalOverdueChip && task.isOverdue)) {
      return const SizedBox.shrink();
    }

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        if (showMetadata) ...[
          const SizedBox(height: 4),
          Text(subtitle),
          const SizedBox(height: 6),
        ] else
          const SizedBox(height: 6),
        Wrap(
          spacing: 8,
          runSpacing: 4,
          children: [
            if (showMetadata) _TaskChip(label: '${task.pointsValue} pts'),
            if (task.isOverdue) const _TaskChip(label: 'overdue'),
            if (showMetadata && isStatusPending)
              const _TaskChip(label: 'pending sync'),
            if (showMetadata && showDisplayBucketChip)
              _TaskChip(label: task.displayBucket),
            if (showMetadata && task.recurrenceSummary != null)
              _TaskChip(label: task.recurrenceSummary!),
          ],
        ),
      ],
    );
  }
}

class _TaskActions extends StatelessWidget {
  const _TaskActions({
    required this.task,
    required this.updating,
    required this.onScheduleTap,
    required this.onStatusSelected,
  });

  final MobileTask task;
  final bool updating;
  final ValueChanged<MobileTask>? onScheduleTap;
  final Future<void> Function(MobileTask task, MobileTaskStatus status)?
      onStatusSelected;

  @override
  Widget build(BuildContext context) {
    if (updating) {
      return const SizedBox(
        width: 20,
        height: 20,
        child: CircularProgressIndicator(strokeWidth: 2),
      );
    }

    final actions = <Widget>[
      if (onScheduleTap != null && !task.isCompleted)
        IconButton(
          visualDensity: VisualDensity.compact,
          tooltip: 'Adjust dates',
          onPressed: () => onScheduleTap!(task),
          icon: const Icon(Icons.calendar_today_outlined),
        ),
      if (onStatusSelected != null)
        PopupMenuButton<MobileTaskStatus>(
          tooltip: 'Change status',
          onSelected: (status) => onStatusSelected!(task, status),
          itemBuilder: (context) => MobileTaskStatus.values
              .map(
                (status) =>
                    PopupMenuItem(value: status, child: Text(status.label)),
              )
              .toList(growable: false),
          child: const Icon(Icons.more_horiz),
        ),
    ];

    if (actions.isEmpty) {
      return Text('${task.pointsValue} pts');
    }

    return Row(mainAxisSize: MainAxisSize.min, children: actions);
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
