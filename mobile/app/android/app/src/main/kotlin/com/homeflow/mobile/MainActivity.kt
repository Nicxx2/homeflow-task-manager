package com.homeflow.mobile

import android.content.Context
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel

class MainActivity : FlutterActivity() {
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

    companion object {
        private const val CHANNEL_NAME = "homeflow/mobile/widget"
    }
}
