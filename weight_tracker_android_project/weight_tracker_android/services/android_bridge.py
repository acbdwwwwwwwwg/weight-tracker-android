"""Android-only APIs isolated from UI code.

The desktop interpreter remains importable. On Android, PyJNIus imports are
performed separately so one optional symbol cannot make the whole bridge
appear unavailable.
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
        from android import activity as android_activity
    except Exception as exc:  # pragma: no cover - Android runtime only
        _errors.append(f"android.activity 导入失败：{type(exc).__name__}: {exc}")
        android_activity = None
    try:
        from jnius import autoclass, cast
    except Exception as exc:  # pragma: no cover - Android runtime only
        _errors.append(f"PyJNIus 导入失败：{type(exc).__name__}: {exc}")
        autoclass = cast = None
    ANDROID_AVAILABLE = android_activity is not None and autoclass is not None and cast is not None
    if not ANDROID_AVAILABLE:
        ANDROID_IMPORT_ERROR = "\n".join(_errors) or "Android 接口未能初始化。"
else:
    ANDROID_IMPORT_ERROR = f"当前 Kivy platform 为 {KIVY_PLATFORM!r}，不是 Android。"


def get_current_activity():
    if not ANDROID_AVAILABLE:
        raise RuntimeError(ANDROID_IMPORT_ERROR or "Android 桥接接口不可用。")
    python_activity = autoclass("org.kivy.android.PythonActivity")
    live_activity = python_activity.mActivity
    if live_activity is None:
        raise RuntimeError("当前 Android Activity 尚未就绪，请稍后再试。")
    return cast("android.app.Activity", live_activity)


def copy_uri_to_path(uri, destination):
    """Copy a content URI to app-private storage with bounded memory usage."""
    if not ANDROID_AVAILABLE:
        raise RuntimeError(ANDROID_IMPORT_ERROR or "Android 桥接接口不可用。")
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    activity = get_current_activity()
    input_stream = activity.getContentResolver().openInputStream(uri)
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
        while True:
            copied = int(output_channel.transferFrom(source_channel, total, 1024 * 1024))
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


def create_photo_thumbnail(source, destination, max_dimension=640, quality=82):
    """Downsample an image using Android BitmapFactory without loading full pixels in Python.

    This function must be called from a background worker. BitmapFactory's
    inSampleSize avoids decoding the full-resolution image into app memory.
    Returns the thumbnail path.
    """
    if not ANDROID_AVAILABLE:
        raise RuntimeError(ANDROID_IMPORT_ERROR or "Android 桥接接口不可用。")
    source = Path(source)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    BitmapFactory = autoclass("android.graphics.BitmapFactory")
    Options = autoclass("android.graphics.BitmapFactory$Options")
    options = Options()
    options.inJustDecodeBounds = True
    BitmapFactory.decodeFile(str(source), options)
    width, height = int(options.outWidth), int(options.outHeight)
    if width <= 0 or height <= 0:
        raise ValueError("系统无法解码此图片格式。")
    sample = 1
    while max(width // sample, height // sample) > int(max_dimension):
        sample *= 2
    options.inSampleSize = sample
    options.inJustDecodeBounds = False
    bitmap = BitmapFactory.decodeFile(str(source), options)
    if bitmap is None:
        raise ValueError("生成缩略图失败，图片可能已损坏或格式不受支持。")
    FileOutputStream = autoclass("java.io.FileOutputStream")
    CompressFormat = autoclass("android.graphics.Bitmap$CompressFormat")
    stream = None
    try:
        stream = FileOutputStream(str(destination))
        ok = bool(bitmap.compress(CompressFormat.JPEG, int(quality), stream))
        stream.flush()
        if not ok:
            raise OSError("系统未能写入缩略图。")
    finally:
        if stream is not None:
            try:
                stream.close()
            except Exception:
                pass
        try:
            bitmap.recycle()
        except Exception:
            pass
    if not destination.exists() or destination.stat().st_size == 0:
        raise OSError("缩略图文件未成功生成。")
    return destination
