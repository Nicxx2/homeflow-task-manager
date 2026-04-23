import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import 'package:provider/provider.dart';

import '../../application/app_controller.dart';
import '../../core/app_release.dart';
import '../../core/date_display.dart';
import '../../core/models/app_preferences.dart';
import '../../core/models/mobile_task.dart';
import '../widgets/sync_status_strip.dart';
import '../widgets/task_preview_list.dart';
import 'task_detail_shell_screen.dart';

class HomeShellScreen extends StatelessWidget {
  const HomeShellScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return Consumer<AppController>(
      builder: (context, controller, _) {
        final pages = <Widget>[
          const _TodayTab(),
          const _UpcomingTab(),
          const _SettingsTab(),
        ];

        return Scaffold(
          appBar: AppBar(
            title: const Text('Homeflow'),
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
            child: Padding(
              padding: const EdgeInsets.fromLTRB(16, 12, 16, 16),
              child: AnimatedSwitcher(
                duration: const Duration(milliseconds: 180),
                child: KeyedSubtree(
                  key: ValueKey<int>(controller.selectedTabIndex),
                  child: pages[controller.selectedTabIndex],
                ),
              ),
            ),
          ),
          bottomNavigationBar: NavigationBar(
            selectedIndex: controller.selectedTabIndex,
            onDestinationSelected: controller.selectTab,
            destinations: const [
              NavigationDestination(
                icon: Icon(Icons.today_outlined),
                label: 'Today',
              ),
              NavigationDestination(
                icon: Icon(Icons.view_agenda_outlined),
                label: 'Upcoming',
              ),
              NavigationDestination(
                icon: Icon(Icons.settings_outlined),
                label: 'Settings',
              ),
            ],
          ),
        );
      },
    );
  }
}

enum _TodaySection { active, overdue, completed }

class _TodayTab extends StatefulWidget {
  const _TodayTab();

  @override
  State<_TodayTab> createState() => _TodayTabState();
}

class _TodayTabState extends State<_TodayTab> {
  _TodaySection _selectedSection = _TodaySection.active;

  @override
  Widget build(BuildContext context) {
    final controller = context.watch<AppController>();
    final activeTasks = controller.activeTodayTasks;
    final overdueTasks = controller.overdueTasks;
    final completedTasks = controller.completedTodayTasks;
    final showOverdueSection =
        controller.preferences.showOverdueTasksInTodayView &&
        overdueTasks.isNotEmpty;
    final availableSections = <_TodaySection>[
      _TodaySection.active,
      if (showOverdueSection) _TodaySection.overdue,
      _TodaySection.completed,
    ];
    final selectedSection = availableSections.contains(_selectedSection)
        ? _selectedSection
        : _TodaySection.active;
    final visibleTasks = switch (selectedSection) {
      _TodaySection.active => activeTasks,
      _TodaySection.overdue => overdueTasks,
      _TodaySection.completed => completedTasks,
    };
    final now = DateTime.now().toUtc();
    final today = DateTime.utc(now.year, now.month, now.day);
    final emptyMessage = switch (selectedSection) {
      _TodaySection.active => completedTasks.isNotEmpty || overdueTasks.isNotEmpty
          ? 'No active tasks remain for today.'
          : controller.messageForDay(today),
      _TodaySection.overdue => 'No overdue tasks right now.',
      _TodaySection.completed => 'No tasks have been completed today yet.',
    };

    return ListView(
      children: [
        Text('Today', style: Theme.of(context).textTheme.headlineSmall),
        const SizedBox(height: 4),
        Text(
          DateFormat('EEEE, dd MMM').format(DateTime.now()),
          style: Theme.of(context).textTheme.bodyMedium,
        ),
        const SizedBox(height: 16),
        SegmentedButton<_TodaySection>(
          showSelectedIcon: false,
          segments: [
            ButtonSegment<_TodaySection>(
              value: _TodaySection.active,
              label: Text('Active ${activeTasks.length}'),
            ),
            if (showOverdueSection)
              ButtonSegment<_TodaySection>(
                value: _TodaySection.overdue,
                label: Text('Overdue ${overdueTasks.length}'),
              ),
            ButtonSegment<_TodaySection>(
              value: _TodaySection.completed,
              label: Text('Completed ${completedTasks.length}'),
            ),
          ],
          selected: <_TodaySection>{selectedSection},
          onSelectionChanged: (selection) {
            if (selection.isNotEmpty) {
              setState(() {
                _selectedSection = selection.first;
              });
            }
          },
        ),
        const SizedBox(height: 16),
        AnimatedSwitcher(
          duration: const Duration(milliseconds: 180),
          child: TaskPreviewList(
            key: ValueKey<_TodaySection>(selectedSection),
            tasks: visibleTasks,
            emptyMessage: emptyMessage,
            isUpdatingTask: controller.isUpdatingTask,
            onStatusSelected: controller.canChangeTaskStatus
                ? (task, status) async {
                    await controller.updateTaskStatus(
                      taskId: task.id,
                      status: status,
                    );
                  }
                : null,
            onTaskTap: (task) => Navigator.of(
              context,
            ).pushNamed(TaskDetailShellScreen.routeName, arguments: task.id),
          ),
        ),
      ],
    );
  }
}

