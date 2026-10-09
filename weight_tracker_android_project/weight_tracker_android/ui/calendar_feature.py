"""Calendar, workout check-in, photo timeline, Android picker and full-backup behavior."""

import calendar
import mimetypes
import shutil
import zipfile
from uuid import uuid4
from datetime import datetime, timedelta
from pathlib import Path

from kivy.clock import Clock
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.carousel import Carousel
from kivy.uix.image import Image
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView

from services.android_bridge import ANDROID_AVAILABLE, android_activity, autoclass, cast, jarray, PHOTO_PICK_REQUEST
from ui.theme import (BG, CARD, CARD_ALT, CARD_DARK, FIELD_BG, FONT_NAME, GREEN, GREEN_DARK,
                      LINE_COLOR, MUTED, PRIMARY, PRIMARY_DARK, PURPLE, SURFACE, SURFACE_DOWN,
                      TEXT, WHITE)
from ui.widgets import CalendarCell, PhotoPage, RoundedButton, RoundedPanel

class CalendarFeatureMixin:
    """Methods implementing monthly calendar, workout status and body-photo timeline."""

    def open_calendar(self, *_):
        self.calendar_date = self.calendar_selected_date.replace(day=1)
        self.calendar_overview_labels = {}

        content = BoxLayout(orientation="vertical", padding=(dp(12), dp(10)), spacing=dp(12), size_hint_y=None)
        content.bind(minimum_height=content.setter("height"))

        # 顶部：健身风格标题 + 关闭操作
        header = RoundedPanel(orientation="horizontal", padding=(dp(14), dp(10)), spacing=dp(8),
                              size_hint_y=None, height=dp(68), panel_color=CARD)
        heading = BoxLayout(orientation="vertical", spacing=dp(1))
        heading.add_widget(self.label("TRAINING LOG", 10, PRIMARY, True))
        heading.add_widget(self.label("训练日历与体型", 18, TEXT, True))
        header.add_widget(heading)
        today_btn = self.button("今天", self.calendar_today, 38, tone="secondary")
        today_btn.size_hint_x = None
        today_btn.width = dp(58)
        close_btn = self.button("完成", lambda *_: self.calendar_popup.dismiss(), 38, tone="primary")
        close_btn.size_hint_x = None
        close_btn.width = dp(66)
        header.add_widget(today_btn)
        header.add_widget(close_btn)
        content.add_widget(header)

        # 概览卡：当月打卡、当月照片与照片总量
        overview = RoundedPanel(orientation="vertical", padding=(dp(14), dp(12)), spacing=dp(8),
                                size_hint_y=None, height=dp(126), panel_color=CARD)
        overview.add_widget(self.label("训练概览", 14, TEXT, True))
        metrics = GridLayout(cols=3, spacing=dp(6), size_hint_y=None, height=dp(74))
        for key, title, accent in [("month_workouts", "本月健身", GREEN),
                                   ("month_photos", "本月照片", PRIMARY),
                                   ("all_photos", "累计照片", PURPLE)]:
            cell = BoxLayout(orientation="vertical", spacing=dp(2))
            value = self.label("0", 22, accent, True)
            caption = self.label(title, 11, MUTED)
            self.calendar_overview_labels[key] = value
            cell.add_widget(value)
            cell.add_widget(caption)
            metrics.add_widget(cell)
        overview.add_widget(metrics)
        content.add_widget(overview)

        # 本周训练卡：使用胶囊式日期块，增强打卡反馈
        week_card = RoundedPanel(orientation="vertical", padding=(dp(12), dp(10)), spacing=dp(8),
                                 size_hint_y=None, height=dp(112), panel_color=CARD)
        week_header = BoxLayout(size_hint_y=None, height=dp(20))
        week_header.add_widget(self.label("本周训练", 13, TEXT, True))
        self.week_summary_label = self.label("", 11, PURPLE, True)
        week_header.add_widget(self.week_summary_label)
        week_card.add_widget(week_header)
        self.week_strip = GridLayout(cols=7, spacing=dp(5), size_hint_y=None, height=dp(58))
        week_card.add_widget(self.week_strip)
        content.add_widget(week_card)

        # 月历卡：所有日期用圆角块表现，训练日采用薄荷绿/珊瑚色区分。
        month_card = RoundedPanel(orientation="vertical", padding=(dp(12), dp(12)), spacing=dp(7),
                                  size_hint_y=None, height=dp(372), panel_color=CARD)
        month_head = BoxLayout(size_hint_y=None, height=dp(36), spacing=dp(6))
        month_title_box = BoxLayout(orientation="vertical", spacing=dp(0))
        month_title_box.add_widget(self.label("月训练日历", 14, TEXT, True))
        month_title_box.add_widget(self.label("选择日期查看打卡与照片", 10, MUTED))
        month_head.add_widget(month_title_box)
        month_nav = BoxLayout(size_hint_x=None, width=dp(154), spacing=dp(5))
        prev_btn = self.button("‹", self.calendar_prev_month, 32, tone="soft")
        prev_btn.size_hint_x = None
        prev_btn.width = dp(34)
        self.calendar_title = self.label("", 11, TEXT, True)
        month_nav.add_widget(prev_btn)
        month_nav.add_widget(self.calendar_title)
        next_btn = self.button("›", self.calendar_next_month, 32, tone="soft")
        next_btn.size_hint_x = None
        next_btn.width = dp(34)
        month_nav.add_widget(next_btn)
        month_head.add_widget(month_nav)
        month_card.add_widget(month_head)

        weekdays = GridLayout(cols=7, size_hint_y=None, height=dp(22), spacing=dp(2))
        for day_name in ("一", "二", "三", "四", "五", "六", "日"):
            weekdays.add_widget(self.label(day_name, 10, MUTED, True))
        month_card.add_widget(weekdays)
        self.calendar_grid = GridLayout(cols=7, size_hint_y=None, height=dp(6 * 45), spacing=dp(4))
        month_card.add_widget(self.calendar_grid)
        content.add_widget(month_card)

        # 所选日期卡
        detail = RoundedPanel(orientation="vertical", padding=(dp(12), dp(11)), spacing=dp(6),
                              size_hint_y=None, height=dp(118), panel_color=CARD)
        self.calendar_selected_label = self.label("", 14, TEXT, True)
        detail.add_widget(self.calendar_selected_label)
        detail_actions = BoxLayout(spacing=dp(7), size_hint_y=None, height=dp(40))
        self.workout_button = self.button("", self.toggle_selected_workout, 38, tone="success")
        detail_actions.add_widget(self.workout_button)
        add_photo = self.button("＋ 添加照片", self.add_body_photo, 38, tone="primary")
        detail_actions.add_widget(add_photo)
        backup_btn = self.button("备份", self.full_backup, 38, tone="secondary")
        backup_btn.size_hint_x = None
        backup_btn.width = dp(64)
        detail_actions.add_widget(backup_btn)
        detail.add_widget(detail_actions)
        self.photo_count_label = self.label("", 11, MUTED)
        detail.add_widget(self.photo_count_label)
        content.add_widget(detail)

        # 照片时间线卡。Carousel 保留原功能，照片仍按数据库中的时间顺序加载。
        photos_card = RoundedPanel(orientation="vertical", padding=(dp(12), dp(12)), spacing=dp(7),
                                   size_hint_y=None, height=dp(370), panel_color=CARD)
        photos_header = BoxLayout(size_hint_y=None, height=dp(42), spacing=dp(5))
        title_stack = BoxLayout(orientation="vertical", spacing=dp(1))
        title_stack.add_widget(self.label("体型进度", 14, TEXT, True))
        title_stack.add_widget(self.label("BODY TIMELINE  ·  左右滑动", 9, MUTED, True))
        photos_header.add_widget(title_stack)
        self.photo_date_label = self.label("暂无照片", 10, PURPLE, True)
        photos_header.add_widget(self.photo_date_label)
        photos_card.add_widget(photos_header)
        self.photo_carousel = Carousel(direction="left", loop=False, size_hint_y=None, height=dp(246))
        self.photo_carousel.bind(index=self.on_photo_index)
        photos_card.add_widget(self.photo_carousel)
        photo_actions = BoxLayout(size_hint_y=None, height=dp(36), spacing=dp(6))
        photo_actions.add_widget(self.button("删除当前照片", self.delete_current_photo, 34, tone="secondary"))
        photo_actions.add_widget(self.button("跳到所选日期", self.jump_to_selected_photo, 34, tone="secondary"))
        photos_card.add_widget(photo_actions)
        content.add_widget(photos_card)

        scroller = ScrollView(do_scroll_x=False, do_scroll_y=True, bar_width=dp(3),
                              scroll_type=["bars", "content"])
        scroller.add_widget(content)
        self.calendar_popup = Popup(
            title="",
            title_font=FONT_NAME,
            content=scroller,
            size_hint=(.98, .97),
            title_size=dp(1),
            background="",
            separator_color=(0, 0, 0, 0),
            separator_height=0,
            auto_dismiss=True,
        )
        self.calendar_popup.open()
        self.render_calendar()
        self.refresh_calendar_photo_data(preferred_date=self.calendar_selected_date)

    def refresh_calendar_overview(self):
        if not getattr(self, "calendar_overview_labels", None):
            return
        y, m = self.calendar_date.year, self.calendar_date.month
        workouts = self.storage.list_workouts_for_month(y, m)
        counts = self.storage.body_photo_counts()
        photos = self.storage.list_body_photos()
        month_photos = sum(count for date_value, count in counts.items() if date_value.startswith(f"{y:04d}-{m:02d}-"))
        self.calendar_overview_labels["month_workouts"].text = str(sum(1 for value in workouts.values() if value))
        self.calendar_overview_labels["month_photos"].text = str(month_photos)
        self.calendar_overview_labels["all_photos"].text = str(len(photos))

    def refresh_week_strip(self):
        if not hasattr(self, "week_strip"):
            return
        self.week_strip.clear_widgets()
        selected = self.calendar_selected_date
        monday = selected - timedelta(days=selected.weekday())
        workouts = self.storage.list_workouts_for_month(selected.year, selected.month)
        # При переходе месяца рядом с выбранной датой дополняем остальные дни прямым запросом。
        is_workout = []
        for offset in range(7):
            day_value = monday + timedelta(days=offset)
            workout = self.storage.get_workout(day_value.isoformat())
            is_workout.append(workout)
            fill = GREEN_DARK if workout else CARD_ALT
            fg = GREEN if workout else MUTED
            if day_value == selected:
                fill = PRIMARY
                fg = WHITE
            text_value = f"{('一','二','三','四','五','六','日')[offset]}\n{day_value.day}\n{'✓' if workout else '·'}"
            cell = RoundedButton(text=text_value, size_hint_y=None, height=dp(56), fill_color=fill,
                                 press_color=SURFACE_DOWN, color=fg, font_size=dp(10), corner_radius=14)
            cell.bind(on_release=lambda _, value=day_value: self.select_calendar_date(value))
            self.week_strip.add_widget(cell)
        if hasattr(self, "week_summary_label"):
            self.week_summary_label.text = f"本周 {sum(1 for x in is_workout if x)} 天"

    def _move_calendar_month(self, delta):
        year, month = self.calendar_date.year, self.calendar_date.month
        month_index = year * 12 + (month - 1) + int(delta)
        target_year, month_zero_based = divmod(month_index, 12)
        self.calendar_date = datetime(target_year, month_zero_based + 1, 1).date()
        # 保留原选中日；若目标月没有该日（例如 31 号），自动落到该月最后一天。
        last_day = calendar.monthrange(self.calendar_date.year, self.calendar_date.month)[1]
        selected_day = min(self.calendar_selected_date.day, last_day)
        self.calendar_selected_date = self.calendar_date.replace(day=selected_day)
        self.refresh_calendar_photo_data(preferred_date=self.calendar_selected_date)
        self.render_calendar()

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
        if not hasattr(self, "calendar_grid"):
            return
        self.calendar_grid.clear_widgets()
        y, m = self.calendar_date.year, self.calendar_date.month
        self.calendar_title.text = f"{y}年{m:02d}月"
        workouts = self.storage.list_workouts_for_month(y, m)
        photo_counts = self.storage.body_photo_counts()
        weeks = calendar.monthcalendar(y, m)
        while len(weeks) < 6:
            weeks.append([0] * 7)
        today = datetime.now().date()
        for week in weeks[:6]:
            for day in week:
                if day == 0:
                    self.calendar_grid.add_widget(Label(text="", font_name=FONT_NAME))
                    continue
                d = datetime(y, m, day).date()
                workout = bool(workouts.get(d.isoformat(), False))
                count = int(photo_counts.get(d.isoformat(), 0))
                selected = d == self.calendar_selected_date
                if selected:
                    fill, fg = PRIMARY, WHITE
                elif workout:
                    fill, fg = GREEN_DARK, GREEN
                elif count:
                    fill, fg = SURFACE, PURPLE
                else:
                    fill, fg = CARD_ALT, TEXT
                marker = "✓" if workout else (f"{count}图" if count else ("·" if d == today else ""))
                text = f"{day}\n{marker}" if marker else str(day)
                cell = CalendarCell(
                    text=text,
                    font_size=dp(11),
                    color=fg,
                    fill_color=fill,
                    press_color=SURFACE_DOWN,
                    corner_radius=14,
                    size_hint_y=None,
                    height=dp(43),
                )
                cell.bind(on_release=lambda _, value=d: self.select_calendar_date(value))
                self.calendar_grid.add_widget(cell)
        self.refresh_calendar_overview()
        self.refresh_week_strip()

    def select_calendar_date(self, value):
        self.calendar_selected_date = value
        self.refresh_calendar_photo_data(preferred_date=value)
        self.render_calendar()

    def toggle_selected_workout(self, *_):
        date_text = self.calendar_selected_date.isoformat()
        current = self.storage.get_workout(date_text)
        self.storage.set_workout(date_text, not current)
        self.refresh_calendar_photo_data(preferred_date=self.calendar_selected_date)
        self.render_calendar()

    def refresh_calendar_photo_data(self, preferred_date=None):
        if preferred_date is not None:
            self.calendar_selected_date = preferred_date
        date_text = self.calendar_selected_date.isoformat()
        workout = self.storage.get_workout(date_text)
        count = int(self.storage.body_photo_counts().get(date_text, 0))
        if self.calendar_selected_label is not None:
            self.calendar_selected_label.text = f"选中日期：{date_text}"
        if self.workout_button is not None:
            self.workout_button.text = "✓ 今日已打卡" if workout else "＋ 健身打卡"
            self.workout_button.fill_color = GREEN_DARK if workout else SURFACE
            self.workout_button.press_color = SURFACE_DOWN
            self.workout_button.color = GREEN if workout else TEXT
        if self.photo_count_label is not None:
            self.photo_count_label.text = f"{count} 张照片 · 选中日期的训练与照片会保存在同一天"
        self.refresh_photo_carousel(preferred_date=date_text)

    def refresh_photo_carousel(self, preferred_date=None):
        if self.photo_carousel is None:
            return
        rows = self.storage.list_body_photos()
        self.photo_rows = rows
        self.photo_pages = []
        self.photo_carousel.clear_widgets()
        if not rows:
            self.photo_carousel.add_widget(self.label("暂无体型照片\n\n请先选择一天并添加照片。", 14, MUTED))
            return
        target_index = 0
        for index, row in enumerate(rows):
            path = self.storage.body_photo_path(row)
            page = PhotoPage(row, path)
            self.photo_pages.append(page)
            self.photo_carousel.add_widget(page)
            if preferred_date and row["photo_date"] == preferred_date and target_index == 0:
                target_index = index
        self.photo_carousel.index = target_index
        Clock.schedule_once(lambda *_: self._load_photo_window(), 0)

    def _load_photo_window(self):
        if not self.photo_pages or self.photo_carousel is None:
            return
        current = int(self.photo_carousel.index)
        for i, page in enumerate(self.photo_pages):
            if abs(i - current) <= 1:
                page.load()
            else:
                page.unload()
        self._update_photo_caption()

    def on_photo_index(self, *_):
        Clock.schedule_once(lambda __: self._load_photo_window(), 0)

    def _update_photo_caption(self):
        if not self.photo_pages or self.photo_carousel is None:
            return
        idx = int(self.photo_carousel.index)
        if 0 <= idx < len(self.photo_pages):
            row = self.photo_pages[idx].photo_row
            if self.photo_date_label is not None:
                self.photo_date_label.text = f"照片：{row['photo_date']}"

    def jump_to_selected_photo(self, *_):
        if not self.photo_rows or self.photo_carousel is None:
            return
        date_text = self.calendar_selected_date.isoformat()
        for index, row in enumerate(self.photo_rows):
            if row["photo_date"] == date_text:
                self.photo_carousel.index = index
                self._load_photo_window()
                return
        self.info("没有照片", f"{date_text} 暂无体型照片。")

    def add_body_photo(self, *_):
        if not ANDROID_AVAILABLE:
            self.info("仅支持 Android", "照片选择器需要在 Android APK 中使用。")
            return
        self._photo_pending_date = self.calendar_selected_date.isoformat()
        try:
            try:
                android_activity.unbind(on_activity_result=self.on_activity_result)
            except Exception:
                pass
            android_activity.bind(on_activity_result=self.on_activity_result)
            Intent = autoclass("android.content.Intent")
            Build = autoclass("android.os.Build")
            Activity = autoclass("android.app.Activity")
            current_activity = cast("android.app.Activity", autoclass("org.kivy.android.PythonActivity").mActivity)
            if int(Build.VERSION.SDK_INT) >= 33:
                intent = Intent("android.provider.action.PICK_IMAGES")
            else:
                intent = Intent(Intent.ACTION_OPEN_DOCUMENT)
                intent.addCategory(Intent.CATEGORY_OPENABLE)
            intent.setType("image/*")
            current_activity.startActivityForResult(intent, PHOTO_PICK_REQUEST)
        except Exception as exc:
            try:
                android_activity.unbind(on_activity_result=self.on_activity_result)
            except Exception:
                pass
            self.info("打开照片选择器失败", str(exc))

    def on_activity_result(self, request_code, result_code, intent):
        if request_code != PHOTO_PICK_REQUEST:
            return
        try:
            android_activity.unbind(on_activity_result=self.on_activity_result)
        except Exception:
            pass
        if not ANDROID_AVAILABLE:
            return
        Activity = autoclass("android.app.Activity")
        if int(result_code) != int(Activity.RESULT_OK) or intent is None:
            return
        try:
            uri = intent.getData()
            if uri is None:
                return
            date_text = self._photo_pending_date or datetime.now().date().isoformat()
            Clock.schedule_once(lambda *_: self._import_photo_uri(uri, date_text), 0)
        except Exception as exc:
            Clock.schedule_once(lambda *_: self.info("照片读取失败", str(exc)), 0)

    def _import_photo_uri(self, uri, date_text):
        target = None
        try:
            base = Path(self.user_data_dir) / "body_photos"
            base.mkdir(parents=True, exist_ok=True)
            current_activity = cast("android.app.Activity", autoclass("org.kivy.android.PythonActivity").mActivity)
            resolver = current_activity.getContentResolver()
            mime = resolver.getType(uri) or "image/jpeg"
            ext = mimetypes.guess_extension(str(mime)) or ".jpg"
            if ext == ".jpe":
                ext = ".jpg"
            target = base / f"{date_text.replace('-', '')}_{datetime.now():%H%M%S}_{uuid4().hex[:8]}{ext}"
            input_stream = resolver.openInputStream(uri)
            if input_stream is None:
                raise ValueError("无法读取所选照片")
            buffer = jarray("b", [0] * 65536)
            with open(target, "wb") as output:
                while True:
                    n = input_stream.read(buffer)
                    if n is None or int(n) <= 0:
                        break
                    output.write(bytes((int(value) & 0xFF) for value in buffer[: int(n)]))
            input_stream.close()
            self.storage.add_body_photo(date_text, target)
            self.refresh_calendar_photo_data(preferred_date=date_text)
            self.render_calendar()
            self.info("照片已保存", f"已保存到 {date_text}。")
        except Exception as exc:
            if target is not None:
                try:
                    target.unlink()
                except OSError:
                    pass
            self.info("保存照片失败", str(exc))

    def delete_current_photo(self, *_):
        if not self.photo_pages or self.photo_carousel is None:
            self.info("没有照片", "当前没有可删除的照片。")
            return
        index = int(self.photo_carousel.index)
        if index < 0 or index >= len(self.photo_pages):
            return
        row = self.photo_pages[index].photo_row
        try:
            self.storage.create_full_backup()
            self.storage.delete_body_photo(row["id"])
            self.refresh_calendar_photo_data(preferred_date=self.calendar_selected_date.isoformat())
            self.render_calendar()
        except Exception as exc:
            self.info("删除照片失败", str(exc))

    def full_backup(self, *_):
        try:
            path = self.storage.create_full_backup()
            if path is None:
                self.info("备份失败", "当前没有可备份的数据。")
            else:
                self.info("完整备份完成", f"已生成：\n{path.name}\n\n备份包含数据库和所有体型照片。")
        except Exception as exc:
            self.info("备份失败", str(exc))
