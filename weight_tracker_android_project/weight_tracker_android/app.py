"""Thin application shell with four persistent top-level destinations."""
from datetime import datetime

from kivy.app import App
from kivy.core.window import Window
from kivy.metrics import dp
from kivy.utils import get_color_from_hex
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.textinput import TextInput

from storage import Storage
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
        self.title = "体重追踪助手"
        self.storage = Storage(self.user_data_dir)
        self.end_date = datetime.now().date()
        self.window_days = int(self.storage.get_setting("window_days") or 30)
        self.height_cm = self._float_setting("height_cm")
        self.target_weight = self._float_setting("target_weight")
        self.theme = self.storage.get_setting("theme") or "深色"
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
        self.photo_carousel = None
        self.photo_pages = []
        self.photo_rows = []
        self.photo_date_label = None
        self.photo_counter_label = None
        self.progress_summary_label = None
        self._photo_pending_date = None

        Window.clearcolor = BG
        root = BoxLayout(orientation="vertical", padding=(dp(7), dp(8), dp(7), dp(5)), spacing=dp(7))
        self.screen_host = BoxLayout(orientation="vertical")
        root.add_widget(self.screen_host)
        self.navigation = BottomNavigation(self)
        root.add_widget(self.navigation.root)
        self.screen_widgets = {}
        self.current_screen = None
        self.navigate_to("home")
        return root

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
            self.refresh_photo_carousel(preferred_date=self.progress_filter_date)
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
        """Refresh today's glance cards without rebuilding whichever screen is open."""
        today = datetime.now().date()
        today_start = datetime.combine(today, datetime.min.time())
        today_end = datetime.combine(today, datetime.max.time())
        today_records = self.storage.list_records(today_start, today_end)
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

        trained = self.storage.get_workout(today.isoformat())
        if getattr(self, "home_workout_status", None) is not None:
            self.home_workout_status.text = "✓ 今日已打卡" if trained else "今天还没打卡"
            self.home_workout_status.color = GREEN if trained else MUTED
        if getattr(self, "home_workout_button", None) is not None:
            self.home_workout_button.text = "✓  已完成健身" if trained else "＋  完成健身打卡"
            self.home_workout_button.fill_color = GREEN_DARK if trained else CARD_ALT
            self.home_workout_button.color = GREEN if trained else TEXT

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
