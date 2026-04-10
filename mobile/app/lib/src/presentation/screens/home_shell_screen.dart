import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import 'package:provider/provider.dart';

import '../../application/app_controller.dart';
import '../../core/app_release.dart';
import '../../core/models/app_preferences.dart';
import '../../core/models/mobile_task.dart';
import '../widgets/sync_status_banner.dart';
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
            title: const Text('Homeflow Mobile'),
            actions: [
              IconButton(
                onPressed: controller.canRetrySync ? controller.refreshTasks : null,
                icon: const Icon(Icons.refresh),
                tooltip: 'Refresh',
              ),
            ],
          ),
          body: SafeArea(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  SyncStatusBanner(
                    title: controller.syncBannerTitle,
                    message: controller.syncStatusMessage,
                    isWarning: controller.syncBannerIsWarning,
                    isError: controller.syncBannerIsError,
                    actionLabel: controller.canRetrySync ? controller.syncBannerActionLabel : null,
                    onAction: controller.canRetrySync ? controller.refreshTasks : null,
                  ),
                  const SizedBox(height: 16),
                  Expanded(child: pages[controller.selectedTabIndex]),
                ],
              ),
            ),
          ),
          bottomNavigationBar: NavigationBar(
            selectedIndex: controller.selectedTabIndex,
            onDestinationSelected: controller.selectTab,
            destinations: const [
              NavigationDestination(icon: Icon(Icons.today_outlined), label: 'Today'),
              NavigationDestination(icon: Icon(Icons.view_agenda_outlined), label: 'Upcoming'),
              NavigationDestination(icon: Icon(Icons.settings_outlined), label: 'Settings'),
            ],
          ),
        );
      },
    );
  }
}

class _TodayTab extends StatelessWidget {
  const _TodayTab();

  @override
  Widget build(BuildContext context) {
    final controller = context.watch<AppController>();
    final tasks = controller.todayTasks;
    final activeTasks = tasks.where((task) => !task.isCompleted).toList(growable: false);
    final completedTasks = tasks.where((task) => task.isCompleted).toList(growable: false);
    final now = DateTime.now().toUtc();
    final today = DateTime.utc(now.year, now.month, now.day);

    return ListView(
      children: [
        Text(
          'Today',
          style: Theme.of(context).textTheme.headlineSmall,
        ),
        const SizedBox(height: 6),
        Text(
          'Fast status updates and a clear view of what still needs attention.',
          style: Theme.of(context).textTheme.bodyMedium,
        ),
        const SizedBox(height: 16),
        _SummaryRow(
          activeCount: activeTasks.length,
          completedCount: completedTasks.length,
        ),
        const SizedBox(height: 16),
        Text(
          activeTasks.isEmpty ? 'No active tasks' : 'Active tasks',
          style: Theme.of(context).textTheme.titleMedium,
        ),
        const SizedBox(height: 8),
        TaskPreviewList(
          tasks: activeTasks,
          emptyMessage: completedTasks.isNotEmpty
              ? 'No active tasks remain for today.'
              : controller.messageForDay(today),
          isUpdatingTask: controller.isUpdatingTask,
          onStatusSelected: controller.canChangeTaskStatus
              ? (task, status) async {
                  await controller.updateTaskStatus(taskId: task.id, status: status);
                }
              : null,
          onTaskTap: (task) => Navigator.of(context).pushNamed(
            TaskDetailShellScreen.routeName,
            arguments: task.id,
          ),
        ),
        if (completedTasks.isNotEmpty) ...[
          const SizedBox(height: 12),
          Text(
            'Completed today',
            style: Theme.of(context).textTheme.titleMedium,
          ),
          const SizedBox(height: 8),
          TaskPreviewList(
            tasks: completedTasks,
            emptyMessage: '',
            isUpdatingTask: controller.isUpdatingTask,
            onStatusSelected: controller.canChangeTaskStatus
                ? (task, status) async {
                    await controller.updateTaskStatus(taskId: task.id, status: status);
                  }
                : null,
            onTaskTap: (task) => Navigator.of(context).pushNamed(
              TaskDetailShellScreen.routeName,
              arguments: task.id,
            ),
          ),
        ],
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
    final tomorrow = DateTime.utc(now.year, now.month, now.day).add(const Duration(days: 1));

    return ListView(
      children: [
        Text(
          'Upcoming',
          style: Theme.of(context).textTheme.headlineSmall,
        ),
        const SizedBox(height: 6),
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
        for (final day in days) ...[
          _UpcomingDaySection(
            day: day,
            tasks: controller.tasksForDate(day)
                .where((task) => task.displayBucket == 'upcoming')
                .toList(growable: false),
          ),
          const SizedBox(height: 12),
        ],
      ],
    );
  }
}

class _UpcomingDaySection extends StatelessWidget {
  const _UpcomingDaySection({
    required this.day,
    required this.tasks,
  });

  final DateTime day;
  final List<MobileTask> tasks;

  @override
  Widget build(BuildContext context) {
    final controller = context.watch<AppController>();
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          DateFormat('EEEE, dd MMM').format(day.toLocal()),
          style: Theme.of(context).textTheme.titleMedium,
        ),
        const SizedBox(height: 8),
        TaskPreviewList(
          tasks: tasks,
          emptyMessage: controller.messageForDay(day),
          showAssignmentDate: true,
          isUpdatingTask: controller.isUpdatingTask,
          onStatusSelected: controller.canChangeTaskStatus
              ? (task, status) async {
                  await controller.updateTaskStatus(taskId: task.id, status: status);
                }
              : null,
          onTaskTap: (task) => Navigator.of(context).pushNamed(
            TaskDetailShellScreen.routeName,
            arguments: task.id,
          ),
        ),
      ],
    );
  }
}

