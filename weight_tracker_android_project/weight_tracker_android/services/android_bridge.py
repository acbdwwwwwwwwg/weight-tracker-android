"""Android APIs used by the photo picker, imported without desktop side effects.

PyJNIus 1.7.x does not expose ``jarray`` from ``jnius``. Importing it in the same
``try`` block as ``autoclass``/``cast`` makes the whole Android bridge appear
unavailable, which incorrectly shows the app-only-on-Android warning on phones.
This module deliberately imports only the public APIs it needs and records any
initialization error for a useful message in the UI.
"""

from pathlib import Path

from kivy.utils import platform as KIVY_PLATFORM

PHOTO_PICK_REQUEST = 4101
IS_ANDROID = KIVY_PLATFORM == "android"
ANDROID_AVAILABLE = False
ANDROID_IMPORT_ERROR = None
android_activity = None
autoclass = None
cast = None

if IS_ANDROID:
    _errors = []
    try:
        from android import activity as android_activity  # python-for-android API
    except Exception as exc:  # pragma: no cover - requires Android runtime
        android_activity = None
        _errors.append(f"android.activity 导入失败：{type(exc).__name__}: {exc}")

    try:
        from jnius import autoclass, cast  # PyJNIus public API
    except Exception as exc:  # pragma: no cover - requires Android runtime
        autoclass = None
        cast = None
        _errors.append(f"PyJNIus 导入失败：{type(exc).__name__}: {exc}")

    ANDROID_AVAILABLE = android_activity is not None and autoclass is not None and cast is not None
    if not ANDROID_AVAILABLE:
        ANDROID_IMPORT_ERROR = "\n".join(_errors) or "Android 接口未能初始化。"
else:
    ANDROID_IMPORT_ERROR = f"当前 Kivy platform 为 {KIVY_PLATFORM!r}，不是 Android。"


def get_current_activity():
    """Return the live Kivy Android Activity, resolving it only when needed."""
    if not ANDROID_AVAILABLE:
        raise RuntimeError(ANDROID_IMPORT_ERROR or "Android 桥接接口不可用。")

    python_activity = autoclass("org.kivy.android.PythonActivity")
    live_activity = python_activity.mActivity
    if live_activity is None:
        raise RuntimeError("当前 Android Activity 尚未就绪，请稍后再试。")
    return cast("android.app.Activity", live_activity)


def copy_uri_to_path(uri, destination):
    """Copy a picked content:// URI into app-private storage without jarray.

    Uses Android's ContentResolver InputStream and Java NIO FileChannel in
    bounded chunks. This avoids the unsupported ``from jnius import jarray``
    import and does not load the whole image into Python memory.
    """
    if not ANDROID_AVAILABLE:
        raise RuntimeError(ANDROID_IMPORT_ERROR or "Android 桥接接口不可用。")

    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)

    activity = get_current_activity()
    resolver = activity.getContentResolver()
    input_stream = resolver.openInputStream(uri)
    if input_stream is None:
        raise OSError("Android 无法打开所选照片的读取流。")

    FileOutputStream = autoclass("java.io.FileOutputStream")
    Channels = autoclass("java.nio.channels.Channels")
    output_stream = None
    source_channel = None
    total = 0
    try:
        output_stream = FileOutputStream(str(destination))
        source_channel = Channels.newChannel(input_stream)
        output_channel = output_stream.getChannel()
        chunk_size = 1024 * 1024

        while True:
            copied = int(output_channel.transferFrom(source_channel, total, chunk_size))
            if copied <= 0:
                break
            total += copied
    finally:
        if source_channel is not None:
            try:
                source_channel.close()
            except Exception:
                pass
        else:
            try:
                input_stream.close()
            except Exception:
                pass
        if output_stream is not None:
            try:
                output_stream.close()
            except Exception:
                pass

    if total <= 0:
        try:
            destination.unlink()
        except OSError:
            pass
        raise OSError("没有从照片选择器读取到任何照片数据。")
    return total
