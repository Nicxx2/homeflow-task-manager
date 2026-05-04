import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:homeflow_mobile/src/application/app_controller.dart';
import 'package:homeflow_mobile/src/application/app_services.dart';
import 'package:homeflow_mobile/src/core/date_display.dart';
import 'package:homeflow_mobile/src/core/models/app_preferences.dart';
import 'package:homeflow_mobile/src/core/models/date_codec.dart';
import 'package:homeflow_mobile/src/core/models/mobile_task.dart';
import 'package:homeflow_mobile/src/core/models/saved_login.dart';
import 'package:homeflow_mobile/src/core/models/task_schedule_feedback.dart';
import 'package:homeflow_mobile/src/data/repositories/connection_repository.dart';
import 'package:homeflow_mobile/src/data/repositories/pending_status_update_repository.dart';
import 'package:homeflow_mobile/src/data/repositories/preferences_repository.dart';
import 'package:homeflow_mobile/src/data/repositories/saved_login_repository.dart';
import 'package:homeflow_mobile/src/data/repositories/session_repository.dart';
import 'package:homeflow_mobile/src/data/repositories/task_cache_repository.dart';
import 'package:homeflow_mobile/src/data/repositories/widget_state_repository.dart';
import 'package:homeflow_mobile/src/data/storage/in_memory_local_store.dart';
import 'package:homeflow_mobile/src/data/storage/in_memory_secure_store.dart';
import 'package:homeflow_mobile/src/presentation/screens/home_shell_screen.dart';
import 'package:homeflow_mobile/src/presentation/widgets/task_schedule_sheet.dart';
import 'package:http/http.dart' as http;
import 'package:provider/provider.dart';

