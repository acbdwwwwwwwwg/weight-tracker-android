"""Calendar page composition, separated from calendar behavior/state logic."""
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.scrollview import ScrollView
from kivy.uix.widget import Widget

from ui.theme import CARD, CARD_ALT, GREEN, MUTED, PRIMARY, PURPLE, TEXT
from ui.widgets import RoundedPanel


class CalendarScreenMixin:
    """Construct the daily training calendar surface."""

    def build_calendar_screen(self):
        scroll = ScrollView(do_scroll_x=False, do_scroll_y=True, bar_width=dp(3),
                            scroll_type=["bars", "content"])
        content = BoxLayout(orientation="vertical", padding=(dp(14), dp(14), dp(14), dp(16)),
                            spacing=dp(12), size_hint_y=None)
        content.bind(minimum_height=content.setter("height"))

        header = RoundedPanel(orientation="horizontal", padding=(dp(15), dp(11)), spacing=dp(9),
                              size_hint_y=None, height=dp(72), panel_color=CARD)
        title = BoxLayout(orientation="vertical", spacing=dp(2))
        title.add_widget(self.label("TRAINING LOG", 10, PRIMARY, True))
        title.add_widget(self.label("训练日历", 19, TEXT, True))
        header.add_widget(title)
        header.add_widget(Widget())
        today_btn = self.button("回到今天", self.calendar_today, 42, tone="primary")
        today_btn.size_hint_x = None
        today_btn.width = dp(90)
        header.add_widget(today_btn)
        content.add_widget(header)

        overview = RoundedPanel(orientation="vertical", padding=(dp(13), dp(11)), spacing=dp(6),
                                size_hint_y=None, height=dp(106), panel_color=CARD)
        overview.add_widget(self.label("坚持概览", 13, TEXT, True))
        metrics = GridLayout(cols=3, spacing=dp(5), size_hint_y=None, height=dp(63))
        self.calendar_overview_labels = {}
        for key, caption, accent in (("month_workouts", "本月健身", GREEN),
                                     ("month_photos", "本月照片", PRIMARY),
                                     ("all_photos", "累计照片", PURPLE)):
            cell = BoxLayout(orientation="vertical", spacing=dp(1))
            value = self.label("0", 21, accent, True)
            self.calendar_overview_labels[key] = value
            cell.add_widget(value)
            cell.add_widget(self.label(caption, 10, MUTED))
            metrics.add_widget(cell)
        overview.add_widget(metrics)
        content.add_widget(overview)

        week_card = RoundedPanel(orientation="vertical", padding=(dp(11), dp(9)), spacing=dp(6),
                                 size_hint_y=None, height=dp(112), panel_color=CARD)
        week_head = BoxLayout(size_hint_y=None, height=dp(20))
        week_head.add_widget(self.label("本周打卡", 13, TEXT, True))
        week_head.add_widget(Widget())
        self.week_summary_label = self.label("本周 0 天", 10, GREEN, True)
        week_head.add_widget(self.week_summary_label)
        week_card.add_widget(week_head)
        self.week_strip = GridLayout(cols=7, spacing=dp(5), size_hint_y=None, height=dp(58))
        week_card.add_widget(self.week_strip)
        content.add_widget(week_card)

        month_card = RoundedPanel(orientation="vertical", padding=(dp(12), dp(11)), spacing=dp(8),
                                  size_hint_y=None, height=dp(385), panel_color=CARD)
        month_head = BoxLayout(size_hint_y=None, height=dp(42), spacing=dp(6))
        month_title = BoxLayout(orientation="vertical", spacing=dp(0))
        month_title.add_widget(self.label("月历", 14, TEXT, True))
        month_title.add_widget(self.label("✓ 已健身 · 数字为照片数（可同时显示）", 9, MUTED))
        month_head.add_widget(month_title)
        month_nav = BoxLayout(size_hint_x=None, width=dp(170), spacing=dp(5))
        prev_month = self.button("‹", self.calendar_prev_month, 40, tone="soft")
        prev_month.size_hint_x = None
        prev_month.width = dp(40)
        self.calendar_title = self.label("", 11, TEXT, True)
        self.calendar_title.size_hint_x = 1
        next_month = self.button("›", self.calendar_next_month, 40, tone="soft")
        next_month.size_hint_x = None
        next_month.width = dp(40)
        month_nav.add_widget(prev_month)
        month_nav.add_widget(self.calendar_title)
        month_nav.add_widget(next_month)
        month_head.add_widget(month_nav)
        month_card.add_widget(month_head)
        weekdays = GridLayout(cols=7, spacing=dp(2), size_hint_y=None, height=dp(20))
        for day_name in ("一", "二", "三", "四", "五", "六", "日"):
            weekdays.add_widget(self.label(day_name, 10, MUTED, True))
        month_card.add_widget(weekdays)
        self.calendar_grid = GridLayout(cols=7, spacing=dp(4), size_hint_y=None, height=dp(6 * 44))
        month_card.add_widget(self.calendar_grid)
        content.add_widget(month_card)

        detail = RoundedPanel(orientation="vertical", padding=(dp(12), dp(11)), spacing=dp(7),
                              size_hint_y=None, height=dp(136), panel_color=CARD_ALT)
        self.calendar_selected_label = self.label("选择一个日期", 14, TEXT, True)
        detail.add_widget(self.calendar_selected_label)
        self.calendar_detail_subtitle = self.label("查看当天训练状态与体型照片。", 10, MUTED)
        detail.add_widget(self.calendar_detail_subtitle)
        actions = BoxLayout(size_hint_y=None, height=dp(42), spacing=dp(7))
        self.workout_button = self.button("＋ 健身打卡", self.toggle_selected_workout, 42, tone="success")
        actions.add_widget(self.workout_button)
        actions.add_widget(self.button("＋ 添加照片", self.add_body_photo, 42, tone="primary"))
        actions.add_widget(self.button("查看照片", self.open_progress_for_selected_date, 42, tone="secondary"))
        detail.add_widget(actions)
        self.photo_count_label = self.label("", 10, MUTED)
        detail.add_widget(self.photo_count_label)
        content.add_widget(detail)

        content.add_widget(self._calendar_legend())
        scroll.add_widget(content)
        self.calendar_screen_widget = scroll
        return scroll

    def _calendar_legend(self):
        legend = RoundedPanel(orientation="horizontal", padding=(dp(12), dp(9)), spacing=dp(8),
                              size_hint_y=None, height=dp(44), panel_color=CARD)
        legend.add_widget(self.label("状态", 10, MUTED, True))
        legend.add_widget(self.label("●", 11, GREEN, True))
        legend.add_widget(self.label("已健身", 10, TEXT))
        legend.add_widget(Widget())
        legend.add_widget(self.label("●", 11, PURPLE, True))
        legend.add_widget(self.label("有照片", 10, TEXT))
        return legend

