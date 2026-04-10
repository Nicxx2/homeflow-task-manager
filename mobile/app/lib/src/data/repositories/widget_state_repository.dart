import 'dart:convert';

import '../../core/models/today_widget_snapshot.dart';
import '../../core/storage/local_store.dart';

class WidgetStateRepository {
  WidgetStateRepository(this._store);

  static const String todayWidgetKey = 'homeflow.widget.today';

  final LocalStore _store;

  Future<TodayWidgetSnapshot?> loadToday() async {
    final raw = await _store.readString(todayWidgetKey);
    if (raw == null || raw.isEmpty) {
      return null;
    }
    return TodayWidgetSnapshot.fromJson(jsonDecode(raw) as Map<String, dynamic>);
  }

  Future<void> saveToday(TodayWidgetSnapshot snapshot) async {
    await _store.writeString(todayWidgetKey, jsonEncode(snapshot.toJson()));
  }

  Future<void> clearToday() async {
    await _store.delete(todayWidgetKey);
  }
}
