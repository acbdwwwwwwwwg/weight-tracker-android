"""Reusable rounded widgets shared by the main screen and calendar/photo screen."""

from kivy.graphics import Color, Line, Ellipse, RoundedRectangle
from kivy.metrics import dp
from kivy.properties import ListProperty, NumericProperty, BooleanProperty, StringProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.button import Button
from kivy.uix.image import Image, AsyncImage
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.recycleview.views import RecycleDataViewBehavior
from kivy.uix.label import Label

from services.plot_geometry import value_bounds, normalized_x_positions, date_tick_indices, format_date_tick

from ui.theme import (CARD, CARD_ALT, CARD_DARK, DISABLED_SURFACE, GREEN, LINE_COLOR, MUTED, PRIMARY, PRIMARY_DARK,
                      SURFACE_DOWN, TEXT, WHITE, FONT_NAME, CARD_RADIUS, CONTROL_RADIUS, TILE_RADIUS)

class PlotWidget(BoxLayout):
    points = ListProperty([])
    labels = ListProperty([])
    target = NumericProperty(0)
    show_labels = BooleanProperty(False)
    value_unit = StringProperty("斤")
    on_point = None

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.orientation = "vertical"
        self._suspend_redraw = False
        # Keep caption widgets in a full-size overlay: putting them directly in
        # the BoxLayout would consume vertical space and change chart geometry.
        self._label_layer = FloatLayout(size_hint=(1, 1))
        self.add_widget(self._label_layer)
        self.bind(size=self.redraw, pos=self.redraw, points=self.redraw,
                  target=self.redraw, show_labels=self.redraw, value_unit=self.redraw)

    def set_data(self, points, target=0):
        """Update chart inputs and redraw once instead of once per property."""
        self._suspend_redraw = True
        try:
            self.points = points
            self.target = target
        finally:
            self._suspend_redraw = False
        self.redraw()

    def _add_caption(self, text, center_x, y, width, height, *, color=TEXT, font_size=9,
                     align="center", bold=False):
        caption = Label(text=text, color=color, font_name=FONT_NAME,
                        font_size=dp(font_size), bold=bold,
                        size_hint=(None, None), size=(dp(width), dp(height)),
                        halign=align, valign="middle", shorten=True)
        caption.text_size = caption.size
        half_width = caption.width / 2
        center_x = max(self.x + half_width + dp(2),
                       min(float(center_x), self.right - half_width - dp(2)))
        caption.pos = (center_x - half_width, y)
        self._label_layer.add_widget(caption)

    def redraw(self, *_):
        if getattr(self, "_suspend_redraw", False):
            return
        self.canvas.clear()
        if hasattr(self, "_label_layer"):
            self._label_layer.clear_widgets()
        with self.canvas:
            Color(*CARD)
            RoundedRectangle(pos=self.pos, size=self.size,
                             radius=[(dp(CARD_RADIUS), dp(CARD_RADIUS))] * 4)
            # Reserve bottom room for date captions and a modest top margin.
            x0 = self.x + dp(28)
            y0 = self.y + dp(36)
            w = max(dp(50), self.width - dp(44))
            h = max(dp(50), self.height - dp(62))
            Color(*LINE_COLOR)
            for i in range(5):
                yy = y0 + i * h / 4
                Line(points=[x0, yy, x0 + w, yy], width=1)
            if not self.points:
                self._add_caption("暂无体重记录", self.center_x, self.center_y - dp(8),
                                  max(90, self.width - 50), 20, color=MUTED, font_size=11)
                return

            lo, hi = value_bounds(self.points, self.target)
            span = hi - lo if hi > lo else 1.0
            x_positions = normalized_x_positions(self.points)
            coords = []
            plotted = []
            for idx, (xv, yv, rid, raw) in enumerate(self.points):
                xx = x0 + x_positions[idx] * w
                yy = y0 + ((float(yv) - lo) / span) * h
                coords.extend([xx, yy])
                plotted.append((xx, yy, xv, float(yv)))
            # Draw line first, then points on top so markers remain crisp.
            Color(*PRIMARY)
            if len(coords) >= 4:
                Line(points=coords, width=dp(2.2), joint="round", cap="round")
            for xx, yy, _xv, _yv in plotted:
                Color(*PRIMARY)
                Ellipse(pos=(xx - dp(4), yy - dp(4)), size=(dp(8), dp(8)))
            if self.target:
                ty = y0 + ((float(self.target) - lo) / span) * h
                Color(*GREEN)
                Line(points=[x0, ty, x0 + w, ty], width=dp(1.3), dash_offset=2, dash_length=4)

        # Captions are ordinary Kivy widgets, kept outside the data canvas so
        # they remain legible and use the same registered CJK font as the app.
        if not self.points:
            return
        for index in date_tick_indices(self.points, maximum=3):
            xx, _yy, xv, _yv = plotted[index]
            caption = format_date_tick(xv, self.points)
            if caption:
                self._add_caption(caption, xx, self.y + dp(4), 56, 18,
                                  color=MUTED, font_size=9)
        unit_text = "BMI" if self.value_unit.upper() == "BMI" else str(self.value_unit or "斤")
        self._add_caption(unit_text, self.x + dp(18), self.top - dp(23), 34, 16,
                          color=MUTED, font_size=9)
        if self.show_labels:
            # Labels are useful only while they remain distinguishable. Sparse
            # histories show every value; dense histories use evenly spaced
            # representatives to avoid overlapping text on small phones.
            max_value_labels = max(2, int(w / dp(50)))
            for index in date_tick_indices(self.points, maximum=max_value_labels):
                xx, yy, _xv, yv = plotted[index]
                label_y = min(yy + dp(3), self.top - dp(24))
                self._add_caption(f"{yv:.1f}", xx, label_y, 46, 16,
                                  color=TEXT, font_size=9, bold=True)

    def on_touch_down(self, touch):
        if not self.collide_point(*touch.pos) or not self.points:
            return super().on_touch_down(touch)
        x0 = self.x + dp(28)
        w = max(dp(50), self.width - dp(44))
        lo, hi = value_bounds(self.points, self.target)
        span = hi - lo if hi > lo else 1.0
        y0 = self.y + dp(36)
        h = max(dp(50), self.height - dp(62))
        x_positions = normalized_x_positions(self.points)
        best = None
        bestd = float("inf")
        for idx, (xv, yv, rid, raw) in enumerate(self.points):
            xx = x0 + x_positions[idx] * w
            yy = y0 + ((float(yv) - lo) / span) * h
            d = (touch.x - xx) ** 2 + (touch.y - yy) ** 2
            if d < bestd:
                bestd = d
                best = raw
        if best is not None and bestd <= dp(26) ** 2 and self.on_point:
            self.on_point(best)
            return True
        return super().on_touch_down(touch)


