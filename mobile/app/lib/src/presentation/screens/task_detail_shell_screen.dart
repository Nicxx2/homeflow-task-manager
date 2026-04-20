import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import 'package:provider/provider.dart';

import '../../application/app_controller.dart';
import '../../core/date_display.dart';
import '../../core/models/mobile_task.dart';
import '../widgets/sync_status_strip.dart';

class TaskDetailShellScreen extends StatelessWidget {
  const TaskDetailShellScreen({super.key});

  static const String routeName = '/task-detail';

  @override
  Widget build(BuildContext context) {
    final taskId = ModalRoute.of(context)?.settings.arguments as int?;
    final controller = context.watch<AppController>();
    final task = taskId == null ? null : controller.taskById(taskId);
    final isUpdating = taskId != null && controller.isUpdatingTask(taskId);

    return Scaffold(
      appBar: AppBar(
        title: const Text('Task detail'),
        actions: [
          if (controller.isSyncing)
            const Padding(
              padding: EdgeInsets.only(right: 20),
              child: SizedBox(
                width: 18,
                height: 18,
                child: CircularProgressIndicator(strokeWidth: 2.2),
              ),
            )
          else
            IconButton(
              onPressed:
                  controller.canRetrySync ? controller.refreshTasks : null,
              icon: const Icon(Icons.refresh),
              tooltip: 'Refresh',
            ),
        ],
        bottom: PreferredSize(
          preferredSize: const Size.fromHeight(44),
          child: Padding(
            padding: const EdgeInsets.fromLTRB(16, 0, 16, 12),
            child: SyncStatusStrip(controller: controller),
          ),
        ),
      ),
      body: SafeArea(
        child: task == null
            ? const Padding(
                padding: EdgeInsets.all(16),
                child: Text('Task is not available in the current cache.'),
              )
            : ListView(
                padding: const EdgeInsets.all(16),
                children: [
                  Text(
                    task.title,
                    style: Theme.of(context).textTheme.headlineSmall,
                  ),
                  const SizedBox(height: 12),
                  Text(task.description),
                  const SizedBox(height: 20),
                  Text(
                    'Status',
                    style: Theme.of(context).textTheme.titleMedium,
                  ),
                  const SizedBox(height: 8),
                  if (isUpdating)
                    const LinearProgressIndicator()
                  else
                    Wrap(
                      spacing: 8,
                      runSpacing: 8,
                      children: MobileTaskStatus.values
                          .map(
                            (status) => ChoiceChip(
                              label: Text(status.label),
                              selected: task.status == status,
                              onSelected: controller.canChangeTaskStatus
                                  ? (_) async {
                                      await controller.updateTaskStatus(
                                        taskId: task.id,
                                        status: status,
                                      );
                                    }
                                  : null,
                            ),
                          )
                          .toList(growable: false),
                    ),
                  if (!controller.canChangeTaskStatus) ...[
                    const SizedBox(height: 8),
                    Text(
                      controller.needsReauth
                          ? 'Sign in again before changing task status.'
                          : 'Task status changes are unavailable right now.',
                      style: Theme.of(context).textTheme.bodySmall,
                    ),
                  ],
                  const SizedBox(height: 20),
                  _DetailRow(
                    label: 'Due date',
                    value: formatDateOnlyLabel(task.dueDate, 'dd MMM yyyy'),
                  ),
                  _DetailRow(
                    label: 'Assignment',
                    value: task.assignmentDate == null
                        ? 'Not assigned'
                        : formatDateOnlyLabel(
                            task.assignmentDate!,
                            'dd MMM yyyy',
                          ),
                  ),
                  _DetailRow(label: 'Effort', value: task.effortLevel.value),
                  _DetailRow(label: 'Points', value: '${task.pointsValue}'),
                  _DetailRow(label: 'Bucket', value: task.displayBucket),
                  _DetailRow(
                    label: 'Updated',
                    value: DateFormat(
                      'dd MMM yyyy, HH:mm',
                    ).format(task.updatedAt.toLocal()),
                  ),
                  if (task.recurrenceSummary != null)
                    _DetailRow(
                      label: 'Recurrence',
                      value: task.recurrenceSummary!,
                    ),
                  const SizedBox(height: 16),
                  Text(
                    controller.isShowingCachedData
                        ? 'Showing cached task data from your last sync.'
                        : 'This task reflects the latest successful sync.',
                    style: Theme.of(context).textTheme.bodySmall,
                  ),
                ],
              ),
      ),
    );
  }
}

class _DetailRow extends StatelessWidget {
  const _DetailRow({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 110,
            child: Text(
              label,
              style: Theme.of(
                context,
              ).textTheme.bodyMedium?.copyWith(fontWeight: FontWeight.w600),
            ),
          ),
          Expanded(child: Text(value)),
        ],
      ),
    );
  }
}
