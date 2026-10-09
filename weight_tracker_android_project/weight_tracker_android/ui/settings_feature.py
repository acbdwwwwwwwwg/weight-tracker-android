"""Settings, CSV, recycle-bin and shared dialog behavior."""

from datetime import datetime
from pathlib import Path

from kivy.metrics import dp
from kivy.core.window import Window
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView

from ui.theme import BG, FONT_NAME, MUTED, PRIMARY, TEXT

class SettingsFeatureMixin:
    """Application settings, CSV import/export, recycle-bin and dialogs."""

    def _float_setting(self, key):
        v = self.storage.get_setting(key)
        try:
            return float(v) if v else None
        except Exception:
            return None

    def ask_height(self, *_):
        self.input_setting("保存身高(cm)", self.height_cm, lambda v: self.set_height(v))

    def set_height(self, v):
        x = float(v)
        if not (x > 0 and x == x and x != float("inf") and x != float("-inf")):
            raise ValueError("身高必须是大于 0 的有限数字")
        self.height_cm = x
        self.storage.set_setting("height_cm", x)
        self.refresh()
        self.refresh_profile_summary()

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
        self.refresh_profile_summary()

    def input_setting(self, title, value, callback):
        content = BoxLayout(orientation="vertical", padding=dp(10), spacing=dp(8))
        inp = self._field(text="" if value is None else str(value))
        content.add_widget(inp)
        btn = self.button("保存", lambda *_: self._save_setting_popup(popup, inp.text, callback), 42)
        content.add_widget(btn)
        popup = Popup(title=title, title_font=FONT_NAME, content=content, size_hint=(.85, None), height=dp(170), background="", separator_color=(0, 0, 0, 0))
        popup.open()

    def _save_setting_popup(self, popup, value, callback):
        try:
            callback(value)
            popup.dismiss()
        except Exception as e:
            self.info("设置失败", str(e))

    def switch_theme(self, *_):
        # 当前版本统一使用健身深色主题，避免只切换窗口底色造成卡片与背景不一致。
        self.theme = "深色"
        self.storage.set_setting("theme", self.theme)
        Window.clearcolor = BG
        self.info("健身深色主题", "当前采用炭黑背景、圆角卡片与珊瑚红训练重点色。")

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
        popup = Popup(title="回收站", title_font=FONT_NAME, content=root, size_hint=(.95, .8), background="", separator_color=(0, 0, 0, 0))
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
        """Show a wrapped, dark-themed message dialog with a clear dismissal action."""
        from ui.theme import CARD

        body = BoxLayout(orientation="vertical", padding=(dp(16), dp(14)), spacing=dp(12))
        message_label = Label(
            text=str(message),
            color=TEXT,
            font_name=FONT_NAME,
            halign="left",
            valign="middle",
            size_hint_y=1,
        )
        message_label.bind(
            width=lambda widget, width: setattr(widget, "text_size", (max(1, width), None))
        )
        body.add_widget(message_label)

        popup = Popup(
            title=title,
            title_font=FONT_NAME,
            title_color=TEXT,
            content=body,
            size_hint=(.90, None),
            height=dp(250),
            background="atlas://data/images/defaulttheme/modalview-background",
            background_color=CARD,
            separator_color=(0, 0, 0, 0),
            auto_dismiss=True,
        )
        body.add_widget(self.button("知道了", lambda *_: popup.dismiss(), 44, tone="primary"))
        popup.open()