class RoundedPanel(BoxLayout):
    """轻量圆角卡片，避免额外图片资源并适配不同屏幕尺寸。"""
    panel_color = ListProperty(CARD)
    corner_radius = NumericProperty(CARD_RADIUS)

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
    corner_radius = NumericProperty(CONTROL_RADIUS)

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
                  disabled=self._sync_button, fill_color=self._sync_button,
                  press_color=self._sync_button, corner_radius=self._sync_button)
        self._sync_button()

    def _sync_button(self, *_):
        if not hasattr(self, "_button_shape"):
            return
        if self.disabled:
            self._button_color_instruction.rgba = DISABLED_SURFACE
        else:
            self._button_color_instruction.rgba = self.press_color if self.state == "down" else self.fill_color
        self._button_shape.pos = self.pos
        self._button_shape.size = self.size
        radius = dp(self.corner_radius)
        self._button_shape.radius = [(radius, radius)] * 4


class CalendarCell(RoundedButton):
    """圆角日历单元格。"""
    def __init__(self, **kwargs):
        kwargs.setdefault("corner_radius", 12)
        kwargs.setdefault("font_size", dp(12))
        super().__init__(**kwargs)
        self.halign = "center"
        self.valign = "middle"
        self.markup = False


class PhotoThumbnailTile(RecycleDataViewBehavior, ButtonBehavior, BoxLayout):
    """Reusable horizontal timeline tile for RecycleView.

    Every visible tile is recycled as the list scrolls. Selection state is
    computed from the browser's current index instead of duplicating a large
    list update for each photo swipe.
    """
    selected = BooleanProperty(False)
    photo_index = NumericProperty(-1)

    def __init__(self, **kwargs):
        super().__init__(orientation="vertical", spacing=dp(2),
                         padding=(dp(3), dp(3), dp(3), dp(2)), **kwargs)
        self.on_select_callback = None
        self.selection_provider = None
        self.photo_id = None
        self.thumbnail_source_value = ""
        self.thumbnail_error_callback = None
        self.thumbnail_area = FloatLayout(size_hint=(1, 1))
        self.thumbnail = AsyncImage(source="", allow_stretch=True, keep_ratio=True,
                                    size_hint=(1, 1), pos_hint={"x": 0, "y": 0}, nocache=True)
        self.thumbnail_placeholder = Label(
            text="无预览", color=MUTED, font_name=FONT_NAME, font_size=dp(9),
            size_hint=(1, 1), halign="center", valign="middle",
        )
        self.thumbnail_placeholder.bind(size=lambda widget, size: setattr(widget, "text_size", size))
        self.thumbnail_area.add_widget(self.thumbnail)
        self.thumbnail_area.add_widget(self.thumbnail_placeholder)
        self.thumbnail.bind(texture=self._on_thumbnail_texture)
        try:
            self.thumbnail.bind(on_error=self._on_thumbnail_error)
        except Exception:
            # Older Kivy builds may not expose AsyncImage.on_error; placeholder
            # visibility is still managed from the texture property.
            pass
        self.caption_label = Label(text="", color=TEXT, font_name=FONT_NAME,
                                   font_size=dp(10), size_hint_y=None, height=dp(17),
                                   halign="center", valign="middle", shorten=True)
        self.add_widget(self.thumbnail_area)
        self.add_widget(self.caption_label)
        with self.canvas.before:
            self._tile_color = Color(*CARD_ALT)
            self._tile_background = RoundedRectangle(
                pos=self.pos, size=self.size,
                radius=[(dp(TILE_RADIUS), dp(TILE_RADIUS))] * 4,
            )
        self.bind(pos=self._sync_tile, size=self._sync_tile, selected=self._sync_tile)
        self._sync_tile()

    def _on_thumbnail_texture(self, _widget, texture):
        if texture is not None:
            self.thumbnail_placeholder.opacity = 0
            self.thumbnail_placeholder.disabled = True
        else:
            self.thumbnail_placeholder.opacity = 1
            self.thumbnail_placeholder.disabled = False

    def _on_thumbnail_error(self, _widget, error=None):
        self.thumbnail_placeholder.text = "预览失败"
        self.thumbnail_placeholder.opacity = 1
        self.thumbnail_placeholder.disabled = False
        callback = self.thumbnail_error_callback
        if callback is not None and self.photo_id is not None and self.thumbnail_source_value:
            try:
                callback(int(self.photo_id), self.thumbnail_source_value, self.thumbnail_placeholder)
            except Exception:
                # A tile error must never break RecycleView layout/scrolling.
                pass

    def _sync_tile(self, *_args):
        self._tile_color.rgba = PRIMARY_DARK if self.selected else CARD_ALT
        self._tile_background.pos = self.pos
        self._tile_background.size = self.size
        self._tile_background.radius = [(dp(9), dp(9))] * 4

    def refresh_view_attrs(self, rv, index, data):
        result = super().refresh_view_attrs(rv, index, data)
        self.photo_index = int(data.get("photo_index", index))
        self.photo_id = data.get("photo_id")
        source = data.get("source") or ""
        self.thumbnail_source_value = str(source)
        self.thumbnail_error_callback = data.get("on_thumbnail_error")
        if source:
            placeholder_text = "载入中"
        elif data.get("preview_failed", False):
            placeholder_text = "预览失败"
        elif data.get("has_original", True):
            placeholder_text = "生成预览中"
        else:
            placeholder_text = "原图缺失"
        self.thumbnail_placeholder.text = placeholder_text
        self.thumbnail_placeholder.opacity = 1
        self.thumbnail_placeholder.disabled = False
        # Recycled tiles must not flash the previous item's bitmap while the new
        # URI is decoding. Clear the old texture only when the source changes.
        if str(self.thumbnail.source or "") != str(source):
            self.thumbnail.texture = None
        self.thumbnail.source = source
        if not source:
            self.thumbnail.texture = None
        self.caption_label.text = data.get("caption") or ""
        self.on_select_callback = data.get("on_select")
        self.selection_provider = data.get("selection_provider")
        self.selected = bool(self.selection_provider(self.photo_index)) if self.selection_provider else False
        return result

    def on_release(self):
        callback = self.on_select_callback
        if callback is not None and self.photo_index >= 0:
            callback(self.photo_index)


