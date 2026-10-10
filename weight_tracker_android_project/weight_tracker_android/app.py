"""Thin application shell with four persistent top-level destinations."""
from datetime import datetime
import logging
from threading import Thread
from time import perf_counter

from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.metrics import dp
from kivy.utils import get_color_from_hex
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.textinput import TextInput
from kivy.uix.widget import Widget
from kivy.uix.popup import Popup

from storage import Storage
from services.performance import mark
from ui.calendar_feature import CalendarFeatureMixin
from ui.screens.calendar_screen import CalendarScreenMixin
from ui.navigation import BottomNavigation
from ui.screens.home_screen import HomeScreenMixin
from ui.screens.progress_screen import ProgressScreenMixin
from ui.screens.profile_screen import ProfileScreenMixin
from ui.records_feature import RecordsFeatureMixin
from ui.settings_feature import SettingsFeatureMixin
from ui.theme import (BG, CARD, CARD_ALT, FIELD_BG, FONT_NAME, GREEN, GREEN_DARK,
                      MUTED, PRIMARY, PRIMARY_DARK, SURFACE, SURFACE_DOWN, TEXT, WHITE)
from ui.widgets import RoundedButton, RoundedPanel


class WeightApp(HomeScreenMixin, CalendarScreenMixin, CalendarFeatureMixin, ProgressScreenMixin,
                ProfileScreenMixin, RecordsFeatureMixin, SettingsFeatureMixin, App):
    """App coordinator; each main destination is built in its own module."""

    def build(self):
        """Return a lightweight shell immediately; initialize SQLite off the UI thread."""
        build_started = perf_counter()
        mark("app_build_enter")
        self.title = "体重追踪助手"
        self._startup_base_dir = self.user_data_dir
        self.storage = None
        self.end_date = datetime.now().date()
        self.window_days = 30
        self.height_cm = None
        self.target_weight = None
        self.theme = "深色"
        self.show_bmi = False
        self.show_labels = False

        self.calendar_date = datetime.now().date().replace(day=1)
        self.calendar_selected_date = datetime.now().date()
        self.progress_filter_date = None
        self.calendar_screen_widget = None
        self.calendar_grid = None
        self.calendar_overview_labels = None
        self.calendar_selected_label = None
        self.calendar_detail_subtitle = None
        self.workout_button = None
        self.photo_count_label = None
        self.week_strip = None
        self.photo_browser_card = None
        self.photo_rows = []
        self.photo_date_label = None
        self.photo_counter_label = None
        self.progress_summary_label = None
        self.photo_selection_hint = None
        self._photo_pending_date = None
        self._background_task_busy = False
        self._thumbnail_jobs = set()
        self._thumbnail_failed_ids = set()
        self._photo_current_index = 0
        self._compare_before_index = None
        self._compare_after_index = None
        self._calendar_total_photo_count = None
        self._calendar_cache_month = None
        self._calendar_cache_workouts = {}
        self._calendar_cache_photo_counts = {}
        self._home_summary_generation = 0
        self._startup_finished = False
        self._startup_in_progress = False

        Window.clearcolor = BG
        root = BoxLayout(orientation="vertical", padding=(dp(7), dp(8), dp(7), dp(5)), spacing=dp(7))
        self.root_layout = root
        self.screen_host = BoxLayout(orientation="vertical")
        root.add_widget(self.screen_host)
        # Keep the lower region absent until the navigation buttons are ready.
        self.bottom_nav_host = BoxLayout(orientation="vertical", size_hint_y=None, height=0)
        root.add_widget(self.bottom_nav_host)
        splash = RoundedPanel(orientation="vertical", padding=dp(20), spacing=dp(10), panel_color=CARD)
        splash.add_widget(Widget())
        splash.add_widget(self.label("体重追踪助手", 21, TEXT, True))
        splash.add_widget(self.label("正在准备本地数据…", 12, MUTED))
        splash.add_widget(Widget())
        self.startup_splash = splash
        self.screen_host.add_widget(splash)
        self.navigation = None
        self.screen_widgets = {}
        self.current_screen = None

        self._start_storage_initialization()
        mark("startup_shell_ready", build_started)
        return root

    def _start_storage_initialization(self):
        """Initialize the DB and fetch a few preferences without blocking Kivy's first frame."""
        if self._startup_in_progress:
            return
        self._startup_in_progress = True
        data_dir = self._startup_base_dir

        def worker():
            started = perf_counter()
            try:
                storage = Storage(data_dir)
                settings = {
                    key: storage.get_setting(key)
                    for key in ("window_days", "height_cm", "target_weight", "theme")
                }
                mark("startup_storage_ready", started)
                Clock.schedule_once(lambda _dt: self._complete_startup(storage, settings), 0.05)
            except Exception as exc:
                Clock.schedule_once(lambda _dt, err=exc: self._startup_failed(err), 0.05)

        Thread(target=worker, name="startup-storage-init", daemon=True).start()

    def _complete_startup(self, storage, settings):
        if self._startup_finished:
            return
        self.storage = storage
        try:
            self.window_days = int(settings.get("window_days") or 30)
            if self.window_days < 1:
                self.window_days = 30
        except (TypeError, ValueError):
            self.window_days = 30
        self.height_cm = self._parse_optional_float(settings.get("height_cm"))
        self.target_weight = self._parse_optional_float(settings.get("target_weight"))
        self.theme = settings.get("theme") or "深色"
        self._startup_finished = True
        self._startup_in_progress = False

        self.screen_host.clear_widgets()
        self.bottom_nav_host.height = dp(66)
        self.navigation = BottomNavigation(self)
        self.bottom_nav_host.add_widget(self.navigation.root)
        self.screen_widgets = {}
        self.current_screen = None
        ui_build_started = perf_counter()
        mark("startup_ui_build_start")
        self.navigate_to("home")
        mark("startup_first_screen_ready", ui_build_started)

    @staticmethod
    def _parse_optional_float(value):
        try:
            parsed = float(value) if value not in (None, "") else None
            if parsed is None or not (parsed > 0 and parsed < float("inf")):
                return None
            return parsed
        except (TypeError, ValueError):
            return None

    def _startup_failed(self, error):
        self._startup_in_progress = False
        self.screen_host.clear_widgets()
        panel = RoundedPanel(orientation="vertical", padding=dp(18), spacing=dp(10), panel_color=CARD)
        panel.add_widget(Widget())
        panel.add_widget(self.label("应用启动失败", 18, TEXT, True))
        panel.add_widget(self.label(f"本地数据初始化失败：{error}", 11, MUTED))
        panel.add_widget(self.button("重试", lambda *_: self._retry_startup(), 42, tone="primary"))
        panel.add_widget(Widget())
        self.screen_host.add_widget(panel)
        mark("startup_failed", error_type=type(error).__name__)

    def _retry_startup(self):
        self.screen_host.clear_widgets()
        self.screen_host.add_widget(self.startup_splash)
        self._startup_finished = False
        self._start_storage_initialization()

    def open_progress_home(self, *_):
        """Open the full photo timeline without carrying an old calendar filter."""
        self.progress_filter_date = None
        self.navigate_to("progress")

    def navigate_to(self, route, *_):
        builders = {
            "home": self.build_home_screen,
            "calendar": self.build_calendar_screen,
            "progress": self.build_progress_screen,
            "profile": self.build_profile_screen,
        }
        if route not in builders:
            route = "home"
        if route not in self.screen_widgets:
            self.screen_widgets[route] = builders[route]()
        self.screen_host.clear_widgets()
        self.screen_host.add_widget(self.screen_widgets[route])
        self.current_screen = route
        self.navigation.set_active(route)

        if route == "home":
            self.refresh()
        elif route == "calendar":
            self.render_calendar()
            self.refresh_calendar_photo_data(preferred_date=self.calendar_selected_date)
        elif route == "progress":
            self.refresh_photo_browser(preferred_date=self.progress_filter_date)
        elif route == "profile":
            self.refresh_profile_summary()
        return self.screen_widgets[route]

    def label(self, text, size=14, color=TEXT, bold=False, **kwargs):
        return Label(text=text, color=color, font_size=dp(size), bold=bold,
                     font_name=FONT_NAME, **kwargs)

    def button(self, text, callback, height=42, tone="secondary"):
        tones = {
            "primary": (PRIMARY, PRIMARY_DARK, WHITE),
            "secondary": (SURFACE, SURFACE_DOWN, TEXT),
            "success": (GREEN_DARK, get_color_from_hex("#41593B"), GREEN),
            "soft": (CARD_ALT, SURFACE_DOWN, TEXT),
        }
        fill, pressed, fg = tones.get(tone, tones["secondary"])
        btn = RoundedButton(
            text=text, size_hint_y=None, height=dp(height), fill_color=fill,
            press_color=pressed, color=fg, font_size=dp(12), corner_radius=16,
            font_name=FONT_NAME,
        )
        btn.bind(on_release=callback)
        return btn

    def _field(self, **kwargs):
        defaults = dict(
            multiline=False, font_name=FONT_NAME, font_size=dp(14),
            foreground_color=TEXT, hint_text_color=MUTED, cursor_color=PRIMARY,
            background_normal="", background_active="", background_color=(0, 0, 0, 0),
            padding=(dp(8), dp(8)), write_tab=False,
        )
        defaults.update(kwargs)
        return TextInput(**defaults)

    def _field_box(self, field, size_hint_x=1):
        box = RoundedPanel(orientation="vertical", padding=(dp(8), dp(2)),
                           panel_color=FIELD_BG, corner_radius=13, size_hint_x=size_hint_x)
        field.size_hint = (1, 1)
        box.add_widget(field)
        return box

    def refresh_home_summary(self):
        """Query today's cards off the UI thread and apply only the newest result."""
        storage = getattr(self, "storage", None)
        if storage is None:
            return
        self._home_summary_generation = getattr(self, "_home_summary_generation", 0) + 1
        generation = self._home_summary_generation
        today = datetime.now().date()
        today_start = datetime.combine(today, datetime.min.time())
        today_end = datetime.combine(today, datetime.max.time())

        def worker():
            started = perf_counter()
            try:
                today_records = storage.list_records(today_start, today_end)
                trained = storage.get_workout(today.isoformat())
                Clock.schedule_once(
                    lambda _dt: self._apply_home_summary(today_records, trained, generation), 0
                )
                mark("home_summary_query_complete", started, rows=len(today_records))
            except Exception as exc:
                logging.exception("Home summary query failed")
                Clock.schedule_once(lambda _dt, err=exc: self._startup_or_summary_error(err), 0)

        Thread(target=worker, name="home-summary-query", daemon=True).start()

    def _apply_home_summary(self, today_records, trained, generation=None):
        if generation is not None and generation != self._home_summary_generation:
            return
        if getattr(self, "home_today_value", None) is not None:
            if today_records:
                latest = today_records[-1]
                self.home_today_value.text = f"{float(latest['weight']):.1f}"
                self.home_today_hint.text = "今天已记录"
                self.home_today_change.text = f"最近记录 · {latest['recorded_at'][11:16]}"
            else:
                self.home_today_value.text = "待记录"
                self.home_today_hint.text = "今天还没有记录"
                self.home_today_change.text = "记录一次，持续关注变化"

        if getattr(self, "home_workout_status", None) is not None:
            self.home_workout_status.text = "✓ 今日已打卡" if trained else "今天还没打卡"
            self.home_workout_status.color = GREEN if trained else MUTED
        if getattr(self, "home_workout_button", None) is not None:
            self.home_workout_button.text = "✓  已完成健身" if trained else "＋  完成健身打卡"
            self.home_workout_button.fill_color = GREEN_DARK if trained else CARD_ALT
            self.home_workout_button.color = GREEN if trained else TEXT

    def _startup_or_summary_error(self, error):
        logging.error("Summary update failed: %s", error)

    def run_background_task(self, title, worker, on_success=None, on_error=None):
        """Run disk/CPU-heavy work away from Kivy's UI thread.

        All widget mutations happen in the Clock callback on the UI thread.
        Only one user-visible heavy task is allowed at once to avoid overlapping
        ZIP creation, photo imports, or destructive backup/delete operations.
        """
        if self._background_task_busy:
            self.info("正在处理中", "上一项操作尚未完成，请稍候再试。")
            return False
        self._background_task_busy = True
        popup_content = RoundedPanel(orientation="vertical", padding=dp(16), spacing=dp(8),
                                     panel_color=CARD, corner_radius=20)
        status = self.label(str(title), 14, TEXT, True)
        hint = self.label("正在后台处理，完成后会自动通知你。", 11, MUTED)
        popup_content.add_widget(status)
        popup_content.add_widget(hint)
        popup = Popup(title="请稍候", title_font=FONT_NAME, title_color=TEXT,
                      content=popup_content, size_hint=(.88, None), height=dp(150),
                      background="atlas://data/images/defaulttheme/modalview-background",
                      background_color=CARD, separator_color=(0, 0, 0, 0),
                      auto_dismiss=True)
        popup.open()

        def finish(_dt, result=None, error=None):
            self._background_task_busy = False
            try:
                popup.dismiss()
            except Exception:
                pass
            if error is not None:
                logging.exception("Background task failed", exc_info=(type(error), error, error.__traceback__))
                if on_error:
                    on_error(error)
                else:
                    self.info(f"{title}失败", f"{type(error).__name__}: {error}")
                return
            if on_success:
                try:
                    on_success(result)
                except Exception as exc:
                    logging.exception("Background task completion callback failed")
                    self.info("界面更新失败", f"任务已完成，但刷新界面时发生错误：{exc}")

        def work():
            try:
                result = worker()
            except Exception as exc:
                Clock.schedule_once(lambda dt, err=exc: finish(dt, error=err), 0)
            else:
                Clock.schedule_once(lambda dt, value=result: finish(dt, result=value), 0)

        Thread(target=work, name="weight-tracker-task", daemon=True).start()
        return True

    def info(self, title, message):
        from kivy.uix.popup import Popup
        content = RoundedPanel(orientation="vertical", padding=dp(14), spacing=dp(12),
                               panel_color=CARD)
        content.add_widget(self.label(str(message), 13, TEXT))
        content.add_widget(self.button("知道了", lambda *_: popup.dismiss(), 40, tone="primary"))
        popup = Popup(title=str(title), title_font=FONT_NAME, title_color=TEXT,
                      content=content, size_hint=(.9, None), height=dp(190),
                      background="", separator_color=(0, 0, 0, 0))
        popup.open()
