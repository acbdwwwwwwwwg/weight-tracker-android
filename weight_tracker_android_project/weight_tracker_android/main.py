from __future__ import annotations

import csv
from datetime import datetime, timedelta
from pathlib import Path

from kivy.app import App
from kivy.clock import Clock
from kivy.graphics import Color, Line, Ellipse, Rectangle
from kivy.metrics import dp
from kivy.properties import ListProperty, NumericProperty, StringProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.checkbox import CheckBox
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView
from kivy.uix.spinner import Spinner
from kivy.uix.textinput import TextInput
from kivy.utils import get_color_from_hex

from storage import Storage


BG = get_color_from_hex("#F5F7FA")
PRIMARY = get_color_from_hex("#2F80ED")
TEXT = get_color_from_hex("#1F2937")
MUTED = get_color_from_hex("#6B7280")
GREEN = get_color_from_hex("#27AE60")
RED = get_color_from_hex("#EB5757")
WHITE = get_color_from_hex("#FFFFFF")


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
            Color(*WHITE)
            Rectangle(pos=self.pos, size=self.size)
            x0 = self.x + dp(44)
            y0 = self.y + dp(36)
            w = max(dp(50), self.width - dp(60))
            h = max(dp(50), self.height - dp(62))
            Color(*get_color_from_hex("#D9DEE7"))
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
                Ellipse(pos=(xx - dp(5), yy - dp(5)), size=(dp(10), dp(10)))
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
        x0 = self.x + dp(44)
        w = max(dp(50), self.width - dp(60))
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


