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
    ANDROID_AVAILABLE, ANDROID_IMPORT_ERROR, IS_ANDROID, PHOTO_PICK_REQUEST,
    android_activity, autoclass, copy_uri_to_path, get_current_activity,
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
        workouts = self.storage.list_workouts_for_month(year, month)
        counts = self.storage.body_photo_counts()
        photos = self.storage.list_body_photos()
        month_prefix = f"{year:04d}-{month:02d}-"
        month_photos = sum(count for date_value, count in counts.items() if date_value.startswith(month_prefix))
        self.calendar_overview_labels["month_workouts"].text = str(sum(1 for value in workouts.values() if value))
        self.calendar_overview_labels["month_photos"].text = str(month_photos)
        self.calendar_overview_labels["all_photos"].text = str(len(photos))

    def refresh_week_strip(self):
        if getattr(self, "week_strip", None) is None:
            return
        self.week_strip.clear_widgets()
        selected = self.calendar_selected_date
        monday = selected - timedelta(days=selected.weekday())
        states = []
        for offset in range(7):
            day_value = monday + timedelta(days=offset)
            trained = self.storage.get_workout(day_value.isoformat())
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
        workouts = self.storage.list_workouts_for_month(year, month)
        photo_counts = self.storage.body_photo_counts()
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
                                    press_color=SURFACE_DOWN, corner_radius=13,
                                    size_hint_y=None, height=dp(42))
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
        self.refresh_calendar_photo_data(preferred_date=self.calendar_selected_date)
        self.render_calendar()
        self.refresh_home_summary()

    def refresh_calendar_photo_data(self, preferred_date=None):
        if preferred_date is not None:
            self.calendar_selected_date = preferred_date
        date_text = self.calendar_selected_date.isoformat()
        workout = self.storage.get_workout(date_text)
        count = int(self.storage.body_photo_counts().get(date_text, 0))
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
            date_text = self._photo_pending_date or datetime.now().date().isoformat()
            Clock.schedule_once(lambda *_: self._import_photo_uri(uri, date_text), 0)
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            Clock.schedule_once(lambda *_args, text=message: self.info("照片读取失败", text), 0)

    def _import_photo_uri(self, uri, date_text):
        target = None
        try:
            base = Path(self.user_data_dir) / "body_photos"
            base.mkdir(parents=True, exist_ok=True)
            activity = get_current_activity()
            mime_value = activity.getContentResolver().getType(uri)
            mime = str(mime_value) if mime_value else "image/jpeg"
            ext = mimetypes.guess_extension(mime) or ".jpg"
            if ext == ".jpe":
                ext = ".jpg"
            filename = f"{date_text.replace('-', '')}_{datetime.now():%H%M%S}_{uuid4().hex[:8]}{ext}"
            target = base / filename
            copy_uri_to_path(uri, target)
            self.storage.add_body_photo(date_text, target)
            self.refresh_calendar_photo_data(preferred_date=datetime.fromisoformat(date_text).date())
            if getattr(self, "calendar_grid", None) is not None:
                self.render_calendar()
            if getattr(self, "photo_carousel", None) is not None:
                self.refresh_photo_carousel(preferred_date=date_text)
            self.refresh_home_summary()
            self.info("照片已保存", f"已关联到 {date_text}，可在“体型”页面左右滑动查看。")
        except Exception as exc:
            if target is not None:
                try:
                    target.unlink()
                except OSError:
                    pass
            self.info("保存照片失败", f"{type(exc).__name__}: {exc}")

    def full_backup(self, *_):
        try:
            path = self.storage.create_full_backup()
            if path is None:
                self.info("备份失败", "当前没有可备份的数据。")
            else:
                self.info("完整备份完成", f"已生成：\n{path.name}\n\n备份包含数据库和所有体型照片。")
        except Exception as exc:
            self.info("备份失败", str(exc))
