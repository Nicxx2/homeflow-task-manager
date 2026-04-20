package com.homeflow.mobile

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent

class TaskReminderBootReceiver : BroadcastReceiver() {
    override fun onReceive(
        context: Context,
        intent: Intent,
    ) {
        TaskReminderScheduler.restore(context)
    }
}
