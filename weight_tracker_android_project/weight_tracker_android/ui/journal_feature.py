"""Daily food, structured training, measurements, local reminders and reports."""
from datetime import datetime, date
from threading import Thread
import logging
import re

from kivy.clock import Clock
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView
from kivy.uix.spinner import Spinner, SpinnerOption
from kivy.core.clipboard import Clipboard

from services.local_notifications import post_local_notification, request_notification_permission
from services.reporting import format_health_report
from services.android_bridge import ANDROID_AVAILABLE, IS_ANDROID, android_activity, autoclass, get_current_activity
from ui.theme import CARD, MUTED, TEXT, FONT_NAME
from ui.widgets import RoundedPanel


class JournalFeatureMixin:
    """CRUD and rendering for nutrition/training/body measurements."""

    def _journal_selected_date(self):
        raw = str(getattr(self, "journal_date_input", None).text if getattr(self, "journal_date_input", None) else date.today().isoformat()).strip()
        try:
            selected = datetime.strptime(raw, "%Y-%m-%d").date()
        except ValueError as exc:
            raise ValueError("日期请使用 YYYY-MM-DD，例如 2026-10-19") from exc
        return selected

    def journal_today(self, *_):
        if getattr(self, "journal_date_input", None) is not None:
            self.journal_date_input.text = date.today().isoformat()
        self.refresh_journal()

    def _clear_list(self, container):
        if container is not None:
            container.clear_widgets()

    def refresh_journal(self, *_):
        """Read journal data off the UI thread and apply only the latest request."""
        if not getattr(self, "storage", None) or not getattr(self, "food_list_box", None):
            return
        try:
            selected = self._journal_selected_date()
        except ValueError as exc:
            self.info("日期格式不正确", str(exc))
            return

        self._journal_refresh_generation = getattr(self, "_journal_refresh_generation", 0) + 1
        generation = self._journal_refresh_generation
        selected_text = selected.isoformat()
        storage = self.storage
        target = self.target_weight
        unit = self.weight_unit_label()
        if getattr(self, "journal_calories_label", None) is not None:
            self.journal_calories_label.text = f"{selected_text} · 正在加载饮食数据…"

        def worker():
            return {
                "foods": storage.list_food_logs(selected_text, selected_text, limit=1000),
                "training": storage.list_strength_logs(selected_text, selected_text, limit=1000),
                "measurements": storage.list_body_measurements(limit=1000, start_date=selected_text, end_date=selected_text),
                "latest_measurement": (storage.list_body_measurements(limit=1) or [None])[0],
                "average": storage.get_seven_day_weight_average(selected),
                "weight_progress": storage.get_weight_progress_summary(),
            }

        def run():
            try:
                data = worker()
            except Exception as exc:
                logging.exception("Journal refresh failed")
                Clock.schedule_once(lambda _dt, err=exc: self._journal_refresh_failed(generation, err), 0)
                return
            Clock.schedule_once(
                lambda _dt, payload=data: self._apply_journal_refresh(
                    generation, selected_text, payload, target, unit
                ), 0
            )

        Thread(target=run, name="journal-query", daemon=True).start()

    def _journal_refresh_failed(self, generation, error):
        if generation != getattr(self, "_journal_refresh_generation", generation):
            return
        self.info("日志加载失败", f"本机数据读取失败：{error}")

    def _apply_journal_refresh(self, generation, day_text, data, target, unit):
        if generation != getattr(self, "_journal_refresh_generation", generation):
            return
        foods = data["foods"]
        training = data["training"]
        measurements = data["measurements"]
        latest_measurement = data["latest_measurement"]
        average = data["average"]
        weight_progress = data["weight_progress"]
        calories = sum(float(row["calories_kcal"]) for row in foods)
        protein = sum(float(row["protein_g"]) for row in foods)
        carbs = sum(float(row["carbs_g"]) for row in foods)
        fat = sum(float(row["fat_g"]) for row in foods)
        self.journal_calories_label.text = f"{day_text} · 摄入 {calories:.0f} kcal"
        self.journal_macro_label.text = f"蛋白质 {protein:.1f} g · 碳水 {carbs:.1f} g · 脂肪 {fat:.1f} g"
        if average["average_jin"] is None:
            self.journal_7day_label.text = f"7 日平均体重：{average['start']} 至 {average['end']} 暂无记录"
        else:
            value = self.display_weight(average["average_jin"])
            self.journal_7day_label.text = f"7 日平均体重：{value:.1f} {unit}（{average['days']} 个有记录日期）"

        initial = weight_progress["first_weight_jin"]
        latest = weight_progress["current_weight_jin"]
        count = int(weight_progress["count"])
        progress = None
        if latest is not None and initial is not None and target is not None and abs(float(target) - initial) > 1e-8:
            progress = (latest - initial) / (float(target) - initial) * 100.0
        if progress is None:
            if target is None:
                self.journal_goal_label.text = "目标进度：先设置目标体重后显示"
            elif count == 0:
                self.journal_goal_label.text = "目标进度：先记录一次体重后显示"
            else:
                self.journal_goal_label.text = "目标进度：起始体重与目标相同"
            self.journal_goal_bar.value = 0
        else:
            bounded = max(0.0, min(100.0, progress))
            self.journal_goal_bar.value = bounded
            latest_display = self.display_weight(latest)
            target_display = self.display_weight(float(target))
            self.journal_goal_label.text = f"当前 {latest_display:.1f} {unit} · 目标 {target_display:.1f} {unit} · 进度 {bounded:.0f}%"

        self._clear_list(self.food_list_box)
        if not foods:
            self.food_list_box.add_widget(self.label("这一天还没有饮食记录。", 10, MUTED))
        else:
            for row in foods:
                line = BoxLayout(size_hint_y=None, height=dp(42), spacing=dp(3))
                meal_name = str(row["food_name"])
                if len(meal_name) > 9:
                    meal_name = meal_name[:9] + "…"
                line.add_widget(self.label(
                    f"{row['meal_type']} · {meal_name} {float(row['amount_g']):g}g · {float(row['calories_kcal']):.0f}kcal",
                    9, TEXT))
                edit = self.button("改", lambda *_args, item=row: self.add_food_dialog(item), 38, tone="soft")
                edit.size_hint_x = None; edit.width = dp(38)
                delete = self.button("删", lambda *_args, item=row: self.delete_food_with_undo(item), 38, tone="secondary")
                delete.size_hint_x = None; delete.width = dp(38)
                line.add_widget(edit); line.add_widget(delete)
                self.food_list_box.add_widget(line)
        if getattr(self, "journal_food_card", None) is not None:
            self.journal_food_card.height = max(dp(230), dp(95 + 42 * len(foods)))

        self._clear_list(self.training_list_box)
        if not training:
            self.training_list_box.add_widget(self.label("这一天还没有结构化训练记录。", 10, MUTED))
        else:
            for row in training:
                line = BoxLayout(size_hint_y=None, height=dp(42), spacing=dp(3))
                name = str(row["exercise_name"])
                if len(name) > 9:
                    name = name[:9] + "…"
                description = f"{name} · {row['sets']}组×{row['reps']}次 · {float(row['load_kg']):g}kg"
                if float(row["duration_minutes"]):
                    description += f" · {float(row['duration_minutes']):g}分"
                line.add_widget(self.label(description, 9, TEXT))
                edit = self.button("改", lambda *_args, item=row: self.add_training_dialog(item), 38, tone="soft")
                edit.size_hint_x = None; edit.width = dp(38)
                delete = self.button("删", lambda *_args, item=row: self.delete_training_with_undo(item), 38, tone="secondary")
                delete.size_hint_x = None; delete.width = dp(38)
                line.add_widget(edit); line.add_widget(delete)
                self.training_list_box.add_widget(line)
        if getattr(self, "journal_training_card", None) is not None:
            self.journal_training_card.height = max(dp(230), dp(95 + 42 * len(training)))

        self._clear_list(self.measurement_list_box)
        if latest_measurement:
            pieces = []
            for key, label, metric_unit in (("waist_cm", "腰", "cm"), ("hip_cm", "臀", "cm"),
                                            ("chest_cm", "胸", "cm"), ("body_fat_pct", "体脂", "%")):
                value = latest_measurement.get(key)
                if value is not None:
                    pieces.append(f"{label} {float(value):.1f}{metric_unit}")
            self.measurement_latest_label.text = f"最近测量 {latest_measurement['measured_at']}：" + ("、".join(pieces) or "无数值")
        else:
            self.measurement_latest_label.text = "还没有身体围度记录。"
        if not measurements:
            self.measurement_list_box.add_widget(self.label("所选日期没有围度记录。", 10, MUTED))
        else:
            for row in measurements:
                values = []
                for key, label, metric_unit in (("waist_cm", "腰", "cm"), ("hip_cm", "臀", "cm"),
                                                ("chest_cm", "胸", "cm"), ("body_fat_pct", "体脂", "%")):
                    if row.get(key) is not None:
                        values.append(f"{label}{float(row[key]):.1f}{metric_unit}")
                line = BoxLayout(size_hint_y=None, height=dp(38), spacing=dp(3))
                line.add_widget(self.label(" · ".join(values) or "测量", 9, TEXT))
                edit = self.button("改", lambda *_args, item=row: self.add_measurement_dialog(item), 36, tone="soft")
                edit.size_hint_x = None; edit.width = dp(38)
                delete = self.button("删", lambda *_args, item=row: self.delete_measurement_with_undo(item), 36, tone="secondary")
                delete.size_hint_x = None; delete.width = dp(38)
                line.add_widget(edit); line.add_widget(delete)
                self.measurement_list_box.add_widget(line)
        if getattr(self, "journal_measurement_card", None) is not None:
            self.journal_measurement_card.height = max(dp(202), dp(82 + 38 * len(measurements)))

    @staticmethod
    def _input_line(app, form, label, value="", hint="", numeric=False):
        row = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(6))
        lab = app.label(label, 10, MUTED)
        lab.size_hint_x = None; lab.width = dp(76)
        row.add_widget(lab)
        kwargs = {"text": str(value if value is not None else ""), "hint_text": hint}
        if numeric:
            kwargs["input_filter"] = "int" if numeric == "int" else "float"
        inp = app._field(**kwargs)
        row.add_widget(app._field_box(inp))
        form.add_widget(row)
        return inp

    def _date_time_defaults(self):
        selected = self._journal_selected_date()
        time_text = datetime.now().strftime("%H:%M") if selected == date.today() else "12:00"
        return selected.isoformat(), time_text

    def add_food_dialog(self, row=None, *_):
        selected_date, default_time = self._date_time_defaults()
        if row:
            selected_date = str(row["logged_at"])[:10]
            default_time = str(row["logged_at"])[11:16]
        content = BoxLayout(orientation="vertical", padding=dp(8), spacing=dp(5))
        scroll = ScrollView(do_scroll_x=False, do_scroll_y=True, bar_width=dp(3))
        form = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(4))
        form.bind(minimum_height=form.setter("height"))
        date_i = self._input_line(self, form, "日期", selected_date, "YYYY-MM-DD")
        time_i = self._input_line(self, form, "时间", default_time, "HH:MM")
        meal = Spinner(text=str(row["meal_type"] if row else "早餐"), values=("早餐", "午餐", "晚餐", "加餐"),
                       size_hint_y=None, height=dp(38), font_name=FONT_NAME, option_cls=SpinnerOption,
                       background_normal="", background_color=CARD, color=TEXT)
        meal_row = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(6))
        lab = self.label("餐次", 10, MUTED); lab.size_hint_x=None; lab.width=dp(76)
        meal_row.add_widget(lab); meal_row.add_widget(meal); form.add_widget(meal_row)
        foods = self.storage.list_foods()
        name_i = self._input_line(self, form, "食物", row["food_name"] if row else "", "例如：鸡蛋、米饭")
        picker_row = BoxLayout(size_hint_y=None, height=dp(36), spacing=dp(6))
        picker_row.add_widget(self.label("常用食物", 10, MUTED))
        picker = Spinner(text="选择已保存食物", values=tuple(food["name"] for food in foods),
                         size_hint_y=None, height=dp(36), font_name=FONT_NAME, option_cls=SpinnerOption,
                         background_normal="", background_color=CARD, color=TEXT)
        picker_row.add_widget(picker); form.add_widget(picker_row)
        existing_amount = float(row["amount_g"]) if row else 100.0
        existing_per = lambda key: (float(row.get(key, 0) or 0) / existing_amount * 100.0) if row and existing_amount else 0
        amount_i = self._input_line(self, form, "份量(g)", existing_amount, "实际吃了多少克", True)
        kcal_i = self._input_line(self, form, "热量/100g", existing_per("calories_kcal") if row else "0", "kcal", True)
        protein_i = self._input_line(self, form, "蛋白质/100g", existing_per("protein_g") if row else "0", "g", True)
        carbs_i = self._input_line(self, form, "碳水/100g", existing_per("carbs_g") if row else "0", "g", True)
        fat_i = self._input_line(self, form, "脂肪/100g", existing_per("fat_g") if row else "0", "g", True)
        scroll.add_widget(form); content.add_widget(scroll)
        actions = BoxLayout(size_hint_y=None, height=dp(42), spacing=dp(8))
        popup = Popup(title="编辑饮食记录" if row else "添加饮食记录", title_font=FONT_NAME,
                      content=content, size_hint=(.96, .88), background="", separator_color=(0, 0, 0, 0))

        def select_food(_spinner, food_name):
            item = next((f for f in foods if f["name"] == food_name), None)
            if item:
                name_i.text = item["name"]
                kcal_i.text = str(item["calories_per_100g"])
                protein_i.text = str(item["protein_per_100g"])
                carbs_i.text = str(item["carbs_per_100g"])
                fat_i.text = str(item["fat_per_100g"])
        picker.bind(text=select_food)

        def save(*_):
            try:
                stamp = datetime.strptime(f"{date_i.text.strip()} {time_i.text.strip()}", "%Y-%m-%d %H:%M")
                args = (stamp, meal.text, name_i.text, amount_i.text, kcal_i.text,
                        protein_i.text or 0, carbs_i.text or 0, fat_i.text or 0)
                if row:
                    self.storage.update_food_log(int(row["id"]), *args)
                else:
                    self.storage.add_food_log(*args)
                popup.dismiss()
                self.refresh_journal()
            except Exception as exc:
                self.info("保存饮食失败", str(exc))
        actions.add_widget(self.button("取消", lambda *_: popup.dismiss(), 42, tone="secondary"))
        actions.add_widget(self.button("保存记录", save, 42, tone="primary"))
        content.add_widget(actions)
        popup.open()

    def add_training_dialog(self, row=None, *_):
        selected_date, default_time = self._date_time_defaults()
        if row:
            selected_date = str(row["performed_at"])[:10]
            default_time = str(row["performed_at"])[11:16]
        content = BoxLayout(orientation="vertical", padding=dp(10), spacing=dp(6))
        form_scroll = ScrollView(do_scroll_x=False, do_scroll_y=True, bar_width=dp(3))
        form = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(4))
        form.bind(minimum_height=form.setter("height"))
        date_i = self._input_line(self, form, "日期", selected_date, "YYYY-MM-DD")
        time_i = self._input_line(self, form, "时间", default_time, "HH:MM")
        name_i = self._input_line(self, form, "动作/项目", row["exercise_name"] if row else "", "深蹲、卧推、跑步")
        sets_i = self._input_line(self, form, "组数", row["sets"] if row else "0", "力量训练填组数", "int")
        reps_i = self._input_line(self, form, "每组次数", row["reps"] if row else "0", "如 10", "int")
        load_i = self._input_line(self, form, "负重(kg)", row["load_kg"] if row else "0", "自重训练填 0", True)
        mins_i = self._input_line(self, form, "时长(分钟)", row["duration_minutes"] if row else "0", "有氧可只填时长", True)
        note_i = self._input_line(self, form, "备注", row.get("note") if row else "", "可不填")
        form_scroll.add_widget(form); content.add_widget(form_scroll)
        actions = BoxLayout(size_hint_y=None, height=dp(42), spacing=dp(8))
        popup = Popup(title="编辑训练记录" if row else "记录训练", title_font=FONT_NAME,
                      content=content, size_hint=(.95, .82), background="", separator_color=(0, 0, 0, 0))

        def save(*_):
            try:
                stamp = datetime.strptime(f"{date_i.text.strip()} {time_i.text.strip()}", "%Y-%m-%d %H:%M")
                args = (stamp, name_i.text, sets_i.text or 0, reps_i.text or 0, load_i.text or 0,
                        mins_i.text or 0, note_i.text)
                if row:
                    self.storage.update_strength_log(int(row["id"]), *args)
                else:
                    self.storage.add_strength_log(*args)
                popup.dismiss(); self.refresh_journal(); self.refresh_home_summary()
                if getattr(self, "calendar_grid", None) is not None:
                    self._calendar_cache_month = None
                    self.render_calendar()
            except Exception as exc:
                self.info("保存训练失败", str(exc))
        actions.add_widget(self.button("取消", lambda *_: popup.dismiss(), 42, tone="secondary"))
        actions.add_widget(self.button("保存训练", save, 42, tone="primary"))
        content.add_widget(actions)
        popup.open()

    def add_measurement_dialog(self, row=None, *_):
        selected_date, _ = self._date_time_defaults()
        if row:
            selected_date = str(row["measured_at"])
        content = BoxLayout(orientation="vertical", padding=dp(10), spacing=dp(6))
        # Keep the save/cancel actions outside a scrollable field list so the
        # form remains usable on short displays and with the Android keyboard.
        form_scroll = ScrollView(do_scroll_x=False, do_scroll_y=True, bar_width=dp(3),
                                 scroll_type=["bars", "content"])
        form = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(4))
        form.bind(minimum_height=form.setter("height"))
        date_i = self._input_line(self, form, "日期", selected_date, "YYYY-MM-DD")
        waist_i = self._input_line(self, form, "腰围(cm)", row.get("waist_cm") if row else "", "可不填", True)
        hip_i = self._input_line(self, form, "臀围(cm)", row.get("hip_cm") if row else "", "可不填", True)
        chest_i = self._input_line(self, form, "胸围(cm)", row.get("chest_cm") if row else "", "可不填", True)
        fat_i = self._input_line(self, form, "体脂率(%)", row.get("body_fat_pct") if row else "", "可不填", True)
        note_i = self._input_line(self, form, "备注", row.get("note") if row else "", "测量条件可记录在这里")
        form_scroll.add_widget(form)
        content.add_widget(form_scroll)
        actions = BoxLayout(size_hint_y=None, height=dp(42), spacing=dp(8))
        popup = Popup(title="编辑身体指标" if row else "记录身体指标", title_font=FONT_NAME,
                      content=content, size_hint=(.95, .82), background="", separator_color=(0, 0, 0, 0))

        def save(*_):
            try:
                args = (date_i.text, waist_i.text, hip_i.text, chest_i.text, fat_i.text, note_i.text)
                if row:
                    self.storage.update_body_measurement(int(row["id"]), *args)
                else:
                    self.storage.add_body_measurement(*args)
                popup.dismiss(); self.refresh_journal()
            except Exception as exc:
                self.info("保存身体指标失败", str(exc))
        actions.add_widget(self.button("取消", lambda *_: popup.dismiss(), 42, tone="secondary"))
        actions.add_widget(self.button("保存", save, 42, tone="primary"))
        content.add_widget(actions); popup.open()

    def _show_undo_popup(self, title, text, restore_callback):
        content = BoxLayout(orientation="vertical", padding=dp(12), spacing=dp(8))
        content.add_widget(self.label(text, 12, TEXT))
        actions = BoxLayout(size_hint_y=None, height=dp(42), spacing=dp(8))
        popup = Popup(title=title, title_font=FONT_NAME, content=content, size_hint=(.9, None),
                      height=dp(145), background="", separator_color=(0, 0, 0, 0))
        actions.add_widget(self.button("知道了", lambda *_: popup.dismiss(), 42, tone="secondary"))
        actions.add_widget(self.button("撤销删除", lambda *_: restore_callback(popup), 42, tone="primary"))
        content.add_widget(actions); popup.open()

    def delete_food_with_undo(self, row):
        try:
            deleted = self.storage.delete_food_log(row["id"]); self.refresh_journal()
            def undo(popup):
                try:
                    self.storage.restore_food_log(deleted); popup.dismiss(); self.refresh_journal()
                except Exception as exc: self.info("撤销失败", str(exc))
            self._show_undo_popup("饮食记录已删除", f"已删除 {row['food_name']}，可以立即撤销。", undo)
        except Exception as exc: self.info("删除失败", str(exc))

    def delete_training_with_undo(self, row):
        try:
            deleted = self.storage.delete_strength_log(row["id"]); self.refresh_journal()
            def undo(popup):
                try:
                    self.storage.restore_strength_log(deleted); popup.dismiss(); self.refresh_journal(); self.refresh_home_summary()
                except Exception as exc: self.info("撤销失败", str(exc))
            self._show_undo_popup("训练记录已删除", f"已删除 {row['exercise_name']}，可以立即撤销。", undo)
        except Exception as exc: self.info("删除失败", str(exc))

    def delete_measurement_with_undo(self, row):
        try:
            deleted = self.storage.delete_body_measurement(row["id"]); self.refresh_journal()
            def undo(popup):
                try:
                    self.storage.restore_body_measurement(deleted); popup.dismiss(); self.refresh_journal()
                except Exception as exc: self.info("撤销失败", str(exc))
            self._show_undo_popup("身体测量已删除", f"已删除 {row['measured_at']} 的测量，可以立即撤销。", undo)
        except Exception as exc: self.info("删除失败", str(exc))

    def _reminder_day_action(self, kind, day_text):
        if kind == "weight":
            latest = self.storage.latest_record()
            return bool(latest and str(latest["recorded_at"])[:10] == day_text), "记录今天体重", "别忘了记录今天的体重。"
        if kind == "food":
            done = bool(self.storage.list_food_logs(day_text, day_text, limit=1))
            return done, "补记今日饮食", "今天还没有饮食记录，可以补记餐食与热量。"
        done = self.storage.get_workout(day_text)
        return bool(done), "训练打卡提醒", "今天还没有训练打卡，按自己的计划活动即可。"

    def _check_due_reminders(self):
        if not getattr(self, "storage", None) or not getattr(self, "_startup_finished", False):
            return
        now = datetime.now()
        day_text = now.date().isoformat()
        now_minutes = now.hour * 60 + now.minute
        for key in ("weight", "food", "workout"):
            if not self._parse_bool_setting(self.storage.get_setting(f"reminder_{key}_enabled"), False):
                continue
            raw = str(self.storage.get_setting(f"reminder_{key}_time") or {"weight": "08:00", "food": "20:00", "workout": "18:00"}[key])
            try:
                hour, minute = map(int, raw.split(":"))
                planned = hour * 60 + minute
            except (ValueError, TypeError):
                continue
            if not 0 <= hour < 24 or not 0 <= minute < 60 or not 0 <= now_minutes - planned <= 4:
                continue
            if str(self.storage.get_setting(f"reminder_{key}_last_sent") or "") == day_text:
                continue
            done, title, message = self._reminder_day_action(key, day_text)
            if done:
                self.storage.set_setting(f"reminder_{key}_last_sent", day_text)
                continue
            if post_local_notification(title, message):
                self.storage.set_setting(f"reminder_{key}_last_sent", day_text)
            elif not IS_ANDROID:
                # A deterministic desktop fallback for developers/test sessions.
                self.storage.set_setting(f"reminder_{key}_last_sent", day_text)
                if getattr(self, "current_screen", None) == "journal":
                    self.info(title, message)

    def set_reminder_enabled(self, key, enabled):
        self.storage.set_setting(f"reminder_{key}_enabled", "true" if enabled else "false")
        if enabled:
            request_notification_permission()
            if not getattr(self, "_reminder_explained", False):
                self._reminder_explained = True
                Clock.schedule_once(lambda _dt: self.info(
                    "本机提醒", "提醒通过 Android 本地通知发送，不需要服务器。系统强行停止或终止 App 进程时无法保证准时触发。"), 0.1)

    def save_reminder_times(self, *_):
        errors = []
        for key, input_widget in getattr(self, "reminder_inputs", {}).items():
            raw = input_widget.text.strip()
            if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", raw):
                errors.append(f"{key} 的时间格式无效")
        if errors:
            self.info("提醒时间无效", "请使用 24 小时制 HH:MM，例如 08:30。\n" + "\n".join(errors)); return
        for key, input_widget in self.reminder_inputs.items():
            self.storage.set_setting(f"reminder_{key}_time", input_widget.text.strip())
        self.info("已保存提醒", "本地提醒时间已更新。请允许系统通知；App 未运行或被强行停止时无法保证准时触发。")

    def open_health_report(self, period="week", *_):
        period = "month" if period == "month" else "week"
        unit = self.weight_unit_label()
        def worker():
            summary = self.storage.build_health_report(period)
            return format_health_report(summary, unit)
        self.run_background_task(
            "正在生成健康报告", worker,
            on_success=self._show_health_report,
            on_error=lambda exc: self.info("生成报告失败", f"{type(exc).__name__}: {exc}"),
        )

    def _show_health_report(self, text):
        content = BoxLayout(orientation="vertical", padding=dp(10), spacing=dp(8))
        scroll = ScrollView(do_scroll_x=False, do_scroll_y=True, bar_width=dp(3))
        label = self.label(text, 11, TEXT)
        label.size_hint_y = None
        label.bind(width=lambda widget, width: setattr(widget, "text_size", (max(1, width), None)))
        label.bind(texture_size=lambda widget, size: setattr(widget, "height", size[1] + dp(8)))
        scroll.add_widget(label); content.add_widget(scroll)
        actions = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(8))
        popup = Popup(title="健康报告", title_font=FONT_NAME, content=content,
                      size_hint=(.94, .88), background="", separator_color=(0, 0, 0, 0))
        actions.add_widget(self.button("关闭", lambda *_: popup.dismiss(), 44, tone="secondary"))
        actions.add_widget(self.button("分享报告", lambda *_: self.share_health_report(text), 44, tone="primary"))
        content.add_widget(actions); popup.open()

    def share_health_report(self, text):
        if IS_ANDROID and ANDROID_AVAILABLE:
            try:
                Intent = autoclass("android.content.Intent")
                intent = Intent(Intent.ACTION_SEND)
                intent.setType("text/plain")
                intent.putExtra(Intent.EXTRA_TEXT, str(text))
                chooser = Intent.createChooser(intent, "分享健康报告")
                get_current_activity().startActivity(chooser)
                return
            except Exception as exc:
                self.info("打开分享菜单失败", str(exc)); return
        try:
            Clipboard.copy(str(text))
            self.info("报告已复制", "当前不是 Android 环境，报告已复制到剪贴板。")
        except Exception as exc:
            self.info("复制报告失败", str(exc))
