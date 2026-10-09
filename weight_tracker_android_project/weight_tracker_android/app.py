"""Application shell and main weight-entry screen."""

from datetime import datetime

from kivy.app import App
from kivy.metrics import dp
from kivy.core.window import Window
from kivy.utils import get_color_from_hex
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.checkbox import CheckBox
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.scrollview import ScrollView
from kivy.uix.spinner import Spinner, SpinnerOption
from kivy.uix.textinput import TextInput

from services.android_bridge import ANDROID_AVAILABLE, android_activity
from storage import Storage
from ui.calendar_feature import CalendarFeatureMixin
from ui.records_feature import RecordsFeatureMixin
from ui.settings_feature import SettingsFeatureMixin
from ui.theme import (BG, CARD, CARD_ALT, FIELD_BG, FONT_NAME, GREEN, GREEN_DARK, MUTED,
                      PRIMARY, PRIMARY_DARK, PURPLE, SURFACE, SURFACE_DOWN, TEXT, WHITE)
from ui.widgets import PlotWidget, RoundedButton, RoundedPanel

class WeightApp(CalendarFeatureMixin, RecordsFeatureMixin, SettingsFeatureMixin, App):
    """Kivy application shell; behavior is separated into focused feature mixins."""

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
        self.calendar_popup = None
        self.calendar_date = datetime.now().date().replace(day=1)
        self.calendar_selected_date = datetime.now().date()
        self.photo_pages = []
        self.photo_rows = []
        self.photo_carousel = None
        self.photo_date_label = None
        self.workout_button = None
        self.photo_count_label = None
        self._photo_pending_date = None

        Window.clearcolor = BG
        root = BoxLayout(orientation="vertical", padding=(dp(12), dp(10)), spacing=dp(9))
        root.add_widget(self.build_header())
        root.add_widget(self.build_input())
        root.add_widget(self.build_stats())
        root.add_widget(self.build_nav())
        root.add_widget(self.build_settings())
        self.plot = PlotWidget(size_hint_y=1, on_point=self.edit_record)
        root.add_widget(self.plot)
        self.refresh()
        return root

    def build_header(self):
        panel = RoundedPanel(
            orientation="horizontal", padding=(dp(14), dp(8)), spacing=dp(8),
            size_hint_y=None, height=dp(62), panel_color=CARD,
        )
        brand = BoxLayout(orientation="vertical", spacing=dp(1))
        brand.add_widget(Label(text="FIT  /  TRACK", font_name=FONT_NAME, font_size=dp(11),
                               bold=True, color=PRIMARY, halign="left", valign="middle",
                               text_size=(None, None), size_hint_y=None, height=dp(18)))
        brand.add_widget(Label(text="体重 · 训练 · 身材进度", font_name=FONT_NAME, font_size=dp(17),
                               bold=True, color=TEXT, halign="left", valign="middle"))
        panel.add_widget(brand)
        calendar_btn = self.button("日历 / 健身", self.open_calendar, 40, tone="primary")
        calendar_btn.size_hint_x = None
        calendar_btn.width = dp(112)
        panel.add_widget(calendar_btn)
        return panel

    def label(self, text, size=14, color=TEXT, bold=False):
        return Label(text=text, color=color, font_size=dp(size), bold=bold, font_name=FONT_NAME)

    def button(self, text, callback, height=42, tone="secondary"):
        tones = {
            "primary": (PRIMARY, PRIMARY_DARK, WHITE),
            "secondary": (SURFACE, SURFACE_DOWN, TEXT),
            "success": (GREEN_DARK, get_color_from_hex("#41593B"), GREEN),
            "soft": (CARD_ALT, SURFACE_DOWN, TEXT),
        }
        fill, pressed, fg = tones.get(tone, tones["secondary"])
        b = RoundedButton(
            text=text,
            size_hint_y=None,
            height=dp(height),
            fill_color=fill,
            press_color=pressed,
            color=fg,
            font_size=dp(13),
            corner_radius=18,
        )
        b.bind(on_release=callback)
        return b

    def _field(self, **kwargs):
        defaults = dict(
            multiline=False,
            font_name=FONT_NAME,
            font_size=dp(14),
            foreground_color=TEXT,
            hint_text_color=MUTED,
            cursor_color=PRIMARY,
            background_normal="",
            background_active="",
            background_color=(0, 0, 0, 0),
            padding=(dp(8), dp(8)),
            write_tab=False,
        )
        defaults.update(kwargs)
        return TextInput(**defaults)

    def _field_box(self, field, size_hint_x=1):
        box = RoundedPanel(orientation="vertical", padding=(dp(8), dp(2)),
                           panel_color=FIELD_BG, corner_radius=13, size_hint_x=size_hint_x)
        field.size_hint = (1, 1)
        box.add_widget(field)
        return box

    def build_input(self):
        card = RoundedPanel(
            orientation="vertical", padding=dp(11), spacing=dp(7),
            size_hint_y=None, height=dp(176), panel_color=CARD,
        )
        title_row = BoxLayout(size_hint_y=None, height=dp(22))
        title_row.add_widget(self.label("每日体重记录", 14, TEXT, True))
        title_row.add_widget(self.label("小步进步 · 持续变强", 11, MUTED))
        card.add_widget(title_row)

        row1 = BoxLayout(spacing=dp(7), size_hint_y=None, height=dp(40))
        self.date_input = self._field(text=datetime.now().strftime("%Y-%m-%d %H:%M"), hint_text="日期 / 时间")
        self.weight_input = self._field(input_filter="float", hint_text="体重（斤）")
        row1.add_widget(self._field_box(self.date_input, size_hint_x=0.66))
        row1.add_widget(self._field_box(self.weight_input, size_hint_x=0.34))
        card.add_widget(row1)

        row2 = BoxLayout(spacing=dp(7), size_hint_y=None, height=dp(38))
        self.note_input = self._field(hint_text="备注：晨起、运动后……")
        save_btn = self.button("保存记录", self.save_record, 38, tone="primary")
        save_btn.size_hint_x = None
        save_btn.width = dp(98)
        row2.add_widget(self._field_box(self.note_input))
        row2.add_widget(save_btn)
        card.add_widget(row2)

        quick_scroll = ScrollView(size_hint_y=None, height=dp(34), do_scroll_x=True, do_scroll_y=False,
                                  bar_width=dp(2), scroll_type=["bars", "content"])
        quick = BoxLayout(size_hint_x=None, width=dp(682), spacing=dp(5))
        quick.add_widget(self.label("快捷", 11, MUTED, True))
        for txt, delta in [("−1斤", -1), ("−0.5斤", -0.5), ("上次", 0), ("+0.5斤", 0.5), ("+1斤", 1)]:
            b = RoundedButton(text=txt, size_hint_x=None, width=dp(67), size_hint_y=None, height=dp(32),
                              font_size=dp(11), fill_color=SURFACE, press_color=SURFACE_DOWN, color=TEXT,
                              corner_radius=15)
            b.bind(on_release=lambda _, d=delta: self.quick_weight(d))
            quick.add_widget(b)
        for txt in ("晨起", "运动后", "睡前"):
            b = RoundedButton(text=txt, size_hint_x=None, width=dp(68), size_hint_y=None, height=dp(32),
                              font_size=dp(11), fill_color=GREEN_DARK, press_color=SURFACE_DOWN, color=GREEN,
                              corner_radius=15)
            b.bind(on_release=lambda _, t=txt: self.set_note(t))
            quick.add_widget(b)
        quick_scroll.add_widget(quick)
        card.add_widget(quick_scroll)
        return card

    def build_stats(self):
        self.stats = {}
        card = RoundedPanel(orientation="vertical", padding=(dp(10), dp(8)), spacing=dp(5),
                            size_hint_y=None, height=dp(100), panel_color=CARD)
        card.add_widget(self.label("近段时间概览", 12, MUTED, True))
        grid = GridLayout(cols=5, spacing=dp(4), size_hint_y=None, height=dp(58))
        for key, title in [("avg", "平均体重"), ("max", "最高"), ("min", "最低"), ("diff", "变化"), ("bmi", "BMI")]:
            cell = BoxLayout(orientation="vertical", spacing=dp(2))
            cell.add_widget(self.label(title, 10, MUTED))
            val = self.label("--", 15, PURPLE, True)
            self.stats[key] = val
            cell.add_widget(val)
            grid.add_widget(cell)
        card.add_widget(grid)
        return card

    def build_nav(self):
        row = RoundedPanel(orientation="horizontal", padding=(dp(8), dp(6)), spacing=dp(6),
                           size_hint_y=None, height=dp(48), panel_color=CARD)
        left = self.button("‹", self.prev_period, 34, tone="soft")
        left.size_hint_x = None
        left.width = dp(42)
        row.add_widget(left)
        self.range_label = self.label("", 11, TEXT, True)
        row.add_widget(self.range_label)
        right = self.button("›", self.next_period, 34, tone="soft")
        right.size_hint_x = None
        right.width = dp(42)
        row.add_widget(right)
        today_btn = self.button("今天", self.today, 34, tone="primary")
        today_btn.size_hint_x = None
        today_btn.width = dp(60)
        row.add_widget(today_btn)
        return row

    def build_settings(self):
        card = RoundedPanel(orientation="horizontal", padding=(dp(6), dp(6)), spacing=dp(5),
                            size_hint_y=None, height=dp(50), panel_color=CARD)
        scroll = ScrollView(size_hint=(1, 1), do_scroll_x=True, do_scroll_y=False,
                            bar_width=dp(2), scroll_type=["bars", "content"])
        row = BoxLayout(size_hint_x=None, width=dp(866), spacing=dp(5))
        row.add_widget(self.label("范围", 11, MUTED, True))
        self.days_spinner = Spinner(text=str(self.window_days), values=[str(i) for i in (7, 14, 30, 60, 90, 180, 365)],
                                    size_hint_x=None, width=dp(58), font_name=FONT_NAME,
                                    option_cls=SpinnerOption, background_normal="", background_color=SURFACE,
                                    color=TEXT, font_size=dp(12))
        self.days_spinner.bind(text=self.change_days)
        row.add_widget(self.days_spinner)
        self.bmi_cb = CheckBox(active=False, size_hint_x=None, width=dp(26))
        self.bmi_cb.bind(active=lambda _, value: self.toggle_bmi(value))
        row.add_widget(self.bmi_cb)
        row.add_widget(self.label("BMI", 11, MUTED))
        self.labels_cb = CheckBox(active=False, size_hint_x=None, width=dp(26))
        self.labels_cb.bind(active=lambda _, value: self.toggle_labels(value))
        row.add_widget(self.labels_cb)
        row.add_widget(self.label("数值", 11, MUTED))
        for txt, cb, width in [("身高", self.ask_height, 56), ("目标", self.ask_target, 56),
                               ("导出", self.export_csv, 56), ("导入", self.import_csv, 56),
                               ("回收站", self.open_recycle, 66), ("清空", self.clear_form, 56)]:
            b = self.button(txt, cb, 34, tone="soft")
            b.size_hint_x = None
            b.width = dp(width)
            row.add_widget(b)
        scroll.add_widget(row)
        card.add_widget(scroll)
        return card