class WeightApp(App):
    def build(self):
        self.title = "体重追踪助手"
        self.storage = Storage(self.user_data_dir)
        self.end_date = datetime.now().date()
        self.window_days = int(self.storage.get_setting("window_days") or 30)
        self.height_cm = self._float_setting("height_cm")
        self.target_weight = self._float_setting("target_weight")
        self.theme = self.storage.get_setting("theme") or "浅色"
        self.show_bmi = False
        self.show_labels = False

        root = BoxLayout(orientation="vertical", padding=dp(10), spacing=dp(8))
        root.add_widget(self.build_input())
        root.add_widget(self.build_stats())
        root.add_widget(self.build_nav())
        root.add_widget(self.build_settings())
        self.plot = PlotWidget(size_hint_y=0.48, on_point=self.edit_record)
        root.add_widget(self.plot)
        self.refresh()
        return root

    def _float_setting(self, key):
        v = self.storage.get_setting(key)
        try:
            return float(v) if v else None
        except Exception:
            return None

    def label(self, text, size=14, color=TEXT, bold=False):
        return Label(text=text, color=color, font_size=dp(size), bold=bold)

    def button(self, text, callback, height=42):
        b = Button(text=text, size_hint_y=None, height=dp(height), background_normal="", background_color=PRIMARY)
        b.bind(on_release=callback)
        return b

    def build_input(self):
        box = BoxLayout(orientation="vertical", spacing=dp(6), size_hint_y=None, height=dp(142))
        row = BoxLayout(spacing=dp(5), size_hint_y=None, height=dp(44))
        self.date_input = TextInput(text=datetime.now().strftime("%Y-%m-%d %H:%M"), multiline=False, hint_text="日期时间")
        self.weight_input = TextInput(multiline=False, input_filter="float", hint_text="体重(斤)")
        self.note_input = TextInput(multiline=False, hint_text="备注")
        row.add_widget(self.date_input)
        row.add_widget(self.weight_input)
        row.add_widget(self.note_input)
        row.add_widget(self.button("保存", self.save_record))
        box.add_widget(row)
        quick = BoxLayout(spacing=dp(4), size_hint_y=None, height=dp(42))
        quick.add_widget(self.label("快捷：", 12))
        for txt, delta in [("-1斤", -1), ("-0.5斤", -0.5), ("上次", 0), ("+0.5斤", 0.5), ("+1斤", 1)]:
            b = Button(text=txt, size_hint_x=None, width=dp(74), background_normal="", background_color=get_color_from_hex("#E8EEF8"), color=TEXT)
            b.bind(on_release=lambda _, d=delta: self.quick_weight(d))
            quick.add_widget(b)
        for txt in ("晨起", "早餐后", "运动后", "睡前"):
            b = Button(text=txt, size_hint_x=None, width=dp(72), background_normal="", background_color=get_color_from_hex("#EEF6F0"), color=TEXT)
            b.bind(on_release=lambda _, t=txt: self.set_note(t))
            quick.add_widget(b)
        box.add_widget(quick)
        return box

    def build_stats(self):
        self.stats = {}
        grid = GridLayout(cols=5, spacing=dp(5), size_hint_y=None, height=dp(62))
        for key, title in [("avg", "平均"), ("max", "最高"), ("min", "最低"), ("diff", "变化"), ("bmi", "BMI")]:
            cell = BoxLayout(orientation="vertical")
            cell.add_widget(self.label(title, 11, MUTED))
            val = self.label("--", 15, TEXT, True)
            self.stats[key] = val
            cell.add_widget(val)
            grid.add_widget(cell)
        return grid

    def build_nav(self):
        row = BoxLayout(spacing=dp(6), size_hint_y=None, height=dp(42))
        row.add_widget(self.button("◀ 前一周期", self.prev_period, 40))
        self.range_label = self.label("", 13, TEXT, True)
        row.add_widget(self.range_label)
        row.add_widget(self.button("后一周期 ▶", self.next_period, 40))
        row.add_widget(self.button("今天", self.today, 40))
        return row

    def build_settings(self):
        scroll = ScrollView(size_hint_y=None, height=dp(86), do_scroll_x=True, do_scroll_y=False)
        row = BoxLayout(size_hint_x=None, width=dp(1000), spacing=dp(6))
        row.add_widget(self.label("天数", 12))
        self.days_spinner = Spinner(text=str(self.window_days), values=[str(i) for i in (7, 14, 30, 60, 90, 180, 365)], size_hint_x=None, width=dp(70))
        self.days_spinner.bind(text=self.change_days)
        row.add_widget(self.days_spinner)
        self.bmi_cb = CheckBox(active=False, size_hint_x=None, width=dp(28))
        self.bmi_cb.bind(active=lambda _, value: self.toggle_bmi(value))
        row.add_widget(self.bmi_cb)
        row.add_widget(self.label("BMI", 12))
        self.labels_cb = CheckBox(active=False, size_hint_x=None, width=dp(28))
        self.labels_cb.bind(active=lambda _, value: self.toggle_labels(value))
        row.add_widget(self.labels_cb)
        row.add_widget(self.label("数值", 12))
        row.add_widget(self.button("身高", self.ask_height, 40))
        row.add_widget(self.button("目标", self.ask_target, 40))
        row.add_widget(self.button("导出CSV", self.export_csv, 40))
        row.add_widget(self.button("导入CSV", self.import_csv, 40))
        row.add_widget(self.button("回收站", self.open_recycle, 40))
        row.add_widget(self.button("设置主题", self.switch_theme, 40))
        row.add_widget(self.button("清空", self.clear_form, 40))
        scroll.add_widget(row)
        return scroll

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
            pts = [(i, val if not self.show_bmi or not self.height_cm else val*0.5/(self.height_cm/100)**2, r.get("id"), r) for i, ((_, val), r) in enumerate(zip(daily_mean, daily_ids))]
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

    def edit_record(self, row):
        content = BoxLayout(orientation="vertical", padding=dp(10), spacing=dp(6))
        date_i = TextInput(text=as_dt(row["recorded_at"]).strftime("%Y-%m-%d %H:%M"), multiline=False)
        weight_i = TextInput(text=f"{row['weight']:.1f}", input_filter="float", multiline=False)
        note_i = TextInput(text=row.get("note") or "", multiline=False)
        for title, widget in (("日期时间", date_i), ("体重", weight_i), ("备注", note_i)):
            line = BoxLayout(size_hint_y=None, height=dp(42), spacing=dp(5))
            line.add_widget(self.label(title, 12))
            line.add_widget(widget)
            content.add_widget(line)
        btns = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(6))
        popup = Popup(title=f"编辑记录 #{row['id']}", content=content, size_hint=(.94, None), height=dp(290), auto_dismiss=True)
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
        inp = TextInput(text="" if value is None else str(value), multiline=False)
        content.add_widget(inp)
        btn = self.button("保存", lambda *_: self._save_setting_popup(popup, inp.text, callback), 42)
        content.add_widget(btn)
        popup = Popup(title=title, content=content, size_hint=(.85, None), height=dp(170))
        popup.open()

    def _save_setting_popup(self, popup, value, callback):
        try:
            callback(value)
            popup.dismiss()
        except Exception as e:
            self.info("设置失败", str(e))

    def switch_theme(self, *_):
        self.theme = "深色" if self.theme == "浅色" else "浅色"
        self.storage.set_setting("theme", self.theme)
        bg = get_color_from_hex("#111827") if self.theme == "深色" else BG
        self.root_window_color(bg)

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
        popup = Popup(title="回收站", content=root, size_hint=(.95, .8))
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
        Popup(title=title, content=Label(text=message, color=TEXT), size_hint=(.88, None), height=dp(210)).open()


if __name__ == "__main__":
    WeightApp().run()