void main() {
  test('offline task window maps to expected day counts', () {
    expect(OfflineTaskWindow.days3.days, 3);
    expect(OfflineTaskWindow.days7.days, 7);
    expect(OfflineTaskWindow.days14.days, 14);
    expect(OfflineTaskWindow.days30.days, 30);
  });

  test('theme mode preferences serialize and restore correctly', () {
    const preferences = AppPreferences(
      offlineTaskWindow: OfflineTaskWindow.days14,
      autoRefreshOnOpen: false,
      themeMode: AppThemeMode.dark,
      showOverdueTasksInTodayView: false,
      dailyReminderEnabled: true,
      dailyReminderMinutesAfterMidnight: 9 * 60 + 30,
    );

    final restored = AppPreferences.fromJson(preferences.toJson());

    expect(restored.offlineTaskWindow, OfflineTaskWindow.days14);
    expect(restored.autoRefreshOnOpen, isFalse);
    expect(restored.themeMode, AppThemeMode.dark);
    expect(restored.showOverdueTasksInTodayView, isFalse);
    expect(restored.dailyReminderEnabled, isTrue);
    expect(restored.dailyReminderMinutesAfterMidnight, (9 * 60) + 30);
  });

  test('saved login serializes and restores correctly', () {
    const login = SavedLogin(
      email: 'user@example.com',
      password: 'secret-pass',
    );

    final restored = SavedLogin.fromJson(login.toJson());

    expect(restored.email, 'user@example.com');
    expect(restored.password, 'secret-pass');
  });

  test('date-only display keeps the original calendar day', () {
    final value = DateTime.utc(2026, 4, 20);

    expect(formatDateOnlyLabel(value, 'dd MMM yyyy'), '20 Apr 2026');
    expect(formatWeekdayLabelLower(value), 'monday');
  });

  test('date-only payloads keep locally selected calendar day', () {
    final selected = DateTime(2026, 5, 3);

    expect(formatDateOnly(selected), '2026-05-03');
  });

  testWidgets('today tab shows overdue section only when overdue tasks exist', (
    tester,
  ) async {
    final controller = _FakeAppController(
      _buildServices(),
      preferences: AppPreferences.defaults(),
      active: [
        _task(
          id: 1,
          title: 'Today task',
          bucket: 'today',
          dueDate: DateTime.utc(2026, 4, 22),
          assignmentDate: DateTime.utc(2026, 4, 22),
        ),
      ],
      overdue: [
        _task(
          id: 2,
          title: 'Overdue task',
          bucket: 'overdue',
          dueDate: DateTime.utc(2026, 4, 21),
          assignmentDate: DateTime.utc(2026, 4, 21),
        ),
      ],
      completed: [
        _task(
          id: 3,
          title: 'Completed task',
          bucket: 'completed',
          dueDate: DateTime.utc(2026, 4, 22),
          assignmentDate: DateTime.utc(2026, 4, 22),
          status: MobileTaskStatus.completed,
          isCompleted: true,
        ),
      ],
    );

    await tester.pumpWidget(
      ChangeNotifierProvider<AppController>.value(
        value: controller,
        child: const MaterialApp(home: HomeShellScreen()),
      ),
    );
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 250));

    expect(find.text('Active 1'), findsOneWidget);
    expect(find.text('Overdue 1'), findsOneWidget);
    expect(find.text('Completed 1'), findsOneWidget);

    controller.dispose();
  });

  testWidgets('today tab hides overdue section when there are no overdue tasks',
      (
    tester,
  ) async {
    final controller = _FakeAppController(
      _buildServices(),
      preferences: AppPreferences.defaults(),
      active: [
        _task(
          id: 1,
          title: 'Today task',
          bucket: 'today',
          dueDate: DateTime.utc(2026, 4, 22),
          assignmentDate: DateTime.utc(2026, 4, 22),
        ),
      ],
      overdue: const [],
      completed: [
        _task(
          id: 3,
          title: 'Completed task',
          bucket: 'completed',
          dueDate: DateTime.utc(2026, 4, 22),
          assignmentDate: DateTime.utc(2026, 4, 22),
          status: MobileTaskStatus.completed,
          isCompleted: true,
        ),
      ],
    );

    await tester.pumpWidget(
      ChangeNotifierProvider<AppController>.value(
        value: controller,
        child: const MaterialApp(home: HomeShellScreen()),
      ),
    );
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 250));

    expect(find.text('Active 1'), findsOneWidget);
    expect(find.text('Overdue 1'), findsNothing);
    expect(find.text('Completed 1'), findsOneWidget);

    controller.dispose();
  });

  testWidgets(
    'today tab hides overdue section when preference is disabled',
    (tester) async {
      final controller = _FakeAppController(
        _buildServices(),
        preferences: AppPreferences.defaults().copyWith(
          showOverdueTasksInTodayView: false,
        ),
        active: [
          _task(
            id: 1,
            title: 'Today task',
            bucket: 'today',
            dueDate: DateTime.utc(2026, 4, 22),
            assignmentDate: DateTime.utc(2026, 4, 22),
          ),
        ],
        overdue: [
          _task(
            id: 2,
            title: 'Overdue task',
            bucket: 'overdue',
            dueDate: DateTime.utc(2026, 4, 21),
            assignmentDate: DateTime.utc(2026, 4, 21),
          ),
        ],
        completed: const [],
      );

      await tester.pumpWidget(
        ChangeNotifierProvider<AppController>.value(
          value: controller,
          child: const MaterialApp(home: HomeShellScreen()),
        ),
      );
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 250));

      expect(find.text('Active 1'), findsOneWidget);
      expect(find.text('Overdue 1'), findsNothing);

      controller.dispose();
    },
  );

  testWidgets(
    'schedule sheet opens with stored assignment date without checking capacity',
    (tester) async {
      final controller = _FakeAppController(
        _buildServices(),
        preferences: AppPreferences.defaults(),
        active: const [],
        overdue: const [],
        completed: const [],
      );
      final task = _task(
        id: 4,
        title: 'Old assigned task',
        bucket: 'overdue',
        dueDate: DateTime.utc(2026, 5, 4),
        assignmentDate: DateTime.utc(2026, 1, 2),
      );

      await tester.pumpWidget(
        ChangeNotifierProvider<AppController>.value(
          value: controller,
          child: MaterialApp(
            home: Builder(
              builder: (context) => TextButton(
                onPressed: () => showTaskScheduleSheet(context, task: task),
                child: const Text('Open dates'),
              ),
            ),
          ),
        ),
      );

      await tester.tap(find.text('Open dates'));
      await tester.pumpAndSettle();

      expect(
        find.text(
            formatDateOnlyLabel(task.assignmentDate!, 'EEE, dd MMM yyyy')),
        findsOneWidget,
      );
      expect(find.text('Checking...'), findsNothing);
      expect(find.textContaining('pts'), findsNothing);
      expect(controller.scheduleCheckCount, 0);

      controller.dispose();
    },
  );

  testWidgets(
    'schedule sheet saves due-date-only changes with unchanged past assignment',
    (tester) async {
      final controller = _FakeAppController(
        _buildServices(),
        preferences: AppPreferences.defaults(),
        active: const [],
        overdue: const [],
        completed: const [],
      );
      final task = _task(
        id: 7,
        title: 'Due-only task',
        bucket: 'overdue',
        dueDate: DateTime.utc(2026, 5, 4),
        assignmentDate: DateTime.utc(2026, 1, 2),
      );

      await tester.pumpWidget(
        ChangeNotifierProvider<AppController>.value(
          value: controller,
          child: MaterialApp(
            home: Builder(
              builder: (context) => TextButton(
                onPressed: () => showTaskScheduleSheet(context, task: task),
                child: const Text('Open dates'),
              ),
            ),
          ),
        ),
      );

      await tester.tap(find.text('Open dates'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Due'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('10').last);
      await tester.tap(find.text('OK'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Save'));
      await tester.pumpAndSettle();

      expect(controller.scheduleUpdateCount, 1);
      expect(controller.lastScheduleDueDate, DateTime.utc(2026, 5, 10));
      expect(controller.lastScheduleAssignmentDate, task.assignmentDate);
      expect(controller.scheduleCheckCount, 0);

      controller.dispose();
    },
  );

  testWidgets('upcoming rows hide metadata but keep date action',
      (tester) async {
    final upcomingDay = DateTime.utc(2026, 5, 6);
    final controller = _FakeAppController(
      _buildServices(),
      preferences: AppPreferences.defaults(),
      active: const [],
      overdue: const [],
      completed: const [],
      upcomingDays: [upcomingDay],
      tasksByDate: {
        formatDateOnly(upcomingDay): [
          _task(
            id: 5,
            title: 'Future task',
            bucket: 'upcoming',
            dueDate: upcomingDay,
            assignmentDate: upcomingDay,
          ),
        ],
      },
    );

    await tester.pumpWidget(
      ChangeNotifierProvider<AppController>.value(
        value: controller,
        child: const MaterialApp(home: HomeShellScreen()),
      ),
    );
    await tester.pump();
    await tester.tap(find.text('Upcoming'));
    await tester.pumpAndSettle();

    expect(find.text('Future task'), findsOneWidget);
    expect(find.textContaining('assigned'), findsNothing);
    expect(find.textContaining('due '), findsNothing);
    expect(find.text('5 pts'), findsNothing);
    expect(find.byTooltip('Adjust dates'), findsOneWidget);

    controller.dispose();
  });

  testWidgets('upcoming rows show overdue chip when metadata is hidden',
      (tester) async {
    final upcomingDay = DateTime.utc(2026, 5, 6);
    final controller = _FakeAppController(
      _buildServices(),
      preferences: AppPreferences.defaults().copyWith(
        showOverdueTasksInTodayView: false,
      ),
      active: const [],
      overdue: const [],
      completed: const [],
      upcomingDays: [upcomingDay],
      tasksByDate: {
        formatDateOnly(upcomingDay): [
          _task(
            id: 6,
            title: 'Future overdue task',
            bucket: 'overdue',
            dueDate: DateTime.utc(2026, 5, 1),
            assignmentDate: upcomingDay,
          ),
        ],
      },
    );

    await tester.pumpWidget(
      ChangeNotifierProvider<AppController>.value(
        value: controller,
        child: const MaterialApp(home: HomeShellScreen()),
      ),
    );
    await tester.pump();
    await tester.tap(find.text('Upcoming'));
    await tester.pumpAndSettle();

    expect(find.text('Future overdue task'), findsOneWidget);
    expect(find.text('overdue'), findsOneWidget);
    expect(find.text('Pending - assigned 06 May - due 01 May'), findsNothing);
    expect(find.text('5 pts'), findsNothing);
    expect(find.byTooltip('Adjust dates'), findsOneWidget);

    controller.dispose();
  });
}

MobileTask _task({
  required int id,
  required String title,
  required String bucket,
  required DateTime dueDate,
  required DateTime assignmentDate,
  MobileTaskStatus status = MobileTaskStatus.pending,
  bool isCompleted = false,
}) {
  return MobileTask(
    id: id,
    title: title,
    description: 'Task description',
    status: status,
    dueDate: dueDate,
    assignmentDate: assignmentDate,
    assigneeId: 1,
    effortLevel: EffortLevel.medium,
    pointsValue: 5,
    updatedAt: DateTime.now().toUtc(),
    isOverdue: bucket == 'overdue',
    isCompleted: isCompleted,
    displayBucket: bucket,
    sortKey: '$bucket:$id',
    recurrenceParentId: null,
    recurrenceSummary: null,
  );
}

class _FakeAppController extends AppController {
  _FakeAppController(
    super.services, {
    required AppPreferences preferences,
    required List<MobileTask> active,
    required List<MobileTask> overdue,
    required List<MobileTask> completed,
    List<DateTime> upcomingDays = const [],
    Map<String, List<MobileTask>> tasksByDate = const {},
  })  : _preferences = preferences,
        _active = active,
        _overdue = overdue,
        _completed = completed,
        _upcomingDays = upcomingDays,
        _tasksByDate = tasksByDate;

  final AppPreferences _preferences;
  final List<MobileTask> _active;
  final List<MobileTask> _overdue;
  final List<MobileTask> _completed;
  final List<DateTime> _upcomingDays;
  final Map<String, List<MobileTask>> _tasksByDate;
  int scheduleCheckCount = 0;
  int scheduleUpdateCount = 0;
  DateTime? lastScheduleDueDate;
  DateTime? lastScheduleAssignmentDate;

  @override
  AppPreferences get preferences => _preferences;

  @override
  List<MobileTask> get activeTodayTasks => _active;

  @override
  List<MobileTask> get overdueTasks => _overdue;

  @override
  List<MobileTask> get completedTodayTasks => _completed;

  @override
  List<DateTime> get upcomingDays => _upcomingDays;

  @override
  bool get canChangeTaskSchedule => true;

  @override
  List<MobileTask> tasksForDate(DateTime day) =>
      _tasksByDate[formatDateOnly(day)] ?? const [];

  @override
  bool shouldShowTaskInUpcoming(MobileTask task) {
    if (task.displayBucket == 'upcoming') {
      return true;
    }
    if (_preferences.showOverdueTasksInTodayView ||
        task.displayBucket != 'overdue' ||
        task.isCompleted) {
      return false;
    }
    final assignmentDate = task.assignmentDate;
    if (assignmentDate == null) {
      return false;
    }
    final now = DateTime.now().toUtc();
    final today = DateTime.utc(now.year, now.month, now.day);
    final assignment = DateTime.utc(
      assignmentDate.year,
      assignmentDate.month,
      assignmentDate.day,
    );
    return assignment.isAfter(today);
  }

  @override
  Future<TaskScheduleFeedback?> checkTaskSchedule({
    required int taskId,
    required DateTime assignmentDate,
  }) async {
    scheduleCheckCount += 1;
    return null;
  }

  @override
  Future<bool> updateTaskSchedule({
    required int taskId,
    required DateTime dueDate,
    required DateTime assignmentDate,
    bool extendCapacity = false,
  }) async {
    scheduleUpdateCount += 1;
    lastScheduleDueDate = dueDate;
    lastScheduleAssignmentDate = assignmentDate;
    return true;
  }

  @override
  String messageForDay(DateTime day) =>
      'No tasks for this day in the current cache window.';
}

AppServices _buildServices() {
  final localStore = InMemoryLocalStore();
  final secureStore = InMemorySecureStore();

  return AppServices(
    connectionRepository: ConnectionRepository(
      localStore,
      secureStore: secureStore,
    ),
    savedLoginRepository: SavedLoginRepository(secureStore),
    sessionRepository: SessionRepository(secureStore),
    preferencesRepository: PreferencesRepository(localStore),
    pendingStatusUpdateRepository: PendingStatusUpdateRepository(localStore),
    taskCacheRepository: TaskCacheRepository(localStore),
    widgetStateRepository: WidgetStateRepository(localStore),
    httpClient: http.Client(),
  );
}
