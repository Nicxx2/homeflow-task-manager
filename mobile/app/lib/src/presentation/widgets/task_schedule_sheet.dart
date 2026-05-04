import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../application/app_controller.dart';
import '../../core/date_display.dart';
import '../../core/models/mobile_task.dart';
import '../../core/models/task_schedule_feedback.dart';

Future<void> showTaskScheduleSheet(
  BuildContext context, {
  required MobileTask task,
}) {
  return showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    useSafeArea: true,
    builder: (_) => ChangeNotifierProvider<AppController>.value(
      value: context.read<AppController>(),
      child: _TaskScheduleSheet(task: task),
    ),
  );
}

class _TaskScheduleSheet extends StatefulWidget {
  const _TaskScheduleSheet({required this.task});

  final MobileTask task;

  @override
  State<_TaskScheduleSheet> createState() => _TaskScheduleSheetState();
}

class _TaskScheduleSheetState extends State<_TaskScheduleSheet> {
  late DateTime _dueDate;
  late DateTime _assignmentDate;
  late DateTime? _originalAssignmentDate;
  late DateTime _originalDueDate;
  TaskScheduleFeedback? _feedback;
  String? _message;
  bool _checking = false;
  bool _saving = false;
  bool _loadingNext = false;
  bool _userPickedAssignmentDate = false;
  bool _extendCapacity = false;

  @override
  void initState() {
    super.initState();
    _originalDueDate = _dateOnly(widget.task.dueDate);
    _originalAssignmentDate = widget.task.assignmentDate == null
        ? null
        : _dateOnly(widget.task.assignmentDate!);
    _dueDate = _originalDueDate;
    _assignmentDate = _originalAssignmentDate ?? _today();
  }

