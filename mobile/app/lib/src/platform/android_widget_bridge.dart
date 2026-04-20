import 'dart:convert';

import 'package:flutter/services.dart';

import '../core/models/today_widget_snapshot.dart';

class AndroidWidgetBridge {
  static const MethodChannel _channel = MethodChannel('homeflow/mobile/widget');

  static Future<void> updateTodaySnapshot(TodayWidgetSnapshot snapshot) async {
    try {
      await _channel.invokeMethod<void>('updateTodayWidget', <String, dynamic>{
        'snapshot': jsonEncode(snapshot.toJson()),
      });
    } on MissingPluginException {
      // Android widget hosting is optional in non-Android environments.
    } on PlatformException {
      // Widget refresh failures should not break app sync or screen flows.
    }
  }
}
