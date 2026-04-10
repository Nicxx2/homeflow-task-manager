DateTime parseDateOnly(String value) {
  if (!value.contains('T')) {
    final parts = value.split('-');
    return DateTime.utc(
      int.parse(parts[0]),
      int.parse(parts[1]),
      int.parse(parts[2]),
    );
  }

  final parsed = DateTime.parse(value).toUtc();
  return DateTime.utc(parsed.year, parsed.month, parsed.day);
}

String formatDateOnly(DateTime value) {
  final utc = value.toUtc();
  final month = utc.month.toString().padLeft(2, '0');
  final day = utc.day.toString().padLeft(2, '0');
  return '${utc.year}-$month-$day';
}