class _UpcomingTab extends StatelessWidget {
  const _UpcomingTab();

  @override
  Widget build(BuildContext context) {
    final controller = context.watch<AppController>();
    final days = controller.upcomingDays;
    final now = DateTime.now().toUtc();
    final tomorrow = DateTime.utc(
      now.year,
      now.month,
      now.day,
    ).add(const Duration(days: 1));

    return ListView(
      children: [
        Text('Upcoming', style: Theme.of(context).textTheme.headlineSmall),
        const SizedBox(height: 4),
        Text(
          controller.upcomingCoverageMessage(),
          style: Theme.of(context).textTheme.bodyMedium,
        ),
        const SizedBox(height: 16),
        if (days.isEmpty)
          Card(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Text(controller.messageForDay(tomorrow)),
            ),
          ),
        for (var index = 0; index < days.length; index++) ...[
          _UpcomingDayCard(
            day: days[index],
            tasks: controller
                .tasksForDate(days[index])
                .where((task) => task.displayBucket == 'upcoming')
                .toList(growable: false),
            initiallyExpanded: index == 0,
          ),
          const SizedBox(height: 12),
        ],
      ],
    );
  }
}

class _UpcomingDayCard extends StatelessWidget {
  const _UpcomingDayCard({
    required this.day,
    required this.tasks,
    required this.initiallyExpanded,
  });

  final DateTime day;
  final List<MobileTask> tasks;
  final bool initiallyExpanded;

  @override
  Widget build(BuildContext context) {
    final controller = context.watch<AppController>();
    final countLabel = tasks.isEmpty
        ? 'No cached tasks'
        : tasks.length == 1
            ? '1 task'
            : '${tasks.length} tasks';

    return Card(
      child: ExpansionTile(
        tilePadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 2),
        childrenPadding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
        initiallyExpanded: initiallyExpanded && tasks.isNotEmpty,
        title: Text(
          formatDateOnlyLabel(day, 'EEEE, dd MMM'),
          style: Theme.of(context).textTheme.titleMedium,
        ),
        subtitle: Text(countLabel),
        children: [
          TaskPreviewList(
            tasks: tasks,
            emptyMessage: controller.messageForDay(day),
            showAssignmentDate: true,
            isUpdatingTask: controller.isUpdatingTask,
            onStatusSelected: controller.canChangeTaskStatus
                ? (task, status) async {
                    await controller.updateTaskStatus(
                      taskId: task.id,
                      status: status,
                    );
                  }
                : null,
            onTaskTap: (task) => Navigator.of(
              context,
            ).pushNamed(TaskDetailShellScreen.routeName, arguments: task.id),
          ),
        ],
      ),
    );
  }
}

class _SettingsTab extends StatelessWidget {
  const _SettingsTab();

