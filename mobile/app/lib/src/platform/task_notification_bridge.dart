import 'package:flutter/services.dart';

class ScheduledTaskReminder {
  const ScheduledTaskReminder({
    required this.id,
    required this.scheduledFor,
    required this.title,
    required this.body,
  });

  final int id;
  final DateTime scheduledFor;
  final String title;
  final String body;

  Map<String, Object> toMap() {
    final local = scheduledFor.toLocal();
    return <String, Object>{
      'id': id,
      'year': local.year,
      'month': local.month,
      'day': local.day,
      'hour': local.hour,
      'minute': local.minute,
      'title': title,
      'body': body,
    };
  }
}

class TaskNotificationBridge {
  static const MethodChannel _channel = MethodChannel(
    'homeflow/mobile/notifications',
  );

  static Future<bool> requestPermission() async {
    final granted = await _channel.invokeMethod<bool>(
      'requestNotificationPermission',
    );
    return granted ?? false;
  }

  static Future<void> scheduleTaskNotifications(
    List<ScheduledTaskReminder> reminders,
  ) async {
    await _channel
        .invokeMethod<void>('scheduleTaskNotifications', <String, Object>{
          'notifications': reminders
              .map((reminder) => reminder.toMap())
              .toList(growable: false),
        });
  }

  static Future<void> cancelTaskNotifications() async {
    await _channel.invokeMethod<void>('cancelTaskNotifications');
  }
}