  @override
  Widget build(BuildContext context) {
    final controller = context.watch<AppController>();
    final bottomInset = MediaQuery.viewInsetsOf(context).bottom;
    final bottomSafeArea = MediaQuery.viewPaddingOf(context).bottom;
    final bottomPadding = 16 + (bottomInset > 0 ? bottomInset : bottomSafeArea);
    return SafeArea(
      top: false,
      child: LayoutBuilder(
        builder: (context, _) {
          return SingleChildScrollView(
            padding: EdgeInsets.fromLTRB(16, 12, 16, bottomPadding),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    const Icon(Icons.calendar_today_outlined, size: 20),
                    const SizedBox(width: 10),
                    Expanded(
                      child: Text(
                        'Dates',
                        style: Theme.of(context).textTheme.titleMedium,
                      ),
                    ),
                    IconButton(
                      onPressed:
                          _saving ? null : () => Navigator.of(context).pop(),
                      icon: const Icon(Icons.close),
                      tooltip: 'Close',
                    ),
                  ],
                ),
                const SizedBox(height: 8),
                Text(
                  widget.task.title,
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: Theme.of(context).textTheme.bodyMedium,
                ),
                const SizedBox(height: 16),
                _DateField(
                  label: 'Due',
                  value: _dueDate,
                  onPressed: _saving ? null : () => _pickDueDate(context),
                ),
                const SizedBox(height: 10),
                _DateField(
                  label: 'Assigned',
                  value: _assignmentDate,
                  onPressed:
                      _saving ? null : () => _pickAssignmentDate(context),
                ),
                const SizedBox(height: 12),
                Wrap(
                  spacing: 8,
                  runSpacing: 8,
                  children: [
                    OutlinedButton(
                      onPressed: _saving ? null : _useDueDate,
                      child: const Text('Use due date'),
                    ),
                    OutlinedButton.icon(
                      onPressed:
                          _saving || _loadingNext ? null : _useNextAvailable,
                      icon: _loadingNext
                          ? const SizedBox(
                              width: 14,
                              height: 14,
                              child: CircularProgressIndicator(strokeWidth: 2),
                            )
                          : const Icon(Icons.event_available_outlined,
                              size: 18),
                      label: const Text('Next free'),
                    ),
                  ],
                ),
                const SizedBox(height: 12),
                _ScheduleFeedbackCard(
                  feedback: _feedback,
                  message: _message,
                  checking: _checking,
                ),
                if (_canExtendCapacity(_feedback)) ...[
                  const SizedBox(height: 8),
                  SwitchListTile(
                    contentPadding: EdgeInsets.zero,
                    dense: true,
                    title: const Text('Extend capacity'),
                    subtitle: Text(_extendCapacityLabel(_feedback)),
                    value: _extendCapacity,
                    onChanged: _saving
                        ? null
                        : (value) {
                            setState(() {
                              _extendCapacity = value;
                            });
                          },
                  ),
                ],
                const SizedBox(height: 16),
                Row(
                  children: [
                    Expanded(
                      child: OutlinedButton(
                        onPressed:
                            _saving ? null : () => Navigator.of(context).pop(),
                        child: const Text('Cancel'),
                      ),
                    ),
                    const SizedBox(width: 12),
                    Expanded(
                      child: FilledButton(
                        onPressed: _saving ||
                                !controller.canChangeTaskSchedule ||
                                !_canSaveSchedule()
                            ? null
                            : _save,
                        child: _saving
                            ? const SizedBox(
                                width: 18,
                                height: 18,
                                child:
                                    CircularProgressIndicator(strokeWidth: 2),
                              )
                            : const Text('Save'),
                      ),
                    ),
                  ],
                ),
              ],
            ),
          );
        },
      ),
    );
  }

  Future<void> _pickDueDate(BuildContext context) async {
    final selected = await showDatePicker(
      context: context,
      initialDate: _dueDate.toLocal(),
      firstDate: DateTime(1900),
      lastDate: DateTime(2100),
    );
    if (selected == null) {
      return;
    }
    setState(() {
      _dueDate = _dateOnly(selected);
      _message = null;
    });
  }

  Future<void> _pickAssignmentDate(BuildContext context) async {
    final selected = await showDatePicker(
      context: context,
      initialDate: _assignmentDate.isBefore(_today())
          ? _today().toLocal()
          : _assignmentDate.toLocal(),
      firstDate: _today().toLocal(),
      lastDate: DateTime(2100),
    );
    if (selected == null) {
      return;
    }
    setState(() {
      _assignmentDate = _dateOnly(selected);
      _userPickedAssignmentDate = true;
      _message = null;
      _extendCapacity = false;
      if (!_assignmentNeedsValidation()) {
        _feedback = null;
      }
    });
    if (_assignmentNeedsValidation()) {
      await _checkSchedule();
    }
  }

  void _useDueDate() {
    final today = _today();
    final nextAssignmentDate = _dueDate.isBefore(today) ? today : _dueDate;
    setState(() {
      _assignmentDate = nextAssignmentDate;
      _userPickedAssignmentDate = true;
      _message = _dueDate.isBefore(today) ? 'Moved to today.' : null;
      _extendCapacity = false;
      if (!_assignmentNeedsValidation()) {
        _feedback = null;
      }
    });
    if (_assignmentNeedsValidation()) {
      _checkSchedule();
    }
  }

  Future<void> _useNextAvailable() async {
    setState(() {
      _loadingNext = true;
      _message = null;
    });
    final startDate = _userPickedAssignmentDate
        ? _assignmentDate.add(const Duration(days: 1))
        : _today().add(const Duration(days: 1));
    final result =
        await context.read<AppController>().fetchNextAvailableAssignmentDate(
              taskId: widget.task.id,
              startDate: startDate,
            );
    if (!mounted) {
      return;
    }
    setState(() {
      _loadingNext = false;
      if (result?.ok == true && result?.assignmentDate != null) {
        _assignmentDate = _dateOnly(result!.assignmentDate!);
        _userPickedAssignmentDate = true;
        _extendCapacity = false;
      }
      _message = result?.ok == true
          ? 'Next free selected.'
          : result?.message ?? 'Next free day could not be loaded.';
    });
    if (result?.ok == true) {
      await _checkSchedule();
    }
  }

  Future<void> _checkSchedule() async {
    if (!mounted) {
      return;
    }
    setState(() {
      _checking = true;
    });
    final controller = context.read<AppController>();
    final feedback = await controller.checkTaskSchedule(
      taskId: widget.task.id,
      assignmentDate: _assignmentDate,
    );
    if (!mounted) {
      return;
    }
    setState(() {
      _feedback = feedback;
      if (feedback == null) {
        _message = controller.errorMessage ?? 'Schedule could not be checked.';
      }
      if (!_canExtendCapacity(feedback)) {
        _extendCapacity = false;
      }
      _checking = false;
    });
  }

  Future<void> _save() async {
    final today = _today();
    if (_assignmentDate.isBefore(today)) {
      setState(() {
        _message = 'Assignment date cannot be in the past.';
      });
      return;
    }
    setState(() {
      _saving = true;
      _message = null;
    });
    final controller = context.read<AppController>();
    final saved = await controller.updateTaskSchedule(
      taskId: widget.task.id,
      dueDate: _dueDate,
      assignmentDate: _assignmentDate,
      extendCapacity: _extendCapacity,
    );
    if (!mounted) {
      return;
    }
    setState(() {
      _saving = false;
      if (!saved) {
        _message = controller.errorMessage ?? 'Dates could not be saved.';
      }
    });
    if (saved) {
      Navigator.of(context).pop();
    }
  }

  DateTime _today() {
    final now = DateTime.now();
    return DateTime.utc(now.year, now.month, now.day);
  }

  DateTime _dateOnly(DateTime value) {
    return DateTime.utc(value.year, value.month, value.day);
  }

  bool _canExtendCapacity(TaskScheduleFeedback? feedback) {
    final capacity = feedback?.capacity;
    final projected = feedback?.projectedPoints;
    return feedback != null &&
        !feedback.valid &&
        capacity != null &&
        projected != null &&
        projected > capacity &&
        !feedback.isPastDate &&
        !feedback.blockedByPolicy;
  }

  bool _canSaveSchedule() {
    if (_checking || !_hasChanges() || _assignmentDate.isBefore(_today())) {
      return false;
    }
    if (!_assignmentNeedsValidation()) {
      return true;
    }
    final feedback = _feedback;
    if (feedback == null) {
      return false;
    }
    if (feedback.valid) {
      return true;
    }
    return _extendCapacity && _canExtendCapacity(feedback);
  }

  bool _hasChanges() {
    return !_isSameDate(_dueDate, _originalDueDate) ||
        !_isSameNullableDate(_assignmentDate, _originalAssignmentDate);
  }

  bool _assignmentNeedsValidation() {
    return !_isSameNullableDate(_assignmentDate, _originalAssignmentDate);
  }

  bool _isSameNullableDate(DateTime? left, DateTime? right) {
    if (left == null || right == null) {
      return left == right;
    }
    return _isSameDate(left, right);
  }

  bool _isSameDate(DateTime left, DateTime right) {
    return left.year == right.year &&
        left.month == right.month &&
        left.day == right.day;
  }

  String _extendCapacityLabel(TaskScheduleFeedback? feedback) {
    final capacity = feedback?.capacity;
    final projected = feedback?.projectedPoints;
    if (capacity == null || projected == null || projected <= capacity) {
      return 'Add room for this day';
    }
    return 'Add +${projected - capacity} pts for this day';
  }
}

