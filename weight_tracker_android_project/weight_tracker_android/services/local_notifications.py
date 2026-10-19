"""Best-effort Android local notifications without a backend/server.

The app checks configured reminder times while its process is running or when
it resumes. This intentionally does not promise delivery after force-stop or
OS process termination; doing that reliably requires a native scheduled receiver
and reboot restoration, which should be added only after device-specific tests.
"""
from __future__ import annotations


def post_local_notification(title: str, message: str) -> bool:
    try:
        from services.android_bridge import ANDROID_AVAILABLE, autoclass, get_current_activity
        if not ANDROID_AVAILABLE:
            return False
        activity = get_current_activity()
        BuildVersion = autoclass("android.os.Build$VERSION")
        sdk = int(BuildVersion.SDK_INT)
        if sdk >= 33:
            permission = "android.permission.POST_NOTIFICATIONS"
            try:
                if int(activity.checkSelfPermission(permission)) != 0:
                    request_notification_permission()
                    return False
            except Exception:
                return False
        Context = autoclass("android.content.Context")
        NotificationManager = autoclass("android.app.NotificationManager")
        manager = activity.getSystemService(Context.NOTIFICATION_SERVICE)
        channel_id = "weight_tracker_daily_reminders"
        if sdk >= 26:
            Channel = autoclass("android.app.NotificationChannel")
            channel = Channel(channel_id, "体重追踪本地提醒", NotificationManager.IMPORTANCE_DEFAULT)
            channel.setDescription("称重、饮食和训练记录的本地提醒")
            manager.createNotificationChannel(channel)
            Builder = autoclass("android.app.Notification$Builder")
            builder = Builder(activity, channel_id)
        else:
            Builder = autoclass("android.app.Notification$Builder")
            builder = Builder(activity)
        Drawable = autoclass("android.R$drawable")
        notification = (builder.setContentTitle(str(title))
                        .setContentText(str(message))
                        .setSmallIcon(Drawable.ic_dialog_info)
                        .setAutoCancel(True)
                        .build())
        manager.notify(abs(hash((title, message))) % 100000 + 1000, notification)
        return True
    except Exception:
        return False

_permission_request_issued = False

def request_notification_permission() -> None:
    """Ask for Android 13+ notification permission after an explicit user action."""
    global _permission_request_issued
    if _permission_request_issued:
        return
    try:
        from services.android_bridge import ANDROID_AVAILABLE, autoclass, get_current_activity
        if not ANDROID_AVAILABLE:
            return
        activity = get_current_activity()
        sdk = int(autoclass("android.os.Build$VERSION").SDK_INT)
        if sdk < 33 or int(activity.checkSelfPermission("android.permission.POST_NOTIFICATIONS")) == 0:
            return
        from android.permissions import request_permissions
        request_permissions(["android.permission.POST_NOTIFICATIONS"])
        _permission_request_issued = True
    except Exception:
        # The reminder editor remains usable even if permission APIs are unavailable.
        return
