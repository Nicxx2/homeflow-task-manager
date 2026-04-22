enum OfflineTaskWindow {
  days3(3, '3 days'),
  days7(7, '7 days'),
  days14(14, '14 days'),
  days30(30, '30 days');

  const OfflineTaskWindow(this.days, this.label);

  final int days;
  final String label;

  static OfflineTaskWindow fromDays(int value) {
    return OfflineTaskWindow.values.firstWhere(
      (window) => window.days == value,
      orElse: () => OfflineTaskWindow.days7,
    );
  }
}

enum AppThemeMode {
  system('system', 'Use device setting'),
  light('light', 'Light'),
  dark('dark', 'Dark');

  const AppThemeMode(this.value, this.label);

  final String value;
  final String label;

  static AppThemeMode fromValue(String? value) {
    return AppThemeMode.values.firstWhere(
      (mode) => mode.value == value,
      orElse: () => AppThemeMode.system,
    );
  }
}

class AppPreferences {
  const AppPreferences({
    required this.offlineTaskWindow,
    required this.autoRefreshOnOpen,
    required this.themeMode,
    required this.showOverdueTasksInTodayView,
    required this.dailyReminderEnabled,
    required this.dailyReminderMinutesAfterMidnight,
  });

  factory AppPreferences.defaults() {
    return const AppPreferences(
      offlineTaskWindow: OfflineTaskWindow.days7,
      autoRefreshOnOpen: true,
      themeMode: AppThemeMode.system,
      showOverdueTasksInTodayView: true,
      dailyReminderEnabled: false,
      dailyReminderMinutesAfterMidnight: 8 * 60,
    );
  }

  factory AppPreferences.fromJson(Map<String, dynamic> json) {
    return AppPreferences(
      offlineTaskWindow: OfflineTaskWindow.fromDays(
        json['offlineTaskWindowDays'] as int? ?? OfflineTaskWindow.days7.days,
      ),
      autoRefreshOnOpen: json['autoRefreshOnOpen'] as bool? ?? true,
      themeMode: AppThemeMode.fromValue(json['themeMode'] as String?),
      showOverdueTasksInTodayView:
          json['showOverdueTasksInTodayView'] as bool? ?? true,
      dailyReminderEnabled: json['dailyReminderEnabled'] as bool? ?? false,
      dailyReminderMinutesAfterMidnight:
          json['dailyReminderMinutesAfterMidnight'] as int? ?? 8 * 60,
    );
  }

  final OfflineTaskWindow offlineTaskWindow;
  final bool autoRefreshOnOpen;
  final AppThemeMode themeMode;
  final bool showOverdueTasksInTodayView;
  final bool dailyReminderEnabled;
  final int dailyReminderMinutesAfterMidnight;

  Map<String, dynamic> toJson() {
    return <String, dynamic>{
      'offlineTaskWindowDays': offlineTaskWindow.days,
      'autoRefreshOnOpen': autoRefreshOnOpen,
      'themeMode': themeMode.value,
      'showOverdueTasksInTodayView': showOverdueTasksInTodayView,
      'dailyReminderEnabled': dailyReminderEnabled,
      'dailyReminderMinutesAfterMidnight': dailyReminderMinutesAfterMidnight,
    };
  }

  AppPreferences copyWith({
    OfflineTaskWindow? offlineTaskWindow,
    bool? autoRefreshOnOpen,
    AppThemeMode? themeMode,
    bool? showOverdueTasksInTodayView,
    bool? dailyReminderEnabled,
    int? dailyReminderMinutesAfterMidnight,
  }) {
    return AppPreferences(
      offlineTaskWindow: offlineTaskWindow ?? this.offlineTaskWindow,
      autoRefreshOnOpen: autoRefreshOnOpen ?? this.autoRefreshOnOpen,
      themeMode: themeMode ?? this.themeMode,
      showOverdueTasksInTodayView:
          showOverdueTasksInTodayView ?? this.showOverdueTasksInTodayView,
      dailyReminderEnabled: dailyReminderEnabled ?? this.dailyReminderEnabled,
      dailyReminderMinutesAfterMidnight:
          dailyReminderMinutesAfterMidnight ??
          this.dailyReminderMinutesAfterMidnight,
    );
  }
}
