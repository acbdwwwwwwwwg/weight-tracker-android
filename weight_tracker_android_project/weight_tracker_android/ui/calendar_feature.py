"""Calendar screen and workout/photo date actions."""
import calendar
import mimetypes
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

from kivy.clock import Clock
from kivy.metrics import dp
from kivy.uix.label import Label
from kivy.uix.widget import Widget

from services.android_bridge import (
    ANDROID_AVAILABLE, ANDROID_IMPORT_ERROR, IS_ANDROID, PHOTO_PICK_REQUEST, FULL_BACKUP_SAVE_REQUEST,
    android_activity, autoclass, copy_uri_to_path, copy_path_to_uri, create_photo_thumbnail, get_current_activity,
)
from ui.theme import CARD, CARD_ALT, GREEN, GREEN_DARK, MUTED, PRIMARY, PURPLE, SURFACE, SURFACE_DOWN, TEXT, WHITE
from ui.widgets import CalendarCell


class CalendarFeatureMixin:
    """Calendar state, workout toggles and Android photo-import flow."""

    def open_calendar(self, *_):
        self.navigate_to("calendar")

    def open_progress_for_selected_date(self, *_):
        self.progress_filter_date = self.calendar_selected_date.isoformat()
        self.navigate_to("progress")

    def refresh_calendar_overview(self):
        if not getattr(self, "calendar_overview_labels", None):
            return
        year, month = self.calendar_date.year, self.calendar_date.month
        if getattr(self, "_calendar_cache_month", None) == (year, month):
            workouts = self._calendar_cache_workouts
            counts = self._calendar_cache_photo_counts
        else:
            workouts = self.storage.list_workouts_for_month(year, month)
            counts = self.storage.body_photo_counts_for_month(year, month)
        self.calendar_overview_labels["month_workouts"].text = str(sum(1 for value in workouts.values() if value))
        self.calendar_overview_labels["month_photos"].text = str(sum(counts.values()))
        if self._calendar_total_photo_count is None:
            self._calendar_total_photo_count = self.storage.count_body_photos()
        self.calendar_overview_labels["all_photos"].text = str(self._calendar_total_photo_count)

    def refresh_week_strip(self):
        if getattr(self, "week_strip", None) is None:
            return
        self.week_strip.clear_widgets()
        selected = self.calendar_selected_date
        monday = selected - timedelta(days=selected.weekday())
        sunday = monday + timedelta(days=6)
        weekly = self.storage.list_workouts_between(monday.isoformat(), sunday.isoformat())
        states = []
        for offset in range(7):
            day_value = monday + timedelta(days=offset)
            trained = bool(weekly.get(day_value.isoformat(), False))
            states.append(trained)
            fill, fg = (GREEN_DARK, GREEN) if trained else (CARD_ALT, MUTED)
            if day_value == selected:
                fill, fg = PRIMARY, WHITE
            title = ("一", "二", "三", "四", "五", "六", "日")[offset]
            cell = self.button(f"{title}\n{day_value.day}{' ✓' if trained else ''}",
                               lambda _, value=day_value: self.select_calendar_date(value), 56,
                               tone="success" if trained and day_value != selected else "soft")
            cell.fill_color = fill
            cell.color = fg
            cell.corner_radius = 15
            self.week_strip.add_widget(cell)
        self.week_summary_label.text = f"本周 {sum(1 for state in states if state)} 天"

    def _move_calendar_month(self, delta):
        month_index = self.calendar_date.year * 12 + (self.calendar_date.month - 1) + int(delta)
        target_year, month_zero = divmod(month_index, 12)
        self.calendar_date = datetime(target_year, month_zero + 1, 1).date()
        last_day = calendar.monthrange(self.calendar_date.year, self.calendar_date.month)[1]
        self.calendar_selected_date = self.calendar_date.replace(day=min(self.calendar_selected_date.day, last_day))
        self.render_calendar()
        self.refresh_calendar_photo_data(preferred_date=self.calendar_selected_date)

    def calendar_prev_month(self, *_):
        self._move_calendar_month(-1)

    def calendar_next_month(self, *_):
        self._move_calendar_month(1)

    def calendar_today(self, *_):
        self.calendar_selected_date = datetime.now().date()
        self.calendar_date = self.calendar_selected_date.replace(day=1)
        self.render_calendar()
        self.refresh_calendar_photo_data(preferred_date=self.calendar_selected_date)

    def render_calendar(self):
        grid = getattr(self, "calendar_grid", None)
        if grid is None:
            return
        grid.clear_widgets()
        year, month = self.calendar_date.year, self.calendar_date.month
        self.calendar_title.text = f"{year}年{month:02d}月"
        if getattr(self, "_calendar_cache_month", None) == (year, month):
            workouts = self._calendar_cache_workouts
            photo_counts = self._calendar_cache_photo_counts
        else:
            workouts = self.storage.list_workouts_for_month(year, month)
            photo_counts = self.storage.body_photo_counts_for_month(year, month)
            self._calendar_cache_month = (year, month)
            self._calendar_cache_workouts = workouts
            self._calendar_cache_photo_counts = photo_counts
        weeks = calendar.monthcalendar(year, month)
        while len(weeks) < 6:
            weeks.append([0] * 7)
        today = datetime.now().date()
        for week in weeks[:6]:
            for day in week:
                if not day:
                    grid.add_widget(Widget())
                    continue
                date_value = datetime(year, month, day).date()
                day_text = date_value.isoformat()
                trained = bool(workouts.get(day_text, False))
                photo_count = int(photo_counts.get(day_text, 0))
                selected = date_value == self.calendar_selected_date
                if selected:
                    fill, fg = PRIMARY, WHITE
                elif trained:
                    fill, fg = GREEN_DARK, GREEN
                elif photo_count:
                    fill, fg = SURFACE, PURPLE
                else:
                    fill, fg = CARD_ALT, TEXT
                if trained and photo_count:
                    marker = f"✓{photo_count}"
                elif trained:
                    marker = "✓"
                elif photo_count:
                    marker = str(photo_count)
                else:
                    marker = "·" if date_value == today else ""
                cell = CalendarCell(text=f"{day}\n{marker}" if marker else str(day),
                                    font_size=dp(11), color=fg, fill_color=fill,
                                    press_color=SURFACE_DOWN, corner_radius=12,
                                    size_hint_y=None, height=dp(44))
                cell.bind(on_release=lambda _, value=date_value: self.select_calendar_date(value))
                grid.add_widget(cell)
        self.refresh_calendar_overview()
        self.refresh_week_strip()

    def select_calendar_date(self, value):
        self.calendar_selected_date = value
        self.refresh_calendar_photo_data(preferred_date=value)
        self.render_calendar()

    def toggle_selected_workout(self, *_):
        date_text = self.calendar_selected_date.isoformat()
        self.storage.set_workout(date_text, not self.storage.get_workout(date_text))
        self._calendar_cache_month = None
        self.render_calendar()
        self.refresh_calendar_photo_data(preferred_date=self.calendar_selected_date)
        self.refresh_home_summary()

    def refresh_calendar_photo_data(self, preferred_date=None):
        if preferred_date is not None:
            self.calendar_selected_date = preferred_date
        date_text = self.calendar_selected_date.isoformat()
        target_date = self.calendar_selected_date
        target_month = (target_date.year, target_date.month)
        if getattr(self, "_calendar_cache_month", None) == target_month:
            workout = bool(self._calendar_cache_workouts.get(date_text, False))
            count = int(self._calendar_cache_photo_counts.get(date_text, 0))
        else:
            workout = self.storage.get_workout(date_text)
            count = self.storage.count_body_photos_for_date(date_text)
        if getattr(self, "calendar_selected_label", None) is not None:
            self.calendar_selected_label.text = f"{date_text}"
        if getattr(self, "calendar_detail_subtitle", None) is not None:
            self.calendar_detail_subtitle.text = "已完成训练，继续保持！" if workout else "选择日期查看状态，也可以补记过去的训练。"
        if getattr(self, "workout_button", None) is not None:
            self.workout_button.text = "✓ 已完成健身" if workout else "＋ 健身打卡"
            self.workout_button.fill_color = GREEN_DARK if workout else SURFACE
            self.workout_button.press_color = SURFACE_DOWN
            self.workout_button.color = GREEN if workout else TEXT
        if getattr(self, "photo_count_label", None) is not None:
            self.photo_count_label.text = f"当天 {count} 张照片 · 照片会出现在体型时间线中"

    def add_body_photo(self, *_):
        """Open Android's image picker, falling back to the document picker."""
        if not IS_ANDROID:
            self.info(
                "需要 Android APK",
                f"照片选择器仅在 Android APK 中可用。\n\n当前环境：{ANDROID_IMPORT_ERROR or '非 Android'}",
            )
            return
        if not ANDROID_AVAILABLE:
            self.info(
                "Android 照片接口未初始化",
                ANDROID_IMPORT_ERROR or "请检查 Android 桥接配置后重新打包。",
            )
            return

        if getattr(self, "current_screen", None) == "calendar":
            self._photo_pending_date = self.calendar_selected_date.isoformat()
        else:
            self._photo_pending_date = (
                getattr(self, "progress_filter_date", None)
                or datetime.now().date().isoformat()
            )

        sdk_int = 0
        picker_error = None
        try:
            try:
                android_activity.unbind(on_activity_result=self.on_activity_result)
            except Exception:
                pass
            android_activity.bind(on_activity_result=self.on_activity_result)

            Intent = autoclass("android.content.Intent")
            activity = get_current_activity()

            # Build.VERSION is a Java inner class. PyJNIus must load it by its
            # binary name (Build$VERSION), not Build.VERSION.
            try:
                BuildVersion = autoclass("android.os.Build$VERSION")
                sdk_int = int(BuildVersion.SDK_INT)
            except Exception:
                # If version lookup fails, use the broadly supported document picker.
                sdk_int = 0

            # Prefer the system Photo Picker on Android 13+; if an OEM image
            # picker cannot resolve this action, fall back instead of failing.
            if sdk_int >= 33:
                try:
                    intent = Intent("android.provider.action.PICK_IMAGES")
                    intent.setType("image/*")
                    activity.startActivityForResult(intent, PHOTO_PICK_REQUEST)
                    return
                except Exception as exc:
                    picker_error = f"系统照片选择器：{type(exc).__name__}: {exc}"

            # ACTION_OPEN_DOCUMENT works on the supported min API and grants
            # access to the selected URI, which is copied into app-private storage.
            try:
                intent = Intent(Intent.ACTION_OPEN_DOCUMENT)
                intent.addCategory(Intent.CATEGORY_OPENABLE)
                intent.setType("image/*")
                activity.startActivityForResult(intent, PHOTO_PICK_REQUEST)
                return
            except Exception as document_exc:
                document_error = f"系统文件选择器：{type(document_exc).__name__}: {document_exc}"

            # Some OEM ROMs have an incomplete document-provider setup.
            try:
                intent = Intent(Intent.ACTION_GET_CONTENT)
                intent.addCategory(Intent.CATEGORY_OPENABLE)
                intent.setType("image/*")
                activity.startActivityForResult(intent, PHOTO_PICK_REQUEST)
                return
            except Exception as content_exc:
                content_error = f"备用图库选择器：{type(content_exc).__name__}: {content_exc}"
                details = "\n\n".join(
                    part for part in (picker_error, document_error, content_error) if part
                )
                raise RuntimeError(details) from content_exc
        except Exception as exc:
            try:
                android_activity.unbind(on_activity_result=self.on_activity_result)
            except Exception:
                pass
            details = f"{type(exc).__name__}: {exc}"
            self.info(
                "打开照片选择器失败",
                f"无法启动系统图片选择器（Android API {sdk_int or '未知'}）。\n\n"
                f"{details}\n\n请确认手机的系统相册或文件选择器可用，然后重试。",
            )

    def on_activity_result(self, request_code, result_code, intent):
        if int(request_code) != PHOTO_PICK_REQUEST:
            return
        try:
            android_activity.unbind(on_activity_result=self.on_activity_result)
        except Exception:
            pass
        if not ANDROID_AVAILABLE:
            return
        try:
            Activity = autoclass("android.app.Activity")
            if int(result_code) != int(Activity.RESULT_OK) or intent is None:
                return
            uri = intent.getData()
            if uri is None:
                return
            # Pass a stable URI string across the worker-thread boundary; resolve it
            # back to a Java Uri on the worker thread instead of sharing JNI proxies.
            uri_text = str(uri.toString())
            date_text = self._photo_pending_date or datetime.now().date().isoformat()
            Clock.schedule_once(lambda *_: self._import_photo_uri(uri_text, date_text), 0)
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            Clock.schedule_once(lambda *_args, text=message: self.info("照片读取失败", text), 0)

    def _import_photo_uri(self, uri, date_text):
        """Copy the selected URI and make its thumbnail off the UI thread."""
        import os
        photo_dir = self.storage.body_photo_dir
        thumb_dir = self.storage.body_photo_thumbnail_dir
        pending_date = str(date_text)
        storage = self.storage

        def worker():
            Uri = autoclass("android.net.Uri")
            selected_uri = Uri.parse(str(uri))
            activity = get_current_activity()
            mime_value = activity.getContentResolver().getType(selected_uri)
            mime = str(mime_value) if mime_value else "image/jpeg"
            ext = mimetypes.guess_extension(mime) or ".jpg"
            if ext == ".jpe":
                ext = ".jpg"
            stamp = datetime.now().strftime("%H%M%S")
            stem = f"{pending_date.replace('-', '')}_{stamp}_{uuid4().hex[:8]}"
            target = photo_dir / f"{stem}{ext}"
            partial = photo_dir / f".{stem}{ext}.part"
            thumb_target = thumb_dir / f"{stem}.jpg"
            thumb_partial = thumb_dir / f".{stem}.jpg.part"
            try:
                copy_uri_to_path(selected_uri, partial)
                os.replace(partial, target)
                saved_thumb = None
                try:
                    create_photo_thumbnail(target, thumb_partial, max_dimension=640, quality=82)
                    os.replace(thumb_partial, thumb_target)
                    saved_thumb = thumb_target
                except Exception:
                    # Keep the original photo even if thumbnail generation fails;
                    # the UI can lazily retry thumbnail creation when it is viewed.
                    try:
                        thumb_partial.unlink()
                    except OSError:
                        pass
                storage.add_body_photo(pending_date, target, thumbnail_path=saved_thumb)
                return {"date": pending_date, "path": str(target), "bytes": target.stat().st_size,
                        "thumbnail": str(saved_thumb) if saved_thumb else None}
            except Exception:
                for candidate in (partial, target, thumb_partial, thumb_target):
                    try:
                        candidate.unlink()
                    except OSError:
                        pass
                raise

        def complete(result):
            target_date = datetime.fromisoformat(result["date"]).date()
            self.calendar_selected_date = target_date
            self.calendar_date = target_date.replace(day=1)
            if self._calendar_total_photo_count is not None:
                self._calendar_total_photo_count += 1
            self._calendar_cache_month = None
            if getattr(self, "calendar_grid", None) is not None:
                self.render_calendar()
            self.refresh_calendar_photo_data(preferred_date=target_date)
            if getattr(self, "current_screen", None) == "progress" and getattr(self, "photo_browser_card", None) is not None:
                self.refresh_photo_browser(preferred_date=result["date"])
            self.refresh_home_summary()
            size_mb = result["bytes"] / (1024 * 1024)
            self.info("照片已保存", f"已关联到 {result['date']}。\n原图 {size_mb:.1f} MB，时间线使用缩略图预览。")

        self.run_background_task("正在导入照片并生成预览", worker, on_success=complete)

    def full_backup(self, *_):
        def complete(path):
            if path is None:
                self.info("备份失败", "当前没有可备份的数据。")
                return
            if not IS_ANDROID or not ANDROID_AVAILABLE:
                self.info("完整备份完成", f"已生成：\n{path}\n\n备份包含数据库、原图和缩略图。")
                return
            self._open_full_backup_save_picker(path)

        self.run_background_task("正在打包数据库和照片", self.storage.create_full_backup, on_success=complete)

    def _open_full_backup_save_picker(self, backup_path):
        try:
            try:
                android_activity.unbind(on_activity_result=self.on_full_backup_save_result)
            except Exception:
                pass
            android_activity.bind(on_activity_result=self.on_full_backup_save_result)
            Intent = autoclass("android.content.Intent")
            intent = Intent(Intent.ACTION_CREATE_DOCUMENT)
            intent.addCategory(Intent.CATEGORY_OPENABLE)
            intent.setType("application/zip")
            intent.putExtra(Intent.EXTRA_TITLE, backup_path.name)
            get_current_activity().startActivityForResult(intent, FULL_BACKUP_SAVE_REQUEST)
            self._pending_full_backup_export = str(backup_path)
        except Exception as exc:
            try:
                android_activity.unbind(on_activity_result=self.on_full_backup_save_result)
            except Exception:
                pass
            self.info("选择备份保存位置失败", f"完整备份仍保存在应用内部。\n{type(exc).__name__}: {exc}")

    def on_full_backup_save_result(self, request_code, result_code, intent):
        if int(request_code) != FULL_BACKUP_SAVE_REQUEST:
            return
        try:
            android_activity.unbind(on_activity_result=self.on_full_backup_save_result)
        except Exception:
            pass
        try:
            Activity = autoclass("android.app.Activity")
            if int(result_code) != int(Activity.RESULT_OK) or intent is None:
                self.info("已取消导出", "完整备份仍保留在应用内部备份目录中。")
                return
            uri = intent.getData()
            if uri is None:
                raise OSError("系统没有返回目标文件。")
            uri_text = str(uri.toString())
            source_path = str(getattr(self, "_pending_full_backup_export", ""))
            if not source_path:
                raise RuntimeError("找不到待导出的完整备份文件。")
            Clock.schedule_once(lambda *_: self._copy_full_backup_to_uri(source_path, uri_text), 0)
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            Clock.schedule_once(lambda *_args, text=message: self.info("导出备份失败", text), 0)

    def _copy_full_backup_to_uri(self, source_path, uri_text):
        def worker():
            Uri = autoclass("android.net.Uri")
            return copy_path_to_uri(source_path, Uri.parse(str(uri_text)))

        def complete(size):
            self.info("完整备份已导出", f"已保存 {size / (1024 * 1024):.1f} MB。\n同时保留了应用内部保护备份。")

        self.run_background_task("正在导出完整备份文件", worker, on_success=complete,
                                 on_error=lambda exc: self.info("导出备份失败", f"{type(exc).__name__}: {exc}"))
