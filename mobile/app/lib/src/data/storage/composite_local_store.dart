import '../../core/storage/local_store.dart';

class CompositeLocalStore implements LocalStore {
  CompositeLocalStore(this._stores) : assert(_stores.isNotEmpty);

  final List<LocalStore> _stores;

  @override
  Future<void> delete(String key) async {
    var deleted = false;
    for (final store in _stores) {
      try {
        await store.delete(key);
        deleted = true;
      } catch (_) {
        // Continue clearing other stores when one backend fails.
      }
    }
    if (!deleted) {
      throw StateError(
          'No local storage backend was available to delete $key.');
    }
  }

  @override
  Future<String?> readString(String key) async {
    for (var index = 0; index < _stores.length; index++) {
      try {
        final value = await _stores[index].readString(key);
        if (value == null || value.isEmpty) {
          continue;
        }

        for (var repairIndex = 0; repairIndex < index; repairIndex++) {
          try {
            await _stores[repairIndex].writeString(key, value);
          } catch (_) {
            // Best-effort repair only.
          }
        }
        return value;
      } catch (_) {
        // Continue reading from backup stores when one backend fails.
      }
    }
    return null;
  }

  @override
  Future<void> writeString(String key, String value) async {
    var wrote = false;
    for (final store in _stores) {
      try {
        await store.writeString(key, value);
        wrote = true;
      } catch (_) {
        // Continue writing to other stores when one backend fails.
      }
    }
    if (!wrote) {
      throw StateError('No local storage backend was available to write $key.');
    }
  }
}
