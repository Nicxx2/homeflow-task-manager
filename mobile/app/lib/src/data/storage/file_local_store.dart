import 'dart:convert';
import 'dart:io';

import '../../core/storage/local_store.dart';

class FileLocalStore implements LocalStore {
  FileLocalStore(this._file);

  final File _file;

  @override
  Future<void> delete(String key) async {
    final values = await _readValues();
    if (values.remove(key) == null) {
      return;
    }
    await _writeValues(values);
  }

  @override
  Future<String?> readString(String key) async {
    final values = await _readValues();
    final value = values[key];
    return value is String && value.isNotEmpty ? value : null;
  }

  @override
  Future<void> writeString(String key, String value) async {
    final values = await _readValues();
    values[key] = value;
    await _writeValues(values);
  }

  Future<Map<String, dynamic>> _readValues() async {
    if (!await _file.exists()) {
      return <String, dynamic>{};
    }

    final raw = await _file.readAsString();
    if (raw.trim().isEmpty) {
      return <String, dynamic>{};
    }

    final decoded = jsonDecode(raw);
    if (decoded is! Map<String, dynamic>) {
      return <String, dynamic>{};
    }
    return decoded;
  }

  Future<void> _writeValues(Map<String, dynamic> values) async {
    await _file.parent.create(recursive: true);
    await _file.writeAsString(jsonEncode(values), flush: true);
  }
}
