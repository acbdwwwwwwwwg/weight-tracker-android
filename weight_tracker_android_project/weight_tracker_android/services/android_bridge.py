"""Optional Android APIs isolated from the UI, so modules also import on desktop."""

try:
    from android import activity as android_activity
    from jnius import autoclass, cast, jarray
    ANDROID_AVAILABLE = True
except Exception:
    android_activity = None
    autoclass = cast = jarray = None
    ANDROID_AVAILABLE = False

PHOTO_PICK_REQUEST = 4101
