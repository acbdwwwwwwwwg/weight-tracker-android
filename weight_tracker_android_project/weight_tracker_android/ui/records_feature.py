"""Weight history, chart refresh and record editing behavior."""

from datetime import datetime, timedelta
from threading import Thread
from time import perf_counter
import logging

from kivy.metrics import dp
from kivy.clock import Clock
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.popup import Popup

from ui.theme import FONT_NAME, TEXT
from ui.utils import as_dt
from services.performance import mark

class RecordsFeatureMixin:
    """Weight record persistence and chart state transitions."""

    def refresh(self, *_):
        """Fetch and aggregate trend data off the UI thread, applying only the newest result."""
        storage = getattr(self, "storage", None)
        if storage is None or getattr(self, "plot", None) is None:
            return
        self._records_refresh_generation = getattr(self, "_records_refresh_generation", 0) + 1
        generation = self._records_refresh_generation
        end_date = self.end_date
        window_days = int(self.window_days)
        height_cm = self.height_cm
        target_weight = self.target_weight
        show_bmi = bool(self.show_bmi)
        show_labels = bool(self.show_labels)
        start = datetime.combine(end_date - timedelta(days=window_days - 1), datetime.min.time())
        end = datetime.combine(end_date, datetime.max.time())
        today = datetime.now().date()
        today_start = datetime.combine(today, datetime.min.time())
        today_end = datetime.combine(today, datetime.max.time())

        def worker():
            query_started = perf_counter()
            try:
                rows = storage.list_records(start, end)
                if rows:
                    weights = [float(r["weight"]) for r in rows]
                    daily = {}
                    last_record_by_day = {}
                    for record in rows:
                        day = record["recorded_at"][:10]
                        daily.setdefault(day, []).append(float(record["weight"]))
                        last_record_by_day[day] = record
                    daily_mean = [(day, sum(values) / len(values)) for day, values in sorted(daily.items())]
                    delta = daily_mean[-1][1] - daily_mean[0][1] if len(daily_mean) >= 2 else 0
                    latest_weight = float(rows[-1]["weight"])
                    bmi = f"{latest_weight * 0.5 / (height_cm / 100) ** 2:.1f}" if height_cm else "--"
                    stats = {
                        "avg": f"{sum(weights) / len(weights):.1f}斤",
                        "max": f"{max(weights):.1f}",
                        "min": f"{min(weights):.1f}",
                        "diff": f"{delta:+.1f}",
                        "bmi": bmi,
                    }
                    points = []
                    for index, (day, average) in enumerate(daily_mean):
                        record = last_record_by_day[day]
                        value = average * 0.5 / (height_cm / 100) ** 2 if show_bmi and height_cm else average
                        points.append((index, value, record.get("id"), record))
                    target = target_weight if target_weight and not show_bmi else 0
                else:
                    stats = {key: "--" for key in ("avg", "max", "min", "diff", "bmi")}
                    points = []
                    target = 0
                mark("trend_query_and_aggregate_complete", query_started, rows=len(rows), points=len(points))
                Clock.schedule_once(
                    lambda _dt: self._apply_refresh_result(
                        generation, rows, stats, points, target, start, end, show_labels
                    ), 0
                )
            except Exception as exc:
                logging.exception("Trend refresh failed")
                Clock.schedule_once(lambda _dt, err=exc: self._report_refresh_error(err), 0)

        Thread(target=worker, name="weight-trend-query", daemon=True).start()

    def _apply_refresh_result(self, generation, rows, stats, points, target, start, end, show_labels):
        if generation != getattr(self, "_records_refresh_generation", generation):
            return
        self.rows = rows
        self.range_label.text = f"{start:%Y-%m-%d} 至 {end:%Y-%m-%d}"
        for key, value in stats.items():
            if key in getattr(self, "stats", {}):
                self.stats[key].text = value
        self.plot.show_labels = bool(show_labels)
        if hasattr(self.plot, "set_data"):
            self.plot.set_data(points, target)
        else:
            self.plot.points = points
            self.plot.target = target
        self.refresh_home_summary()

    def _report_refresh_error(self, error):
        logging.error("无法刷新体重趋势：%s", error)

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
