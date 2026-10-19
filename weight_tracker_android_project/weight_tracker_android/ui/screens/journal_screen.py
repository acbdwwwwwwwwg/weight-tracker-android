"""Local nutrition, strength training, body-measurement and reports screen."""
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.scrollview import ScrollView
from kivy.uix.widget import Widget
from kivy.uix.checkbox import CheckBox
from kivy.uix.textinput import TextInput
from kivy.uix.spinner import Spinner, SpinnerOption
from kivy.uix.progressbar import ProgressBar

from ui.theme import CARD, CARD_ALT, GREEN, FONT_NAME, MUTED, PRIMARY, TEXT
from ui.widgets import RoundedPanel


class JournalScreenMixin:
    def build_journal_screen(self):
        scroll = ScrollView(do_scroll_x=False, do_scroll_y=True, bar_width=dp(3),
                            scroll_type=["bars", "content"])
        content = BoxLayout(orientation="vertical", padding=(dp(12), dp(12), dp(12), dp(16)),
                            spacing=dp(10), size_hint_y=None)
        content.bind(minimum_height=content.setter("height"))
        header = RoundedPanel(orientation="vertical", padding=dp(13), spacing=dp(3),
                              size_hint_y=None, height=dp(76), panel_color=CARD)
        header.add_widget(self.label("DAILY HEALTH JOURNAL", 10, PRIMARY, True))
        header.add_widget(self.label("饮食 · 训练 · 身体变化", 19, TEXT, True))
        header.add_widget(self.label("本机记录，无需登录或联网", 10, MUTED))
        content.add_widget(header)

        date_card = RoundedPanel(orientation="horizontal", padding=(dp(9), dp(7)), spacing=dp(7),
                                 size_hint_y=None, height=dp(52), panel_color=CARD)
        date_card.add_widget(self.label("记录日期", 11, TEXT, True))
        self.journal_date_input = self._field(text=__import__("datetime").datetime.now().strftime("%Y-%m-%d"),
                                              hint_text="YYYY-MM-DD")
        date_card.add_widget(self._field_box(self.journal_date_input))
        date_card.add_widget(self.button("查看", self.refresh_journal, 40, tone="primary"))
        date_card.add_widget(self.button("今天", self.journal_today, 40, tone="soft"))
        content.add_widget(date_card)

        summary = RoundedPanel(orientation="vertical", padding=dp(12), spacing=dp(7),
                               size_hint_y=None, height=dp(144), panel_color=CARD_ALT)
        summary.add_widget(self.label("所选日期饮食与减脂进展", 13, TEXT, True))
        self.journal_calories_label = self.label("摄入 0 kcal", 21, PRIMARY, True)
        summary.add_widget(self.journal_calories_label)
        self.journal_macro_label = self.label("蛋白质 0 g · 碳水 0 g · 脂肪 0 g", 10, MUTED)
        summary.add_widget(self.journal_macro_label)
        self.journal_7day_label = self.label("7 日平均体重：暂无记录", 11, TEXT, True)
        summary.add_widget(self.journal_7day_label)
        self.journal_goal_label = self.label("目标进度：设置目标后显示", 10, MUTED)
        summary.add_widget(self.journal_goal_label)
        self.journal_goal_bar = ProgressBar(max=100, value=0, size_hint_y=None, height=dp(7))
        summary.add_widget(self.journal_goal_bar)
        content.add_widget(summary)

        food_card = RoundedPanel(orientation="vertical", padding=dp(11), spacing=dp(7),
                                 size_hint_y=None, height=dp(230), panel_color=CARD)
        food_header = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(6))
        food_header.add_widget(self.label("饮食记录", 14, TEXT, True))
        food_header.add_widget(Widget())
        food_header.add_widget(self.button("＋ 添加食物", self.add_food_dialog, 40, tone="primary"))
        food_card.add_widget(food_header)
        food_card.add_widget(self.label("按实际份量计算热量与三大营养素；常用食物会自动保存。", 9, MUTED))
        self.food_list_box = BoxLayout(orientation="vertical", spacing=dp(4), size_hint_y=None)
        self.food_list_box.bind(minimum_height=self.food_list_box.setter("height"))
        food_card.add_widget(self.food_list_box)
        self.journal_food_card = food_card
        content.add_widget(food_card)

        training_card = RoundedPanel(orientation="vertical", padding=dp(11), spacing=dp(7),
                                     size_hint_y=None, height=dp(230), panel_color=CARD)
        training_header = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(6))
        training_header.add_widget(self.label("力量 / 有氧训练日志", 14, TEXT, True))
        training_header.add_widget(Widget())
        training_header.add_widget(self.button("＋ 记录训练", self.add_training_dialog, 40, tone="primary"))
        training_card.add_widget(training_header)
        training_card.add_widget(self.label("记录动作、组数、次数、负重(kg)和训练时长；保存后同步训练打卡。", 9, MUTED))
        self.training_list_box = BoxLayout(orientation="vertical", spacing=dp(4), size_hint_y=None)
        self.training_list_box.bind(minimum_height=self.training_list_box.setter("height"))
        training_card.add_widget(self.training_list_box)
        self.journal_training_card = training_card
        content.add_widget(training_card)

        measure_card = RoundedPanel(orientation="vertical", padding=dp(11), spacing=dp(7),
                                    size_hint_y=None, height=dp(202), panel_color=CARD)
        measure_header = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(6))
        measure_header.add_widget(self.label("身体围度与体脂", 14, TEXT, True))
        measure_header.add_widget(Widget())
        measure_header.add_widget(self.button("＋ 记录围度", self.add_measurement_dialog, 40, tone="primary"))
        measure_card.add_widget(measure_header)
        self.measurement_latest_label = self.label("腰围 / 臀围 / 胸围 / 体脂率均为可选项。", 10, MUTED)
        self.measurement_latest_label.size_hint_y = None
        self.measurement_latest_label.height = dp(36)
        self.measurement_latest_label.bind(width=lambda widget, width: setattr(widget, "text_size", (max(1, width), None)))
        measure_card.add_widget(self.measurement_latest_label)
        self.measurement_list_box = BoxLayout(orientation="vertical", spacing=dp(4), size_hint_y=None)
        self.measurement_list_box.bind(minimum_height=self.measurement_list_box.setter("height"))
        measure_card.add_widget(self.measurement_list_box)
        self.journal_measurement_card = measure_card
        content.add_widget(measure_card)

        reminder_card = RoundedPanel(orientation="vertical", padding=dp(11), spacing=dp(6),
                                     size_hint_y=None, height=dp(220), panel_color=CARD)
        reminder_card.add_widget(self.label("本机提醒", 14, TEXT, True))
        reminder_card.add_widget(self.label("首次开启需允许通知。提醒在 App 运行或恢复时检查；强行停止或系统终止进程后不能保证准时触发。", 9, MUTED))
        self.reminder_checks = {}
        self.reminder_inputs = {}
        for key, title, default_time in (("weight", "每日称重", "08:00"),
                                         ("food", "补记饮食", "20:00"),
                                         ("workout", "训练打卡", "18:00")):
            row = BoxLayout(size_hint_y=None, height=dp(38), spacing=dp(6))
            check = CheckBox(active=self._setting_bool(f"reminder_{key}_enabled", False),
                             size_hint_x=None, width=dp(38))
            check.bind(active=lambda _widget, value, k=key: self.set_reminder_enabled(k, value))
            row.add_widget(check)
            row.add_widget(self.label(title, 11, TEXT))
            row.add_widget(Widget())
            time_input = self._field(text=str(self.storage.get_setting(f"reminder_{key}_time") or default_time),
                                     hint_text="HH:MM", size_hint_x=None, size_hint_y=None, height=dp(36))
            time_input.size_hint_x = None
            time_input.width = dp(82)
            row.add_widget(time_input)
            self.reminder_checks[key] = check
            self.reminder_inputs[key] = time_input
            reminder_card.add_widget(row)
        reminder_card.add_widget(self.button("保存提醒时间", self.save_reminder_times, 40, tone="secondary"))
        content.add_widget(reminder_card)

        report_card = RoundedPanel(orientation="vertical", padding=dp(11), spacing=dp(7),
                                   size_hint_y=None, height=dp(124), panel_color=CARD)
        report_card.add_widget(self.label("周 / 月报告", 14, TEXT, True))
        report_card.add_widget(self.label("汇总体重趋势、7 日平均、饮食热量、训练时长和身体变化。", 9, MUTED))
        report_row = BoxLayout(size_hint_y=None, height=dp(42), spacing=dp(7))
        report_row.add_widget(self.button("生成本周报告", lambda *_: self.open_health_report("week"), 42, tone="primary"))
        report_row.add_widget(self.button("生成本月报告", lambda *_: self.open_health_report("month"), 42, tone="secondary"))
        report_card.add_widget(report_row)
        content.add_widget(report_card)

        content.add_widget(self.label("数据提示：饮食热量来自手动输入或自定义食物库，不是自动识别值；训练负重单位固定为 kg。", 9, MUTED))
        scroll.add_widget(content)
        return scroll

    def _setting_bool(self, key, default=False):
        return self._parse_bool_setting(self.storage.get_setting(key), default)
