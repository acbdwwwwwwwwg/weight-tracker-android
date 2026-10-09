from __future__ import annotations

import calendar
import csv
import mimetypes
import shutil
import zipfile
from uuid import uuid4
from datetime import datetime, timedelta
from pathlib import Path

from kivy.app import App
from kivy.clock import Clock
from kivy.graphics import Color, Line, Ellipse, Rectangle, RoundedRectangle
from kivy.metrics import dp
from kivy.properties import ListProperty, NumericProperty, StringProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.carousel import Carousel
from kivy.uix.image import Image
from kivy.uix.button import Button
from kivy.uix.checkbox import CheckBox
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView
from kivy.uix.spinner import Spinner, SpinnerOption
from kivy.uix.textinput import TextInput
from kivy.utils import get_color_from_hex
from kivy.core.text import LabelBase
from kivy.core.window import Window
from kivy.lang import Builder

from storage import Storage


# Android API 仅在 APK 中可用；桌面运行时保持可用。
try:
    from android import activity as android_activity
    from jnius import autoclass, cast, jarray
    ANDROID_AVAILABLE = True
except Exception:
    android_activity = None
    autoclass = cast = jarray = None
    ANDROID_AVAILABLE = False


PHOTO_PICK_REQUEST = 4101


# -----------------------------------------------------------------------------
# 中文字体支持
# -----------------------------------------------------------------------------
# 将简体中文字体随 APK 一起打包，并注册为 Kivy 的字体别名。
# 这样 Label / Button / TextInput / Spinner / Popup 标题等控件都可以显示中文。
APP_DIR = Path(__file__).resolve().parent
FONT_DIR = APP_DIR / "fonts"
FONT_CANDIDATES = [
    FONT_DIR / "NotoSansCJKsc-Regular.ttf",
    FONT_DIR / "NotoSansCJKsc-Regular.otf",
]
# Android AOSP 在系统字体中包含 Noto Sans CJK；如项目未携带字体则尝试使用系统字体。
if ANDROID_AVAILABLE:
    FONT_CANDIDATES.extend([
        Path("/system/fonts/NotoSansCJK-Regular.ttc"),
        Path("/system/fonts/NotoSansCJKsc-Regular.otf"),
        Path("/system/fonts/NotoSansSC-Regular.otf"),
    ])

FONT_NAME = "Roboto"
for _font in FONT_CANDIDATES:
    if _font.exists():
        try:
            LabelBase.register(
                "NotoSansSC",
                fn_regular=str(_font),
                fn_italic=str(_font),
                fn_bold=str(_font),
                fn_bolditalic=str(_font),
            )
            FONT_NAME = "NotoSansSC"
            FONT_REGULAR = _font
            break
        except Exception:
            continue
else:
    FONT_REGULAR = None

# 必须在任何界面控件创建前应用 KV 默认字体规则。
Builder.load_string(
    f'''
<Label>:
    font_name: "{FONT_NAME}"
<Button>:
    font_name: "{FONT_NAME}"
<TextInput>:
    font_name: "{FONT_NAME}"
<Spinner>:
    font_name: "{FONT_NAME}"
<SpinnerOption>:
    font_name: "{FONT_NAME}"
<Popup>:
    title_font: "{FONT_NAME}"
'''
)


# 深色健身主题：炭黑底色、圆角面板、珊瑚红重点色与清爽薄荷绿状态色。
BG = get_color_from_hex("#101016")
CARD = get_color_from_hex("#1B1A22")
CARD_ALT = get_color_from_hex("#25232D")
CARD_DARK = get_color_from_hex("#17161D")
SURFACE = get_color_from_hex("#2D2B36")
SURFACE_DOWN = get_color_from_hex("#3A3744")
PRIMARY = get_color_from_hex("#FF626B")
PRIMARY_DARK = get_color_from_hex("#E94E5B")
TEXT = get_color_from_hex("#F7F5FA")
MUTED = get_color_from_hex("#A39EAF")
GREEN = get_color_from_hex("#B8F28B")
GREEN_DARK = get_color_from_hex("#364A32")
PURPLE = get_color_from_hex("#AAA5FF")
LINE_COLOR = get_color_from_hex("#383541")
WHITE = get_color_from_hex("#FFFFFF")
FIELD_BG = get_color_from_hex("#272530")



def as_dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


