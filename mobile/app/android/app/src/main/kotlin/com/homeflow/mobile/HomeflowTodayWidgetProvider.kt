package com.homeflow.mobile

import android.app.PendingIntent
import android.appwidget.AppWidgetManager
import android.appwidget.AppWidgetProvider
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.view.View
import android.widget.RemoteViews
import org.json.JSONArray
import org.json.JSONObject

class HomeflowTodayWidgetProvider : AppWidgetProvider() {
    override fun onUpdate(
        context: Context,
        appWidgetManager: AppWidgetManager,
        appWidgetIds: IntArray,
    ) {
        appWidgetIds.forEach { appWidgetId ->
            updateWidget(context, appWidgetManager, appWidgetId)
        }
    }

    override fun onEnabled(context: Context) {
        super.onEnabled(context)
        refreshAll(context)
    }

    companion object {
        const val PREFS_NAME = "homeflow_widget_state"
        const val KEY_TODAY_SNAPSHOT = "today_snapshot"

        fun refreshAll(context: Context) {
            val manager = AppWidgetManager.getInstance(context)
            val component = ComponentName(context, HomeflowTodayWidgetProvider::class.java)
            val ids = manager.getAppWidgetIds(component)
            ids.forEach { appWidgetId ->
                updateWidget(context, manager, appWidgetId)
            }
        }

        private fun updateWidget(
            context: Context,
            appWidgetManager: AppWidgetManager,
            appWidgetId: Int,
        ) {
            val snapshot = readSnapshot(context)
            val views = RemoteViews(context.packageName, R.layout.homeflow_today_widget)
            views.setTextViewText(R.id.widget_title, snapshot.title)
            views.setTextViewText(R.id.widget_subtitle, snapshot.subtitle)
            views.setViewVisibility(
                R.id.widget_stale_badge,
                if (snapshot.isStale) View.VISIBLE else View.GONE,
            )

            val taskLines = snapshot.taskTitles.take(3)
            bindTaskLine(views, R.id.widget_task_one, taskLines.getOrNull(0))
            bindTaskLine(views, R.id.widget_task_two, taskLines.getOrNull(1))
            bindTaskLine(views, R.id.widget_task_three, taskLines.getOrNull(2))

            val emptyVisible = taskLines.isEmpty()
            views.setViewVisibility(
                R.id.widget_empty_state,
                if (emptyVisible) View.VISIBLE else View.GONE,
            )
            views.setTextViewText(R.id.widget_empty_state, emptyMessage(snapshot))

            val launchIntent = Intent(context, MainActivity::class.java).apply {
                flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP
                action = Intent.ACTION_VIEW
                putExtra("open_tab", "today")
            }
            val pendingIntent = PendingIntent.getActivity(
                context,
                appWidgetId,
                launchIntent,
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
            )
            views.setOnClickPendingIntent(R.id.widget_root, pendingIntent)

            appWidgetManager.updateAppWidget(appWidgetId, views)
        }

        private fun bindTaskLine(
            views: RemoteViews,
            viewId: Int,
            line: String?,
        ) {
            val visible = !line.isNullOrBlank()
            views.setViewVisibility(viewId, if (visible) View.VISIBLE else View.GONE)
            if (visible) {
                views.setTextViewText(viewId, "- $line")
            }
        }

        private fun emptyMessage(snapshot: WidgetSnapshot): String {
            return when (snapshot.state) {
                "signedOut" -> "Sign in to view today's tasks."
                "noCache" -> "Open the app to sync today's tasks."
                "authRequired" -> "Sign in again to refresh cached tasks."
                "error" -> "Showing cached state after a server error."
                "stale" -> "No active tasks in the current cached view."
                "empty" -> "No active tasks for today."
                else -> "Open the app for task details."
            }
        }

        private fun readSnapshot(context: Context): WidgetSnapshot {
            val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            val raw = prefs.getString(KEY_TODAY_SNAPSHOT, null)
            if (raw.isNullOrBlank()) {
                return WidgetSnapshot(
                    state = "noCache",
                    title = "No cached tasks yet",
                    subtitle = "Open the app to sync today's view.",
                    taskTitles = emptyList(),
                    isStale = false,
                )
            }

            return try {
                val json = JSONObject(raw)
                val taskTitles = mutableListOf<String>()
                val rawTitles = json.optJSONArray("task_titles") ?: JSONArray()
                for (index in 0 until rawTitles.length()) {
                    taskTitles += rawTitles.optString(index)
                }
                WidgetSnapshot(
                    state = json.optString("state", "noCache"),
                    title = json.optString("title", "Today"),
                    subtitle = json.optString("subtitle", ""),
                    taskTitles = taskTitles,
                    isStale = json.optBoolean("is_stale", false),
                )
            } catch (_: Exception) {
                WidgetSnapshot(
                    state = "error",
                    title = "Widget unavailable",
                    subtitle = "Open the app to refresh widget data.",
                    taskTitles = emptyList(),
                    isStale = true,
                )
            }
        }
    }
}

private data class WidgetSnapshot(
    val state: String,
    val title: String,
    val subtitle: String,
    val taskTitles: List<String>,
    val isStale: Boolean,
)
