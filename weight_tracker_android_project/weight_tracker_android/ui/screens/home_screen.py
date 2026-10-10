"""Home screen: the fastest path to daily weight and workout entry."""
from datetime import datetime, timedelta

from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.scrollview import ScrollView
from kivy.uix.widget import Widget

from ui.theme import (BG, CARD, CARD_ALT, FIELD_BG, FONT_NAME, GREEN, GREEN_DARK,
                      MUTED, PRIMARY, PRIMARY_DARK, PURPLE, SURFACE, SURFACE_DOWN,
                      TEXT, WHITE)
from ui.widgets import PlotWidget, RoundedButton, RoundedPanel


class HomeScreenMixin:
    """Build reusable home UI; data/CRUD actions remain in feature mixins."""

    def build_home_screen(self):
        scroll = ScrollView(do_scroll_x=False, do_scroll_y=True, bar_width=dp(3),
                            scroll_type=["bars", "content"])
        content = BoxLayout(orientation="vertical", padding=(dp(12), dp(12), dp(12), dp(14)),
                            spacing=dp(10), size_hint_y=None)
        content.bind(minimum_height=content.setter("height"))
        content.add_widget(self.build_home_header())
        content.add_widget(self.build_today_card())
        content.add_widget(self.build_weight_entry_card())
        content.add_widget(self.build_stats())
        content.add_widget(self.build_period_nav())
        content.add_widget(self.build_home_workout_card())
        content.add_widget(self.build_trend_card())
        scroll.add_widget(content)
        return scroll

    def build_home_header(self):
        panel = RoundedPanel(orientation="horizontal", padding=(dp(15), dp(10)), spacing=dp(8),
                             size_hint_y=None, height=dp(68), panel_color=CARD)
        brand = BoxLayout(orientation="vertical", spacing=dp(1))
        brand.add_widget(self.label("FIT / TRACK", 10, PRIMARY, True))
        brand.add_widget(self.label("今天，继续变强", 19, TEXT, True))
        now = datetime.now()
        weekday = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")[now.weekday()]
        self.home_date_label = self.label(now.strftime("%Y年%m月%d日") + f" · {weekday}", 10, MUTED)
        brand.add_widget(self.home_date_label)
        panel.add_widget(brand)
        panel.add_widget(Widget())
        return panel

    def build_today_card(self):
        card = RoundedPanel(orientation="vertical", padding=(dp(15), dp(12)), spacing=dp(5),
                            size_hint_y=None, height=dp(118), panel_color=CARD_ALT)
        top = BoxLayout(size_hint_y=None, height=dp(22))
        top.add_widget(self.label("今日体重", 13, MUTED, True))
        top.add_widget(Widget())
        self.home_today_hint = self.label("开始记录今天的状态", 10, MUTED)
        top.add_widget(self.home_today_hint)
        card.add_widget(top)
        row = BoxLayout(orientation="horizontal", spacing=dp(8))
        value_col = BoxLayout(orientation="vertical", spacing=dp(0))
        value_row = BoxLayout(orientation="horizontal", spacing=dp(5), size_hint_y=None, height=dp(52))
        self.home_today_value = self.label("待记录", 29, TEXT, True)
        value_row.add_widget(self.home_today_value)
        value_row.add_widget(self.label("斤", 12, MUTED))
        value_col.add_widget(value_row)
        self.home_today_change = self.label("记录体重，观察自己的变化", 10, MUTED)
        value_col.add_widget(self.home_today_change)
        row.add_widget(value_col)
        row.add_widget(Widget())
        card.add_widget(row)
        return card

    def build_weight_entry_card(self):
        card = RoundedPanel(orientation="vertical", padding=dp(12), spacing=dp(8),
                            size_hint_y=None, height=dp(188), panel_color=CARD)
        title = BoxLayout(size_hint_y=None, height=dp(22))
        title.add_widget(self.label("记录体重", 14, TEXT, True))
        title.add_widget(Widget())
        title.add_widget(self.label("单位：斤", 10, MUTED))
        card.add_widget(title)

        first = BoxLayout(spacing=dp(7), size_hint_y=None, height=dp(40))
        self.date_input = self._field(text=datetime.now().strftime("%Y-%m-%d %H:%M"),
                                      hint_text="日期 / 时间")
        self.weight_input = self._field(input_filter="float", hint_text="体重")
        first.add_widget(self._field_box(self.date_input, size_hint_x=0.65))
        first.add_widget(self._field_box(self.weight_input, size_hint_x=0.35))
        card.add_widget(first)

        second = BoxLayout(spacing=dp(7), size_hint_y=None, height=dp(39))
        self.note_input = self._field(hint_text="备注（可不填）")
        save = self.button("保存记录", self.save_record, 39, tone="primary")
        save.size_hint_x = None
        save.width = dp(104)
        second.add_widget(self._field_box(self.note_input))
        second.add_widget(save)
        card.add_widget(second)

        scroll = ScrollView(size_hint_y=None, height=dp(34), do_scroll_x=True, do_scroll_y=False,
                            bar_width=dp(2), scroll_type=["bars", "content"])
        quick = BoxLayout(size_hint_x=None, width=dp(644), spacing=dp(6))
        quick.add_widget(self.label("快捷", 10, MUTED, True))
        for title_text, delta in [("−1斤", -1), ("−0.5斤", -0.5), ("上次体重", 0), ("+0.5斤", 0.5), ("+1斤", 1)]:
            btn = self.button(title_text, lambda _, d=delta: self.quick_weight(d), 32, tone="soft")
            btn.size_hint_x = None
            btn.width = dp(78 if title_text == "上次体重" else 64)
            quick.add_widget(btn)
        for note in ("晨起", "运动后", "睡前"):
            btn = self.button(note, lambda _, n=note: self.set_note(n), 32, tone="success")
            btn.size_hint_x = None
            btn.width = dp(62)
            quick.add_widget(btn)
        scroll.add_widget(quick)
        card.add_widget(scroll)
        return card

    def build_stats(self):
        self.stats = {}
        card = RoundedPanel(orientation="vertical", padding=(dp(11), dp(9)), spacing=dp(5),
                            size_hint_y=None, height=dp(100), panel_color=CARD)
        card.add_widget(self.label("近期概览", 12, MUTED, True))
        grid = GridLayout(cols=5, spacing=dp(3), size_hint_y=None, height=dp(60))
        for key, title in [("avg", "平均"), ("max", "最高"), ("min", "最低"), ("diff", "变化"), ("bmi", "BMI")]:
            cell = BoxLayout(orientation="vertical", spacing=dp(2))
            cell.add_widget(self.label(title, 10, MUTED))
            value = self.label("--", 14, PURPLE, True)
            self.stats[key] = value
            cell.add_widget(value)
            grid.add_widget(cell)
        card.add_widget(grid)
        return card

    def build_period_nav(self):
        row = RoundedPanel(orientation="horizontal", padding=(dp(7), dp(6)), spacing=dp(6),
                           size_hint_y=None, height=dp(46), panel_color=CARD)
        left = self.button("‹", self.prev_period, 33, tone="soft")
        left.size_hint_x = None
        left.width = dp(42)
        row.add_widget(left)
        self.range_label = self.label("", 10, TEXT, True)
        row.add_widget(self.range_label)
        right = self.button("›", self.next_period, 33, tone="soft")
        right.size_hint_x = None
        right.width = dp(42)
        row.add_widget(right)
        today = self.button("今天", self.today, 33, tone="primary")
        today.size_hint_x = None
        today.width = dp(60)
        row.add_widget(today)
        return row

    def build_home_workout_card(self):
        card = RoundedPanel(orientation="vertical", padding=(dp(12), dp(10)), spacing=dp(7),
                            size_hint_y=None, height=dp(94), panel_color=CARD)
        row = BoxLayout(size_hint_y=None, height=dp(20))
        row.add_widget(self.label("今天的训练", 13, TEXT, True))
        row.add_widget(Widget())
        self.home_workout_status = self.label("还没打卡", 11, MUTED, True)
        row.add_widget(self.home_workout_status)
        card.add_widget(row)
        actions = BoxLayout(spacing=dp(7), size_hint_y=None, height=dp(40))
        self.home_workout_button = self.button("✓  完成健身打卡", self.toggle_today_workout, 40, tone="success")
        actions.add_widget(self.home_workout_button)
        actions.add_widget(self.button("查看日历", lambda *_: self.navigate_to("calendar"), 40, tone="secondary"))
        actions.add_widget(self.button("体型照片", self.open_progress_home, 40, tone="secondary"))
        card.add_widget(actions)
        return card

    def build_trend_card(self):
        card = RoundedPanel(orientation="vertical", padding=(dp(4), dp(5)), spacing=dp(3),
                            size_hint_y=None, height=dp(292), panel_color=CARD)
        head = BoxLayout(size_hint_y=None, height=dp(28), padding=(dp(8), 0))
        head.add_widget(self.label("体重趋势", 14, TEXT, True))
        head.add_widget(Widget())
        head.add_widget(self.label("点击数据点可编辑", 10, MUTED))
        card.add_widget(head)
        self.plot = PlotWidget(size_hint_y=None, height=dp(244), on_point=self.edit_record)
        card.add_widget(self.plot)
        return card

    def toggle_today_workout(self, *_):
        self.calendar_selected_date = datetime.now().date()
        self.storage.set_workout(self.calendar_selected_date.isoformat(),
                                 not self.storage.get_workout(self.calendar_selected_date.isoformat()))
        self.refresh_home_summary()
        if getattr(self, "calendar_grid", None) is not None:
            self.render_calendar()
            self.refresh_calendar_photo_data(preferred_date=self.calendar_selected_date)