class PlotWidget(BoxLayout):
    points = ListProperty([])
    labels = ListProperty([])
    target = NumericProperty(0)
    show_labels = False
    on_point = None

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.orientation = "vertical"
        self.bind(size=self.redraw, pos=self.redraw, points=self.redraw, target=self.redraw)

    def redraw(self, *_):
        self.canvas.clear()
        with self.canvas:
            Color(*CARD)
            RoundedRectangle(pos=self.pos, size=self.size, radius=[(dp(24), dp(24))] * 4)
            x0 = self.x + dp(28)
            y0 = self.y + dp(36)
            w = max(dp(50), self.width - dp(44))
            h = max(dp(50), self.height - dp(62))
            Color(*LINE_COLOR)
            for i in range(5):
                yy = y0 + i * h / 4
                Line(points=[x0, yy, x0 + w, yy], width=1)
            if not self.points:
                return
            ys = [p[1] for p in self.points]
            lo = min(ys)
            hi = max(ys)
            if self.target:
                lo = min(lo, self.target)
                hi = max(hi, self.target)
            span = hi - lo if hi > lo else 1.0
            coords = []
            for idx, (xv, yv, rid, raw) in enumerate(self.points):
                xx = x0 + (idx / max(1, len(self.points) - 1)) * w
                yy = y0 + ((yv - lo) / span) * h
                coords.extend([xx, yy])
                Color(*PRIMARY)
                Ellipse(pos=(xx - dp(4), yy - dp(4)), size=(dp(8), dp(8)))
            Color(*PRIMARY)
            if len(coords) >= 4:
                Line(points=coords, width=dp(2))
            if self.target:
                ty = y0 + ((self.target - lo) / span) * h
                Color(*GREEN)
                Line(points=[x0, ty, x0 + w, ty], width=dp(1.3), dash_offset=2, dash_length=4)

    def on_touch_down(self, touch):
        if not self.collide_point(*touch.pos) or not self.points:
            return super().on_touch_down(touch)
        x0 = self.x + dp(28)
        w = max(dp(50), self.width - dp(44))
        ys = [p[1] for p in self.points]
        lo = min(ys)
        hi = max(ys)
        span = hi - lo if hi > lo else 1.0
        y0 = self.y + dp(36)
        h = max(dp(50), self.height - dp(62))
        best = None
        bestd = 1e9
        for idx, (xv, yv, rid, raw) in enumerate(self.points):
            xx = x0 + (idx / max(1, len(self.points) - 1)) * w
            yy = y0 + ((yv - lo) / span) * h
            d = (touch.x - xx) ** 2 + (touch.y - yy) ** 2
            if d < bestd:
                bestd = d
                best = raw
        if best is not None and bestd <= dp(20) ** 2 and self.on_point:
            self.on_point(best)
            return True
        return super().on_touch_down(touch)




class RoundedPanel(BoxLayout):
    """轻量圆角卡片，避免额外图片资源并适配不同屏幕尺寸。"""
    panel_color = ListProperty(CARD)
    corner_radius = NumericProperty(22)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        with self.canvas.before:
            self._panel_color_instruction = Color(*self.panel_color)
            self._panel_shape = RoundedRectangle(
                pos=self.pos,
                size=self.size,
                radius=[(dp(self.corner_radius), dp(self.corner_radius))] * 4,
            )
        self.bind(pos=self._sync_panel, size=self._sync_panel,
                  panel_color=self._sync_panel, corner_radius=self._sync_panel)
        self._sync_panel()

    def _sync_panel(self, *_):
        if not hasattr(self, "_panel_shape"):
            return
        self._panel_color_instruction.rgba = self.panel_color
        self._panel_shape.pos = self.pos
        self._panel_shape.size = self.size
        radius = dp(self.corner_radius)
        self._panel_shape.radius = [(radius, radius)] * 4


