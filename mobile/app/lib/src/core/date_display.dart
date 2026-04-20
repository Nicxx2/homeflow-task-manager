import 'package:intl/intl.dart';

DateTime localCalendarDate(DateTime value) {
  return DateTime(value.year, value.month, value.day);
}

String formatDateOnlyLabel(DateTime value, String pattern) {
  return DateFormat(pattern).format(localCalendarDate(value));
}

String formatWeekdayLabel(DateTime value) {
  return DateFormat('EEEE').format(localCalendarDate(value));
}

String formatWeekdayLabelLower(DateTime value) {
  return formatWeekdayLabel(value).toLowerCase();
}