class PhotoSwipeSurface(FloatLayout):
    """Capture quick horizontal swipes without imposing a long-press delay.

    Vertical movement is left to the containing ScrollView. Touches are grabbed
    only so that a horizontal gesture can finish even if the finger crosses an
    edge of the photo viewport.
    """
    def __init__(self, on_swipe=None, min_distance_dp=24, **kwargs):
        super().__init__(**kwargs)
        self.on_swipe = on_swipe
        self.min_distance_dp = float(min_distance_dp)
        self._touch_key = f"photo_swipe_{id(self)}"

    def on_touch_down(self, touch):
        if self.collide_point(*touch.pos):
            touch.ud[self._touch_key] = {
                "x": touch.x, "y": touch.y, "claimed": False,
            }
            touch.grab(self)
        return super().on_touch_down(touch)

    def on_touch_move(self, touch):
        state = touch.ud.get(self._touch_key)
        if state is not None and touch.grab_current is self:
            dx = touch.x - state["x"]
            dy = touch.y - state["y"]
            if abs(dx) >= dp(self.min_distance_dp) and abs(dx) > abs(dy) * 1.15:
                state["claimed"] = True
                return True
            if abs(dy) >= dp(self.min_distance_dp) and abs(dy) > abs(dx) * 1.15:
                # Do not consume vertical movement; allow the parent ScrollView
                # to move naturally while this surface merely observes it.
                touch.ungrab(self)
                touch.ud.pop(self._touch_key, None)
                return super().on_touch_move(touch)
        return super().on_touch_move(touch)

    def on_touch_up(self, touch):
        state = touch.ud.pop(self._touch_key, None)
        if state is None or touch.grab_current is not self:
            return super().on_touch_up(touch)
        dx = touch.x - state["x"]
        dy = touch.y - state["y"]
        touch.ungrab(self)
        if state["claimed"] and abs(dx) >= dp(self.min_distance_dp) and abs(dx) > abs(dy) * 1.15:
            if self.on_swipe is not None:
                self.on_swipe("previous" if dx > 0 else "next")
            return True
        return super().on_touch_up(touch)
