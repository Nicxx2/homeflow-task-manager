package com.homeflow.mobile

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel

class MainActivity : FlutterActivity() {
    private var pendingNotificationPermissionResult: MethodChannel.Result? = null

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)

        MethodChannel(
            flutterEngine.dartExecutor.binaryMessenger,
            CHANNEL_NAME,
        ).setMethodCallHandler { call, result ->
            when (call.method) {
                "updateTodayWidget" -> {
                    val snapshot = call.argument<String>("snapshot")
                    if (snapshot.isNullOrBlank()) {
                        result.error("invalid_snapshot", "Missing widget snapshot payload.", null)
                        return@setMethodCallHandler
                    }

                    persistWidgetSnapshot(snapshot)
                    HomeflowTodayWidgetProvider.refreshAll(applicationContext)
                    result.success(null)
                }
                else -> result.notImplemented()
            }
        }

        MethodChannel(
            flutterEngine.dartExecutor.binaryMessenger,
            NOTIFICATION_CHANNEL_NAME,
        ).setMethodCallHandler { call, result ->
            when (call.method) {
                "requestNotificationPermission" -> requestNotificationPermission(result)
                "scheduleTaskNotifications" -> {
                    val payloads = call.argument<List<Map<String, Any?>>>("notifications")
                        ?: emptyList()
                    TaskReminderScheduler.scheduleAll(applicationContext, payloads)
                    result.success(null)
                }
                "cancelTaskNotifications" -> {
                    TaskReminderScheduler.cancelAll(applicationContext)
                    result.success(null)
                }
                else -> result.notImplemented()
            }
        }
    }

    private fun persistWidgetSnapshot(snapshot: String) {
        val prefs = applicationContext.getSharedPreferences(
            HomeflowTodayWidgetProvider.PREFS_NAME,
            Context.MODE_PRIVATE,
        )
        prefs.edit()
            .putString(HomeflowTodayWidgetProvider.KEY_TODAY_SNAPSHOT, snapshot)
            .apply()
    }

    private fun requestNotificationPermission(result: MethodChannel.Result) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) {
            result.success(true)
            return
        }

        val permissionState = ContextCompat.checkSelfPermission(
            this,
            Manifest.permission.POST_NOTIFICATIONS,
        )
        if (permissionState == PackageManager.PERMISSION_GRANTED) {
            result.success(true)
            return
        }

        if (pendingNotificationPermissionResult != null) {
            result.error(
                "permission_in_progress",
                "A notification permission request is already in progress.",
                null,
            )
            return
        }

        pendingNotificationPermissionResult = result
        ActivityCompat.requestPermissions(
            this,
            arrayOf(Manifest.permission.POST_NOTIFICATIONS),
            NOTIFICATION_PERMISSION_REQUEST_CODE,
        )
    }

    override fun onRequestPermissionsResult(
        requestCode: Int,
        permissions: Array<out String>,
        grantResults: IntArray,
    ) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode != NOTIFICATION_PERMISSION_REQUEST_CODE) {
            return
        }

        val granted = grantResults.isNotEmpty() &&
            grantResults[0] == PackageManager.PERMISSION_GRANTED
        pendingNotificationPermissionResult?.success(granted)
        pendingNotificationPermissionResult = null
    }

    companion object {
        private const val CHANNEL_NAME = "homeflow/mobile/widget"
        private const val NOTIFICATION_CHANNEL_NAME = "homeflow/mobile/notifications"
        private const val NOTIFICATION_PERMISSION_REQUEST_CODE = 3017
    }
}