class _SettingsTab extends StatelessWidget {
  const _SettingsTab();

  @override
  Widget build(BuildContext context) {
    final controller = context.watch<AppController>();
    final lastSync = controller.cacheSnapshot?.lastSuccessfulSyncAt;

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
        const _SettingsCard(
          title: 'App version',
          value: appReleaseLabel,
        ),
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
          value: controller.cacheWindowStart == null || controller.cacheWindowEnd == null
              ? 'No cached window yet'
              : '${DateFormat('dd MMM').format(controller.cacheWindowStart!.toLocal())} to ${DateFormat('dd MMM').format(controller.cacheWindowEnd!.toLocal())}',
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
                  subtitle: const Text('Refresh the rolling cache window when the app opens.'),
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
        FilledButton(
          onPressed: controller.logout,
          child: const Text('Logout'),
        ),
      ],
    );
  }
}

class _SettingsCard extends StatelessWidget {
  const _SettingsCard({
    required this.title,
    required this.value,
  });

  final String title;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Card(
      child: ListTile(
        title: Text(title),
        subtitle: Text(value),
      ),
    );
  }
}

class _SummaryRow extends StatelessWidget {
  const _SummaryRow({
    required this.activeCount,
    required this.completedCount,
  });

  final int activeCount;
  final int completedCount;

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        Expanded(
          child: _SummaryTile(
            label: 'Active',
            value: activeCount.toString(),
          ),
        ),
        const SizedBox(width: 12),
        Expanded(
          child: _SummaryTile(
            label: 'Completed',
            value: completedCount.toString(),
          ),
        ),
      ],
    );
  }
}

class _SummaryTile extends StatelessWidget {
  const _SummaryTile({
    required this.label,
    required this.value,
  });

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: Theme.of(context).colorScheme.surfaceContainer,
        borderRadius: BorderRadius.circular(16),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            value,
            style: Theme.of(context).textTheme.headlineSmall,
          ),
          const SizedBox(height: 4),
          Text(label),
        ],
      ),
    );
  }
}