class RoundedButton(Button):
    """可复用的圆角按钮；触摸时轻微改变颜色反馈。"""
    fill_color = ListProperty(CARD_ALT)
    press_color = ListProperty(SURFACE_DOWN)
    corner_radius = NumericProperty(16)

    def __init__(self, **kwargs):
        kwargs.setdefault("background_normal", "")
        kwargs.setdefault("background_down", "")
        kwargs.setdefault("background_color", (0, 0, 0, 0))
        kwargs.setdefault("font_name", FONT_NAME)
        kwargs.setdefault("color", TEXT)
        super().__init__(**kwargs)
        with self.canvas.before:
            self._button_color_instruction = Color(*self.fill_color)
            self._button_shape = RoundedRectangle(
                pos=self.pos,
                size=self.size,
                radius=[(dp(self.corner_radius), dp(self.corner_radius))] * 4,
            )
        self.bind(pos=self._sync_button, size=self._sync_button, state=self._sync_button,
                  fill_color=self._sync_button, press_color=self._sync_button,
                  corner_radius=self._sync_button)
        self._sync_button()

    def _sync_button(self, *_):
        if not hasattr(self, "_button_shape"):
            return
        self._button_color_instruction.rgba = self.press_color if self.state == "down" else self.fill_color
        self._button_shape.pos = self.pos
        self._button_shape.size = self.size
        radius = dp(self.corner_radius)
        self._button_shape.radius = [(radius, radius)] * 4


class PhotoPage(RoundedPanel):
    """单张照片页；仅当前页及相邻页加载图片，避免大量照片同时占用内存。"""

    def __init__(self, row, path, **kwargs):
        kwargs.setdefault("panel_color", CARD_DARK)
        super().__init__(orientation="vertical", spacing=dp(8), padding=dp(10), **kwargs)
        self.photo_row = row
        self.photo_path = path
        self.image_widget = Image(
            source="",
            allow_stretch=True,
            keep_ratio=True,
            size_hint_y=1,
        )
        self.caption = Label(
            text=f"{row['photo_date']}   {row['created_at'][11:19]}",
            color=TEXT,
            font_name=FONT_NAME,
            font_size=dp(13),
            size_hint_y=None,
            height=dp(28),
        )
        self.add_widget(self.image_widget)
        self.add_widget(self.caption)

    def load(self):
        if self.photo_path.exists():
            self.image_widget.source = str(self.photo_path)
            self.image_widget.reload()

    def unload(self):
        self.image_widget.source = ""
        self.image_widget.texture = None


class CalendarCell(RoundedButton):
    """圆角日历单元格。"""
    def __init__(self, **kwargs):
        kwargs.setdefault("corner_radius", 14)
        kwargs.setdefault("font_size", dp(12))
        super().__init__(**kwargs)
        self.halign = "center"
        self.valign = "middle"
        self.markup = False


