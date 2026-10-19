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
                latest_global = storage.latest_record()
                latest_bmi = "--"
                if latest_global is not None and height_cm:
                    latest_bmi = f"{float(latest_global['weight']) * 0.5 / (height_cm / 100) ** 2:.1f}"
                if rows:
                    weights = [float(r["weight"]) for r in rows]
                    daily = {}
                    for record in rows:
                        day = record["recorded_at"][:10]
                        daily.setdefault(day, []).append(record)
                    if show_bmi and height_cm:
                        conversion = 0.5 / (height_cm / 100) ** 2
                    else:
                        conversion = 0.5 if self.weight_unit_label() == "kg" else 1.0
                    metric_values = [weight * conversion for weight in weights]
                    daily_mean = [
                        (day, sum(float(row["weight"]) for row in day_rows) / len(day_rows) * conversion)
                        for day, day_rows in sorted(daily.items())
                    ]
                    delta = daily_mean[-1][1] - daily_mean[0][1] if len(daily_mean) >= 2 else 0
                    stats = {
                        # Mean/high/low describe individual readings in the selected
                        # range. The plot has one point per day's mean; the change
                        # card is therefore explicitly labelled as daily-mean change.
                        "avg": f"{sum(metric_values) / len(metric_values):.1f}",
                        "max": f"{max(metric_values):.1f}",
                        "min": f"{min(metric_values):.1f}",
                        "diff": f"{delta:+.1f}",
                        # This card is global/latest, not the last row in a browsed range.
                        "bmi": latest_bmi,
                    }
                    points = []
                    for day, average in daily_mean:
                        day_records = list(daily[day])
                        aggregate = {
                            "aggregate_date": day,
                            "aggregate_value": average,
                            "aggregate_count": len(day_records),
                            "records": day_records,
                        }
                        # The point is an aggregate, never an alias for a random
                        # original row. The click handler opens the day's records.
                        points.append((day, average, None, aggregate))
                    target = (target_weight * (0.5 if self.weight_unit_label() == "kg" else 1.0)) if target_weight and not show_bmi else 0
                else:
                    stats = {key: "--" for key in ("avg", "max", "min", "diff")}
                    stats["bmi"] = latest_bmi
                    points = []
                    target = 0
                mark("trend_query_and_aggregate_complete", query_started, rows=len(rows), points=len(points))
                Clock.schedule_once(
                    lambda _dt: self._apply_refresh_result(
                        generation, rows, stats, points, target, start, end, show_labels, show_bmi
                    ), 0
                )
            except Exception as exc:
                logging.exception("Trend refresh failed")
                Clock.schedule_once(lambda _dt, err=exc: self._report_refresh_error(err), 0)

        Thread(target=worker, name="weight-trend-query", daemon=True).start()

    def _apply_refresh_result(self, generation, rows, stats, points, target, start, end, show_labels, show_bmi=False):
        if generation != getattr(self, "_records_refresh_generation", generation):
            return
        self.rows = rows
        self.range_label.text = f"{start:%Y-%m-%d} 至 {end:%Y-%m-%d}"
        for key, value in stats.items():
            if key in getattr(self, "stats", {}):
                self.stats[key].text = value
        self.plot.show_labels = bool(show_labels)
        self.plot.value_unit = "BMI" if show_bmi else self.weight_unit_label()
        if hasattr(self, "trend_title_label"):
            self.trend_title_label.text = "BMI 趋势（每日平均）" if show_bmi else "体重趋势（每日平均）"
        if hasattr(self, "stat_titles"):
            unit = "BMI" if show_bmi else self.weight_unit_label()
            # The first three summarize individual measurements in the selected
            # range; the delta compares first/last daily averages, matching the
            # aggregation represented by the plotted points.
            titles = {
                "avg": f"均值{unit}",
                "max": f"最高{unit}",
                "min": f"最低{unit}",
                "diff": f"日均变{unit}",
                "bmi": "当前BMI",
            }
            for key, title in titles.items():
                if key in self.stat_titles:
                    self.stat_titles[key].text = title
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
            w = self.weight_to_storage(float(self.weight_input.text.strip()))
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
        row = self.storage.latest_record()
        if not row:
            return
        last = self.display_weight(float(row["weight"]))
        self.weight_input.text = f"{last + delta:.1f}"

    def update_quick_buttons(self):
        pass

    def edit_record(self, row):
        if isinstance(row, dict) and "aggregate_date" in row and "records" in row:
            self.open_day_record_picker(row)
            return
        content = BoxLayout(orientation="vertical", padding=dp(10), spacing=dp(6))
        date_i = self._field(text=as_dt(row["recorded_at"]).strftime("%Y-%m-%d %H:%M"))
        weight_i = self._field(text=f"{self.display_weight(float(row['weight'])):.1f}", input_filter="float")
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

    def open_day_record_picker(self, aggregate):
        """Let the user choose an actual measurement behind a daily chart point."""
        records = sorted(aggregate.get("records", []),
                         key=lambda row: (str(row.get("recorded_at", "")), int(row.get("id", 0))))
        day = str(aggregate.get("aggregate_date", ""))
        value = float(aggregate.get("aggregate_value", 0.0))
        content = BoxLayout(orientation="vertical", padding=dp(10), spacing=dp(6))
        content.add_widget(self.label(
            f"{day} · 每日平均 {value:.1f} {('BMI' if self.show_bmi else self.weight_unit_label())}", 12, TEXT, True
        ))
        content.add_widget(self.label("请选择要编辑的原始记录。图上的点代表当天平均值，不是某一条记录。", 10, MUTED))
        scroll = __import__("kivy.uix.scrollview", fromlist=["ScrollView"]).ScrollView(
            do_scroll_x=False, do_scroll_y=True, bar_width=dp(3)
        )
        items = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(5))
        items.bind(minimum_height=items.setter("height"))
        scroll.add_widget(items)
        content.add_widget(scroll)
        actions = BoxLayout(size_hint_y=None, height=dp(42), spacing=dp(7))
        popup = Popup(title="选择当天记录", title_font=FONT_NAME, content=content,
                      size_hint=(.94, .78), background="", separator_color=(0, 0, 0, 0))
        actions.add_widget(self.button("取消", lambda *_: popup.dismiss(), 42, tone="secondary"))
        content.add_widget(actions)
        for record in records:
            stamp = str(record.get("recorded_at", ""))
            clock_text = stamp[11:16] if len(stamp) >= 16 else stamp
            note = str(record.get("note") or "").strip()
            label = f"{clock_text}  ·  {self.display_weight(float(record['weight'])):.1f} {self.weight_unit_label()}"
            if note:
                label += f"  ·  {note}"

            def choose(_button, selected=record):
                popup.dismiss()
                Clock.schedule_once(lambda _dt, item=selected: self.edit_record(item), 0)

            items.add_widget(self.button(label, choose, 44, tone="secondary"))
        popup.open()

    def do_update(self, popup, rid, date_text, weight_text, note_text):
        try:
            dt = datetime.strptime(date_text.strip(), "%Y-%m-%d %H:%M")
            weight = self.weight_to_storage(float(weight_text))
            note = note_text.strip() or None
            self.storage._validate_weight(weight)
            self.storage.validate_recorded_at(dt)
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
        if getattr(self, "_syncing_bmi_checkbox", False):
            return
        requested = bool(value)
        if requested and not self.height_cm:
            self.show_bmi = False
            self.storage.set_setting("show_bmi", False)
            self._syncing_bmi_checkbox = True
            try:
                self.bmi_cb.active = False
            finally:
                self._syncing_bmi_checkbox = False
            self.info("需要身高", "请先设置身高(cm)，设置后即可显示 BMI。")
            self.refresh()
            return
        self.show_bmi = requested
        self.storage.set_setting("show_bmi", self.show_bmi)
        self.refresh()

    def toggle_labels(self, value):
        if getattr(self, "_syncing_labels_checkbox", False):
            return
        self.show_labels = bool(value)
        self.storage.set_setting("show_labels", self.show_labels)
        self.plot.show_labels = self.show_labels
        self.plot.redraw()
