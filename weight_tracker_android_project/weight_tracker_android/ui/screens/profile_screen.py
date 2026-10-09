"""Profile and data-management screen. Low-frequency settings live here."""
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.scrollview import ScrollView
from kivy.uix.widget import Widget

from ui.theme import CARD, CARD_ALT, GREEN, FONT_NAME, MUTED, PRIMARY, PURPLE, TEXT
from ui.widgets import RoundedPanel


class ProfileScreenMixin:
    def build_profile_screen(self):
        scroll = ScrollView(do_scroll_x=False, do_scroll_y=True, bar_width=dp(3),
                            scroll_type=["bars", "content"])
        content = BoxLayout(orientation="vertical", padding=(dp(12), dp(12), dp(12), dp(14)),
                            spacing=dp(10), size_hint_y=None)
        content.bind(minimum_height=content.setter("height"))

        header = RoundedPanel(orientation="vertical", padding=(dp(15), dp(12)), spacing=dp(3),
                              size_hint_y=None, height=dp(82), panel_color=CARD)
        header.add_widget(self.label("MY FITNESS", 10, PRIMARY, True))
        header.add_widget(self.label("我的 · 设置与数据", 19, TEXT, True))
        header.add_widget(self.label("目标、统计偏好、导入导出与备份", 11, MUTED))
        content.add_widget(header)

        goal = RoundedPanel(orientation="vertical", padding=(dp(13), dp(12)), spacing=dp(9),
                            size_hint_y=None, height=dp(164), panel_color=CARD)
        goal.add_widget(self.label("个人目标", 14, TEXT, True))
        values = GridLayout(cols=2, spacing=dp(8), size_hint_y=None, height=dp(58))
        self.profile_height_value = self.label("未设置身高", 13, MUTED, True)
        self.profile_target_value = self.label("未设置目标", 13, MUTED, True)
        for title, value in (("身高", self.profile_height_value), ("目标体重", self.profile_target_value)):
            tile = RoundedPanel(orientation="vertical", padding=(dp(9), dp(5)), spacing=dp(2),
                                panel_color=CARD_ALT, corner_radius=14)
            tile.add_widget(self.label(title, 10, MUTED))
            tile.add_widget(value)
            values.add_widget(tile)
        goal.add_widget(values)
        actions = BoxLayout(size_hint_y=None, height=dp(38), spacing=dp(7))
        actions.add_widget(self.button("设置身高", self.ask_height, 38, tone="secondary"))
        actions.add_widget(self.button("设置目标", self.ask_target, 38, tone="secondary"))
        goal.add_widget(actions)
        content.add_widget(goal)

        view_card = RoundedPanel(orientation="vertical", padding=(dp(13), dp(11)), spacing=dp(7),
                                 size_hint_y=None, height=dp(138), panel_color=CARD)
        view_card.add_widget(self.label("统计偏好", 14, TEXT, True))
        period_row = BoxLayout(size_hint_y=None, height=dp(39), spacing=dp(8))
        period_row.add_widget(self.label("统计范围", 12, MUTED))
        period_row.add_widget(Widget())
        from kivy.uix.spinner import Spinner, SpinnerOption
        self.days_spinner = Spinner(
            text=str(self.window_days), values=[str(i) for i in (7, 14, 30, 60, 90, 180, 365)],
            size_hint_x=None, width=dp(82), font_name=FONT_NAME, option_cls=SpinnerOption,
            background_normal="", background_color=CARD_ALT, color=TEXT, font_size=dp(13),
        )
        self.days_spinner.bind(text=self.change_days)
        period_row.add_widget(self.days_spinner)
        view_card.add_widget(period_row)
        toggles = BoxLayout(size_hint_y=None, height=dp(34), spacing=dp(8))
        from kivy.uix.checkbox import CheckBox
        self.bmi_cb = CheckBox(active=False, size_hint_x=None, width=dp(28))
        self.bmi_cb.bind(active=lambda _, value: self.toggle_bmi(value))
        toggles.add_widget(self.bmi_cb)
        toggles.add_widget(self.label("显示 BMI", 12, TEXT))
        self.labels_cb = CheckBox(active=False, size_hint_x=None, width=dp(28))
        self.labels_cb.bind(active=lambda _, value: self.toggle_labels(value))
        toggles.add_widget(self.labels_cb)
        toggles.add_widget(self.label("显示图表数值", 12, TEXT))
        view_card.add_widget(toggles)
        content.add_widget(view_card)

        data_card = RoundedPanel(orientation="vertical", padding=(dp(13), dp(12)), spacing=dp(8),
                                 size_hint_y=None, height=dp(246), panel_color=CARD)
        data_card.add_widget(self.label("数据管理", 14, TEXT, True))
        data_card.add_widget(self.label("导出记录、恢复误删数据，或把数据库与体型照片一起备份。", 11, MUTED))
        row1 = BoxLayout(size_hint_y=None, height=dp(42), spacing=dp(7))
        row1.add_widget(self.button("导出 CSV", self.export_csv, 42, tone="secondary"))
        row1.add_widget(self.button("导入 CSV", self.import_csv, 42, tone="secondary"))
        data_card.add_widget(row1)
        row2 = BoxLayout(size_hint_y=None, height=dp(42), spacing=dp(7))
        row2.add_widget(self.button("打开回收站", self.open_recycle, 42, tone="secondary"))
        row2.add_widget(self.button("完整备份", self.full_backup, 42, tone="primary"))
        data_card.add_widget(row2)
        theme_row = BoxLayout(size_hint_y=None, height=dp(30), spacing=dp(7))
        theme_row.add_widget(self.label("外观", 12, MUTED))
        theme_row.add_widget(Widget())
        theme_row.add_widget(self.label("健身深色主题 · 已启用", 11, GREEN, True))
        data_card.add_widget(theme_row)
        content.add_widget(data_card)

        about = RoundedPanel(orientation="vertical", padding=(dp(13), dp(11)), spacing=dp(4),
                             size_hint_y=None, height=dp(66), panel_color=CARD)
        about.add_widget(self.label("体重追踪助手", 12, TEXT, True))
        about.add_widget(self.label("数据默认保存在本机应用目录；记得定期创建完整备份。", 10, MUTED))
        content.add_widget(about)
        scroll.add_widget(content)
        return scroll

    def refresh_profile_summary(self):
        if hasattr(self, "profile_height_value"):
            self.profile_height_value.text = f"{self.height_cm:g} cm" if self.height_cm else "未设置身高"
        if hasattr(self, "profile_target_value"):
            self.profile_target_value.text = f"{self.target_weight:g} 斤" if self.target_weight else "未设置目标"
