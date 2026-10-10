"""Weight history, chart refresh and record editing behavior."""

from datetime import datetime, timedelta

from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.popup import Popup

from ui.theme import FONT_NAME, TEXT
from ui.utils import as_dt

class RecordsFeatureMixin:
    """Weight record persistence and chart state transitions."""

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
            last_record_by_day = {}
            for record in rows:
                last_record_by_day[record["recorded_at"][:10]] = record
            self.stats["avg"].text = f"{sum(weights)/len(weights):.1f}斤"
            self.stats["max"].text = f"{max(weights):.1f}"
            self.stats["min"].text = f"{min(weights):.1f}"
            delta = daily_mean[-1][1] - daily_mean[0][1] if len(daily_mean) >= 2 else 0
            self.stats["diff"].text = f"{delta:+.1f}"
            last_w = float(rows[-1]["weight"])
            self.stats["bmi"].text = f"{last_w*0.5/(self.height_cm/100)**2:.1f}" if self.height_cm else "--"
            pts = [(i, val, None, None) for i, (_, val) in enumerate(daily_mean)]
            daily_ids = [last_record_by_day.get(day, rows[-1]) for day, _value in daily_mean]
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
        self.refresh_home_summary()

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
            weight = float(weight_text)
            note = note_text.strip() or None
            self.storage._validate_weight(weight)
        except Exception as exc:
            self.info("更新失败", str(exc))
            return
        popup.dismiss()
        self.run_background_task(
            "正在保存修改并保护旧数据",
            lambda: self.storage.update(rid, weight, note, dt),
            on_success=lambda _result: self.refresh(),
            on_error=lambda exc: self.info("更新失败", str(exc)),
        )

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