  @override
  Widget build(BuildContext context) {
    final controller = context.watch<AppController>();
    final lastSync = controller.cacheSnapshot?.lastSuccessfulSyncAt;
    final reminderMinutes =
        controller.preferences.dailyReminderMinutesAfterMidnight;
    final reminderTime = TimeOfDay(
      hour: reminderMinutes ~/ 60,
      minute: reminderMinutes % 60,
    );

    return ListView(
      children: [
        _SettingsCard(
          title: 'Server URL',
          value: controller.currentBaseUrl ?? 'Not configured',
        ),
        _SettingsCard(
          title: 'Account',
          value: controller.currentUserEmail ?? 'Signed out',
        ),
        const _SettingsCard(title: 'App version', value: appReleaseLabel),
        _SettingsCard(
          title: 'Last sync status',
          value: controller.syncStatusMessage,
        ),
        _SettingsCard(
          title: 'Last successful sync',
          value: lastSync == null
              ? 'No successful sync yet'
              : DateFormat('dd MMM yyyy, HH:mm').format(lastSync.toLocal()),
        ),
        _SettingsCard(
          title: 'Cached window',
          value: controller.cacheWindowStart == null ||
                  controller.cacheWindowEnd == null
              ? 'No cached window yet'
              : '${formatDateOnlyLabel(controller.cacheWindowStart!, 'dd MMM')} to ${formatDateOnlyLabel(controller.cacheWindowEnd!, 'dd MMM')}',
        ),
        Card(
          child: SwitchListTile(
            title: const Text('Show overdue in Today view'),
            subtitle: const Text(
              'Keep overdue tasks in a separate Today section when any exist.',
            ),
            value: controller.preferences.showOverdueTasksInTodayView,
            onChanged: controller.setShowOverdueTasksInTodayView,
          ),
        ),
        Card(
          child: ExpansionTile(
            title: const Text('Notifications'),
            subtitle: Text(
              controller.preferences.dailyReminderEnabled
                  ? 'Daily at ${reminderTime.format(context)}'
                  : 'Off',
            ),
            childrenPadding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
            children: [
              SwitchListTile(
                contentPadding: EdgeInsets.zero,
                title: const Text('Daily reminder'),
                subtitle: const Text(
                  'Only send a reminder on days that already have active tasks in the cache.',
                ),
                value: controller.preferences.dailyReminderEnabled,
                onChanged: controller.setDailyReminderEnabled,
              ),
              ListTile(
                contentPadding: EdgeInsets.zero,
                enabled: controller.preferences.dailyReminderEnabled,
                title: const Text('Reminder time'),
                subtitle: Text(reminderTime.format(context)),
                trailing: const Icon(Icons.schedule_outlined),
                onTap: !controller.preferences.dailyReminderEnabled
                    ? null
                    : () async {
                        final picked = await showTimePicker(
                          context: context,
                          initialTime: reminderTime,
                        );
                        if (picked != null && context.mounted) {
                          await controller.setDailyReminderMinutesAfterMidnight(
                            (picked.hour * 60) + picked.minute,
                          );
                        }
                      },
              ),
              const SizedBox(height: 4),
              Align(
                alignment: Alignment.centerLeft,
                child: Text(
                  'Reminders use the app cache, so the message stays simple and works offline.',
                  style: Theme.of(context).textTheme.bodySmall,
                ),
              ),
            ],
          ),
        ),
        Card(
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  'Offline task window',
                  style: Theme.of(context).textTheme.titleMedium,
                ),
                const SizedBox(height: 8),
                DropdownButton<OfflineTaskWindow>(
                  value: controller.preferences.offlineTaskWindow,
                  isExpanded: true,
                  items: OfflineTaskWindow.values
                      .map(
                        (window) => DropdownMenuItem(
                          value: window,
                          child: Text(window.label),
                        ),
                      )
                      .toList(growable: false),
                  onChanged: (value) {
                    if (value != null) {
                      controller.updateOfflineWindow(value);
                    }
                  },
                ),
                const SizedBox(height: 12),
                Text(
                  'Theme mode',
                  style: Theme.of(context).textTheme.titleMedium,
                ),
                const SizedBox(height: 8),
                DropdownButton<AppThemeMode>(
                  value: controller.preferences.themeMode,
                  isExpanded: true,
                  items: AppThemeMode.values
                      .map(
                        (mode) => DropdownMenuItem(
                          value: mode,
                          child: Text(mode.label),
                        ),
                      )
                      .toList(growable: false),
                  onChanged: (value) {
                    if (value != null) {
                      controller.setThemeMode(value);
                    }
                  },
                ),
                SwitchListTile(
                  contentPadding: EdgeInsets.zero,
                  title: const Text('Auto refresh on app open'),
                  subtitle: const Text(
                    'Refresh the rolling cache window when the app opens.',
                  ),
                  value: controller.preferences.autoRefreshOnOpen,
                  onChanged: controller.setAutoRefreshOnOpen,
                ),
              ],
            ),
          ),
        ),
        const SizedBox(height: 8),
        FilledButton.tonal(
          onPressed: controller.canRetrySync ? controller.refreshTasks : null,
          child: const Text('Manual refresh'),
        ),
        const SizedBox(height: 8),
        OutlinedButton(
          onPressed: controller.clearCachedData,
          child: const Text('Clear cached data'),
        ),
        const SizedBox(height: 8),
        FilledButton(onPressed: controller.logout, child: const Text('Logout')),
      ],
    );
  }
}

class _SettingsCard extends StatelessWidget {
  const _SettingsCard({required this.title, required this.value});

  final String title;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Card(
      child: ListTile(title: Text(title), subtitle: Text(value)),
    );
  }
}
