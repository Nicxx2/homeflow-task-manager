package com.homeflow.mobile

import android.app.AlarmManager
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.os.Build
import org.json.JSONArray
import org.json.JSONObject
import java.util.Calendar

object TaskReminderScheduler {
    private const val PREFS_NAME = "homeflow_task_notifications"
    private const val KEY_REMINDERS = "scheduled_reminders"

    fun scheduleAll(
        context: Context,
        payloads: List<Map<String, Any?>>,
    ) {
        cancelAll(context)

        val reminders = payloads.mapNotNull { payload ->
            createReminderSpec(payload)
        }
        persistReminders(context, reminders)
        reminders.forEach { reminder ->
            scheduleReminder(context, reminder)
        }
    }

    fun cancelAll(context: Context) {
        val existing = loadReminders(context)
        val alarmManager = context.getSystemService(Context.ALARM_SERVICE) as AlarmManager
        existing.forEach { reminder ->
            val pendingIntent = pendingIntentForReminder(context, reminder)
            alarmManager.cancel(pendingIntent)
            pendingIntent.cancel()
        }
        val notificationManager =
            context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        notificationManager.cancelAll()
        clearPersistedReminders(context)
    }

    fun restore(context: Context) {
        val now = System.currentTimeMillis()
        loadReminders(context)
            .filter { reminder -> reminder.triggerAtMillis > now }
            .forEach { reminder ->
                scheduleReminder(context, reminder)
            }
    }

    private fun scheduleReminder(
        context: Context,
        reminder: TaskReminderSpec,
    ) {
        val alarmManager = context.getSystemService(Context.ALARM_SERVICE) as AlarmManager
        val pendingIntent = pendingIntentForReminder(context, reminder)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            alarmManager.setAndAllowWhileIdle(
                AlarmManager.RTC_WAKEUP,
                reminder.triggerAtMillis,
                pendingIntent,
            )
        } else {
            alarmManager.set(
                AlarmManager.RTC_WAKEUP,
                reminder.triggerAtMillis,
                pendingIntent,
            )
        }
    }

    private fun pendingIntentForReminder(
        context: Context,
        reminder: TaskReminderSpec,
    ): PendingIntent {
        val intent = Intent(context, TaskReminderReceiver::class.java).apply {
            putExtra(TaskReminderReceiver.EXTRA_NOTIFICATION_ID, reminder.id)
            putExtra(TaskReminderReceiver.EXTRA_TITLE, reminder.title)
            putExtra(TaskReminderReceiver.EXTRA_BODY, reminder.body)
        }
        return PendingIntent.getBroadcast(
            context,
            reminder.id,
            intent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
    }

    private fun createReminderSpec(payload: Map<String, Any?>): TaskReminderSpec? {
        val id = (payload["id"] as? Number)?.toInt() ?: return null
        val year = (payload["year"] as? Number)?.toInt() ?: return null
        val month = (payload["month"] as? Number)?.toInt() ?: return null
        val day = (payload["day"] as? Number)?.toInt() ?: return null
        val hour = (payload["hour"] as? Number)?.toInt() ?: return null
        val minute = (payload["minute"] as? Number)?.toInt() ?: return null
        val title = payload["title"] as? String ?: "Homeflow"
        val body = payload["body"] as? String ?: return null

        val triggerAtMillis = Calendar.getInstance().apply {
            set(Calendar.YEAR, year)
            set(Calendar.MONTH, month - 1)
            set(Calendar.DAY_OF_MONTH, day)
            set(Calendar.HOUR_OF_DAY, hour)
            set(Calendar.MINUTE, minute)
            set(Calendar.SECOND, 0)
            set(Calendar.MILLISECOND, 0)
        }.timeInMillis

        return TaskReminderSpec(
            id = id,
            triggerAtMillis = triggerAtMillis,
            title = title,
            body = body,
        )
    }

    private fun persistReminders(
        context: Context,
        reminders: List<TaskReminderSpec>,
    ) {
        val payload = JSONArray().apply {
            reminders.forEach { reminder ->
                put(
                    JSONObject().apply {
                        put("id", reminder.id)
                        put("triggerAtMillis", reminder.triggerAtMillis)
                        put("title", reminder.title)
                        put("body", reminder.body)
                    },
                )
            }
        }

        context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            .edit()
            .putString(KEY_REMINDERS, payload.toString())
            .apply()
    }

    private fun clearPersistedReminders(context: Context) {
        context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            .edit()
            .remove(KEY_REMINDERS)
            .apply()
    }

    private fun loadReminders(context: Context): List<TaskReminderSpec> {
        val raw = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            .getString(KEY_REMINDERS, null)
            ?: return emptyList()

        val jsonArray = runCatching { JSONArray(raw) }.getOrElse { return emptyList() }
        val reminders = mutableListOf<TaskReminderSpec>()
        for (index in 0 until jsonArray.length()) {
            val item = jsonArray.optJSONObject(index) ?: continue
            reminders.add(
                TaskReminderSpec(
                    id = item.optInt("id"),
                    triggerAtMillis = item.optLong("triggerAtMillis"),
                    title = item.optString("title", "Homeflow"),
                    body = item.optString("body"),
                ),
            )
        }
        return reminders
    }
}

data class TaskReminderSpec(
    val id: Int,
    val triggerAtMillis: Long,
    val title: String,
    val body: String,
)