class WeightApp(App):
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

    def _float_setting(self, key):
        v = self.storage.get_setting(key)
        try:
            return float(v) if v else None
        except Exception:
            return None

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

    def refresh(self, *_):
        start = datetime.combine(self.end_date - timedelta(days=self.window_days - 1), datetime.min.time())
        end = datetime.combine(self.end_date, datetime.max.time())
        rows = self.storage.list_records(start, end)
        self.rows = rows
        self.range_label.text = f"{start:%Y-%m-%d} 至 {end:%Y-%m-%d}"
        if rows:
            weights = [float(r["weight"]) for r in rows]
            daily = {}
            for r in rows:
                day = r["recorded_at"][:10]
                daily.setdefault(day, []).append(float(r["weight"]))
            daily_mean = [(d, sum(v) / len(v)) for d, v in sorted(daily.items())]
            self.stats["avg"].text = f"{sum(weights)/len(weights):.1f}斤"
            self.stats["max"].text = f"{max(weights):.1f}"
            self.stats["min"].text = f"{min(weights):.1f}"
            delta = daily_mean[-1][1] - daily_mean[0][1] if len(daily_mean) >= 2 else 0
            self.stats["diff"].text = f"{delta:+.1f}"
            last_w = float(rows[-1]["weight"])
            self.stats["bmi"].text = f"{last_w*0.5/(self.height_cm/100)**2:.1f}" if self.height_cm else "--"
            pts = [(i, val, None, None) for i, (_, val) in enumerate(daily_mean)]
            daily_ids = []
            for day, val in daily_mean:
                matching = [r for r in rows if r["recorded_at"][:10] == day]
                daily_ids.append(matching[-1] if matching else rows[-1])
            pts = [
                (i, val if not self.show_bmi or not self.height_cm else val*0.5/(self.height_cm/100)**2, r.get("id"), r)
                for i, ((_, val), r) in enumerate(zip(daily_mean, daily_ids))
            ]
            self.plot.points = pts
            self.plot.target = self.target_weight if (self.target_weight and not self.show_bmi) else 0
        else:
            for k in self.stats:
                self.stats[k].text = "--"
            self.plot.points = []
            self.plot.target = 0
        self.plot.show_labels = self.show_labels
        self.plot.redraw()

    def save_record(self, *_):
        try:
            dt = datetime.strptime(self.date_input.text.strip(), "%Y-%m-%d %H:%M")
            w = float(self.weight_input.text.strip())
            note = self.note_input.text.strip() or None
            self.storage.insert(w, dt, note)
            self.clear_form()
            self.refresh()
            self.update_quick_buttons()
        except Exception as e:
            self.info("保存失败", str(e))

    def clear_form(self, *_):
        self.date_input.text = datetime.now().strftime("%Y-%m-%d %H:%M")
        self.weight_input.text = ""
        self.note_input.text = ""

    def set_note(self, text):
        self.note_input.text = text

    def quick_weight(self, delta):
        rows = self.storage.list_records()
        if not rows:
            return
        last = float(rows[-1]["weight"])
        self.weight_input.text = f"{last + delta:.1f}"

    def update_quick_buttons(self):
        pass



    # ------------------------------------------------------------------
    # 日历 / 健身 / 体型照片
    # ------------------------------------------------------------------
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

    def edit_record(self, row):
        content = BoxLayout(orientation="vertical", padding=dp(10), spacing=dp(6))
        date_i = self._field(text=as_dt(row["recorded_at"]).strftime("%Y-%m-%d %H:%M"))
        weight_i = self._field(text=f"{row['weight']:.1f}", input_filter="float")
        note_i = self._field(text=row.get("note") or "")
        for title, widget in (("日期时间", date_i), ("体重", weight_i), ("备注", note_i)):
            line = BoxLayout(size_hint_y=None, height=dp(42), spacing=dp(5))
            line.add_widget(self.label(title, 12))
            line.add_widget(widget)
            content.add_widget(line)
        btns = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(6))
        popup = Popup(
            title=f"编辑记录 #{row['id']}",
            title_font=FONT_NAME,
            content=content,
            size_hint=(.94, None),
            height=dp(290),
            auto_dismiss=True,
            background="",
            separator_color=(0, 0, 0, 0),
        )
        btns.add_widget(self.button("保存", lambda *_: self.do_update(popup, row['id'], date_i.text, weight_i.text, note_i.text), 42))
        btns.add_widget(self.button("移入回收站", lambda *_: self.do_delete(popup, row['id']), 42))
        content.add_widget(btns)
        popup.open()

    def do_update(self, popup, rid, date_text, weight_text, note_text):
        try:
            dt = datetime.strptime(date_text.strip(), "%Y-%m-%d %H:%M")
            self.storage.update(rid, float(weight_text), note_text.strip() or None, dt)
            popup.dismiss()
            self.refresh()
        except Exception as e:
            self.info("更新失败", str(e))

    def do_delete(self, popup, rid):
        try:
            self.storage.delete(rid)
            popup.dismiss()
            self.refresh()
        except Exception as e:
            self.info("删除失败", str(e))

    def prev_period(self, *_):
        self.end_date -= timedelta(days=self.window_days)
        self.refresh()

    def next_period(self, *_):
        today = datetime.now().date()
        self.end_date = min(today, self.end_date + timedelta(days=self.window_days))
        self.refresh()

    def today(self, *_):
        self.end_date = datetime.now().date()
        self.refresh()

    def change_days(self, _, value):
        self.window_days = int(value)
        self.storage.set_setting("window_days", self.window_days)
        self.refresh()

    def toggle_bmi(self, value):
        self.show_bmi = value
        if value and not self.height_cm:
            self.show_bmi = False
            self.bmi_cb.active = False
            self.info("需要身高", "请先设置身高(cm)。")
        self.refresh()

    def toggle_labels(self, value):
        self.show_labels = value
        self.plot.show_labels = value
        self.plot.redraw()

    def ask_height(self, *_):
        self.input_setting("保存身高(cm)", self.height_cm, lambda v: self.set_height(v))

    def set_height(self, v):
        x = float(v)
        if not (x > 0 and x == x and x != float("inf") and x != float("-inf")):
            raise ValueError("身高必须是大于 0 的有限数字")
        self.height_cm = x
        self.storage.set_setting("height_cm", x)
        self.refresh()

    def ask_target(self, *_):
        self.input_setting("保存目标体重(斤)", self.target_weight, lambda v: self.set_target(v))

    def set_target(self, v):
        if str(v).strip() == "":
            self.target_weight = None
            self.storage.set_setting("target_weight", None)
        else:
            x = float(v)
            if not (x > 0 and x == x and x != float("inf") and x != float("-inf")):
                raise ValueError("目标体重必须是大于 0 的有限数字")
            self.target_weight = x
            self.storage.set_setting("target_weight", x)
        self.refresh()

    def input_setting(self, title, value, callback):
        content = BoxLayout(orientation="vertical", padding=dp(10), spacing=dp(8))
        inp = self._field(text="" if value is None else str(value))
        content.add_widget(inp)
        btn = self.button("保存", lambda *_: self._save_setting_popup(popup, inp.text, callback), 42)
        content.add_widget(btn)
        popup = Popup(title=title, title_font=FONT_NAME, content=content, size_hint=(.85, None), height=dp(170), background="", separator_color=(0, 0, 0, 0))
        popup.open()

    def _save_setting_popup(self, popup, value, callback):
        try:
            callback(value)
            popup.dismiss()
        except Exception as e:
            self.info("设置失败", str(e))

    def switch_theme(self, *_):
        # 当前版本统一使用健身深色主题，避免只切换窗口底色造成卡片与背景不一致。
        self.theme = "深色"
        self.storage.set_setting("theme", self.theme)
        Window.clearcolor = BG
        self.info("健身深色主题", "当前采用炭黑背景、圆角卡片与珊瑚红训练重点色。")

    def root_window_color(self, color):
        Window = __import__("kivy.core.window", fromlist=["Window"]).Window
        Window.clearcolor = color

    def export_csv(self, *_):
        path = Path(self.user_data_dir) / f"weight_export_{datetime.now():%Y%m%d_%H%M%S}.csv"
        try:
            self.storage.export_csv(path, self.rows)
            self.info("导出完成", f"文件已保存到应用数据目录：\n{path.name}\n\n可在系统文件管理器中访问或导出。")
        except Exception as e:
            self.info("导出失败", str(e))

    def import_csv(self, *_):
        self.info("导入方式", "请把 CSV 文件放入应用可访问的共享目录后再导入。当前版本保留了 CSV 数据层，后续可接 Android 系统文件选择器。")

    def open_recycle(self, *_):
        rows = self.storage.recycle()
        root = BoxLayout(orientation="vertical", padding=dp(8), spacing=dp(5))
        scroll = ScrollView()
        box = GridLayout(cols=1, size_hint_y=None, spacing=dp(5))
        box.bind(minimum_height=box.setter("height"))
        for r in rows:
            line = BoxLayout(size_hint_y=None, height=dp(74), spacing=dp(4))
            text = f"#{r['original_id']}  {float(r['weight']):.1f}斤\n{r['recorded_at']}\n删除：{r['deleted_at']}"
            line.add_widget(self.label(text, 11))
            line.add_widget(self.button("恢复", lambda _, x=r['id']: self.restore_recycle(x), 40))
            line.add_widget(self.button("永久删除", lambda _, x=r['id']: self.perm_recycle(x), 40))
            box.add_widget(line)
        scroll.add_widget(box)
        root.add_widget(scroll)
        root.add_widget(self.button("关闭", lambda *_: popup.dismiss(), 42))
        popup = Popup(title="回收站", title_font=FONT_NAME, content=root, size_hint=(.95, .8), background="", separator_color=(0, 0, 0, 0))
        popup.open()

    def restore_recycle(self, rid):
        try:
            self.storage.restore(rid)
            self.refresh()
            self.open_recycle()
        except Exception as e:
            self.info("恢复失败", str(e))

    def perm_recycle(self, rid):
        try:
            self.storage.permanently_delete(rid)
            self.info("已永久删除", "该记录已从回收站永久删除。")
        except Exception as e:
            self.info("删除失败", str(e))

    def info(self, title, message):
        Popup(
            title=title,
            title_font=FONT_NAME,
            title_color=TEXT,
            content=Label(text=message, color=TEXT, font_name=FONT_NAME),
            size_hint=(.88, None),
            height=dp(210),
            background="",
            separator_color=(0, 0, 0, 0),
        ).open()


if __name__ == "__main__":
    WeightApp().run()