class _DateField extends StatelessWidget {
  const _DateField({
    required this.label,
    required this.value,
    required this.onPressed,
  });

  final String label;
  final DateTime value;
  final VoidCallback? onPressed;

  @override
  Widget build(BuildContext context) {
    return OutlinedButton(
      onPressed: onPressed,
      style: OutlinedButton.styleFrom(
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
      ),
      child: Row(
        children: [
          SizedBox(
            width: 78,
            child: Text(label, style: Theme.of(context).textTheme.labelLarge),
          ),
          Expanded(
            child: Text(
              formatDateOnlyLabel(value, 'EEE, dd MMM yyyy'),
              textAlign: TextAlign.right,
            ),
          ),
        ],
      ),
    );
  }
}

class _ScheduleFeedbackCard extends StatelessWidget {
  const _ScheduleFeedbackCard({
    required this.feedback,
    required this.message,
    required this.checking,
  });

  final TaskScheduleFeedback? feedback;
  final String? message;
  final bool checking;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final feedback = this.feedback;
    if (!checking && feedback == null && message == null) {
      return const SizedBox.shrink();
    }
    final text = checking
        ? 'Checking...'
        : message ?? feedback?.message ?? 'Choose an assignment date.';
    final valid = feedback?.valid == true;
    final background = checking
        ? scheme.surfaceContainerHighest
        : valid
            ? scheme.tertiaryContainer
            : scheme.errorContainer;
    final foreground = checking
        ? scheme.onSurfaceVariant
        : valid
            ? scheme.onTertiaryContainer
            : scheme.onErrorContainer;
    final capacity = feedback?.capacity;
    final projected = feedback?.projectedPoints;

    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: background,
        borderRadius: BorderRadius.circular(12),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(text, style: TextStyle(color: foreground)),
          if (capacity != null && projected != null) ...[
            const SizedBox(height: 4),
            Text(
              '$projected / $capacity pts',
              style: Theme.of(
                context,
              ).textTheme.labelMedium?.copyWith(color: foreground),
            ),
          ],
        ],
      ),
    );
  }
}
