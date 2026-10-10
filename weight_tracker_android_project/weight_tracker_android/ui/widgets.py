"""Reusable rounded widgets shared by the main screen and calendar/photo screen."""

from pathlib import Path

from kivy.graphics import Color, Line, Ellipse, RoundedRectangle
from kivy.metrics import dp
from kivy.properties import ListProperty, NumericProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.image import Image
from kivy.uix.label import Label

from ui.theme import (CARD, CARD_ALT, CARD_DARK, GREEN, LINE_COLOR, MUTED, PRIMARY,
                      SURFACE_DOWN, TEXT, WHITE, FONT_NAME)

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
    """One photo preview page. The timeline passes a downsampled thumbnail path."""

    def __init__(self, row, path=None, original_path=None, **kwargs):
        kwargs.setdefault("panel_color", CARD_DARK)
        super().__init__(orientation="vertical", spacing=dp(8), padding=dp(10), **kwargs)
        self.photo_row = row
        self.photo_path = path
        self.original_path = original_path or path
        self.preview_status = Label(
            text="正在准备预览…", color=MUTED, font_name=FONT_NAME,
            font_size=dp(12), size_hint_y=1,
        )
        self.image_widget = Image(
            source="", allow_stretch=True, keep_ratio=True, size_hint_y=0,
        )
        self.caption = Label(
            text=f"{row['photo_date']}   {str(row['created_at'])[11:19]}",
            color=TEXT, font_name=FONT_NAME, font_size=dp(13),
            size_hint_y=None, height=dp(28),
        )
        self.add_widget(self.preview_status)
        self.add_widget(self.image_widget)
        self.add_widget(self.caption)

    def load(self):
        path = self.photo_path
        if path is not None and Path(path).exists():
            if self.image_widget.source != str(path):
                self.image_widget.source = str(path)
                self.image_widget.reload()
            self.image_widget.size_hint_y = 1
            self.preview_status.size_hint_y = 0
            self.preview_status.opacity = 0
        else:
            self.image_widget.source = ""
            self.image_widget.texture = None
            self.image_widget.size_hint_y = 0
            self.preview_status.size_hint_y = 1
            self.preview_status.opacity = 1

    def unload(self):
        self.image_widget.source = ""
        self.image_widget.texture = None
        self.image_widget.size_hint_y = 0
        self.preview_status.size_hint_y = 1
        self.preview_status.opacity = 1


class CalendarCell(RoundedButton):
    """圆角日历单元格。"""
    def __init__(self, **kwargs):
        kwargs.setdefault("corner_radius", 14)
        kwargs.setdefault("font_size", dp(12))
        super().__init__(**kwargs)
        self.halign = "center"
        self.valign = "middle"
        self.markup = False
