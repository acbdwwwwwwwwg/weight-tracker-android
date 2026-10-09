"""Body-photo timeline page, isolated from calendar navigation and storage."""
from datetime import datetime

from kivy.clock import Clock
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.carousel import Carousel
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.widget import Widget

from ui.theme import CARD, CARD_ALT, MUTED, PRIMARY, TEXT
from ui.widgets import PhotoPage, RoundedPanel


class ProgressScreenMixin:
    def build_progress_screen(self):
        from kivy.uix.scrollview import ScrollView
        scroll = ScrollView(do_scroll_x=False, do_scroll_y=True, bar_width=dp(3),
                            scroll_type=["bars", "content"])
        content = BoxLayout(orientation="vertical", padding=(dp(12), dp(12), dp(12), dp(14)),
                            spacing=dp(10), size_hint_y=None)
        content.bind(minimum_height=content.setter("height"))

        header = RoundedPanel(orientation="vertical", padding=(dp(15), dp(12)), spacing=dp(3),
                              size_hint_y=None, height=dp(80), panel_color=CARD)
        header.add_widget(self.label("BODY TIMELINE", 10, PRIMARY, True))
        header.add_widget(self.label("体型变化", 19, TEXT, True))
        header.add_widget(self.label("按时间浏览每一次记录，左右滑动对比变化", 11, MUTED))
        content.add_widget(header)

        summary = RoundedPanel(orientation="horizontal", padding=(dp(13), dp(11)), spacing=dp(8),
                               size_hint_y=None, height=dp(78), panel_color=CARD)
        info = BoxLayout(orientation="vertical", spacing=dp(3))
        info.add_widget(self.label("我的照片时间线", 13, TEXT, True))
        self.progress_summary_label = self.label("从第一张照片开始记录变化", 10, MUTED)
        info.add_widget(self.progress_summary_label)
        summary.add_widget(info)
        summary.add_widget(Widget())
        add_btn = self.button("＋ 添加照片", self.add_body_photo, 42, tone="primary")
        add_btn.size_hint_x = None
        add_btn.width = dp(112)
        summary.add_widget(add_btn)
        content.add_widget(summary)

        carousel_card = RoundedPanel(orientation="vertical", padding=(dp(10), dp(10)), spacing=dp(7),
                                      size_hint_y=None, height=dp(460), panel_color=CARD)
        carousel_header = BoxLayout(size_hint_y=None, height=dp(28))
        carousel_header.add_widget(self.label("照片", 14, TEXT, True))
        carousel_header.add_widget(Widget())
        self.photo_date_label = self.label("暂无照片", 10, MUTED, True)
        carousel_header.add_widget(self.photo_date_label)
        carousel_card.add_widget(carousel_header)
        self.photo_carousel = Carousel(direction="left", loop=False, size_hint_y=None, height=dp(332))
        self.photo_carousel.bind(index=self.on_photo_index)
        carousel_card.add_widget(self.photo_carousel)
        self.photo_counter_label = self.label("0 张照片", 10, MUTED)
        carousel_card.add_widget(self.photo_counter_label)
        actions = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(7))
        actions.add_widget(self.button("跳到日历选中日", self.jump_to_selected_photo, 40, tone="secondary"))
        actions.add_widget(self.button("删除当前照片", self.confirm_delete_current_photo, 40, tone="secondary"))
        carousel_card.add_widget(actions)
        content.add_widget(carousel_card)

        tip = RoundedPanel(orientation="vertical", padding=(dp(12), dp(10)), spacing=dp(3),
                           size_hint_y=None, height=dp(66), panel_color=CARD_ALT)
        tip.add_widget(self.label("记录建议", 12, TEXT, True))
        tip.add_widget(self.label("尽量使用相似光线、距离和姿势拍摄，长期对比更直观。", 10, MUTED))
        content.add_widget(tip)
        scroll.add_widget(content)
        self.refresh_photo_carousel(preferred_date=getattr(self, "progress_filter_date", None))
        return scroll

    def refresh_photo_carousel(self, preferred_date=None):
        carousel = getattr(self, "photo_carousel", None)
        if carousel is None:
            return
        rows = self.storage.list_body_photos()
        self.photo_rows = rows
        self.photo_pages = []
        carousel.clear_widgets()
        if not rows:
            empty = RoundedPanel(orientation="vertical", padding=dp(18), spacing=dp(8),
                                 panel_color=CARD_ALT, corner_radius=20)
            empty.add_widget(Widget())
            empty.add_widget(self.label("还没有体型照片", 16, TEXT, True))
            empty.add_widget(self.label("添加一张今天的照片，开启自己的变化记录。", 11, MUTED))
            empty.add_widget(self.button("＋ 添加第一张照片", self.add_body_photo, 42, tone="primary"))
            empty.add_widget(Widget())
            carousel.add_widget(empty)
            self.photo_date_label.text = "暂无照片"
            self.photo_counter_label.text = "0 张照片"
            if getattr(self, "progress_summary_label", None):
                self.progress_summary_label.text = "从第一张照片开始记录变化"
            return

        target_index = 0
        preferred_index = None
        for index, row in enumerate(rows):
            page = PhotoPage(row, self.storage.body_photo_path(row))
            self.photo_pages.append(page)
            carousel.add_widget(page)
            if preferred_date and row["photo_date"] == preferred_date and preferred_index is None:
                preferred_index = index
        if preferred_index is not None:
            target_index = preferred_index
        elif preferred_date:
            for index, row in enumerate(rows):
                if row["photo_date"] >= preferred_date:
                    target_index = index
                    break
            else:
                target_index = len(rows) - 1
        carousel.index = target_index
        if hasattr(self, "photo_counter_label"):
            self.photo_counter_label.text = f"共 {len(rows)} 张 · 按日期和时间排序"
        if getattr(self, "progress_summary_label", None):
            dates = sorted({r["photo_date"] for r in rows})
            self.progress_summary_label.text = f"记录跨度 {dates[0]} — {dates[-1]} · {len(rows)} 张照片"
        Clock.schedule_once(lambda *_: self._load_photo_window(), 0)

    def _load_photo_window(self):
        if not getattr(self, "photo_pages", None) or getattr(self, "photo_carousel", None) is None:
            return
        current = int(self.photo_carousel.index)
        for index, page in enumerate(self.photo_pages):
            if abs(index - current) <= 1:
                page.load()
            else:
                page.unload()
        self._update_photo_caption()

    def on_photo_index(self, *_):
        Clock.schedule_once(lambda __: self._load_photo_window(), 0)

    def _update_photo_caption(self):
        if not getattr(self, "photo_pages", None) or getattr(self, "photo_carousel", None) is None:
            return
        index = int(self.photo_carousel.index)
        if 0 <= index < len(self.photo_pages):
            row = self.photo_pages[index].photo_row
            self.photo_date_label.text = f"{row['photo_date']} · {row['created_at'][11:16]}"
            if hasattr(self, "photo_counter_label"):
                self.photo_counter_label.text = f"第 {index + 1} / {len(self.photo_pages)} 张"

    def jump_to_selected_photo(self, *_):
        date_value = getattr(self, "calendar_selected_date", datetime.now().date()).isoformat()
        self.progress_filter_date = date_value
        if not getattr(self, "photo_rows", None):
            self.info("没有照片", f"{date_value} 暂无体型照片。添加后会显示在时间线上。")
            return
        for index, row in enumerate(self.photo_rows):
            if row["photo_date"] == date_value:
                self.photo_carousel.index = index
                self._load_photo_window()
                return
        self.info("没有当天照片", f"{date_value} 暂无照片，时间线仍保留全部历史记录。")

    def confirm_delete_current_photo(self, *_):
        if not getattr(self, "photo_pages", None) or self.photo_carousel is None:
            self.info("没有照片", "当前没有可删除的照片。")
            return
        row = self.photo_pages[int(self.photo_carousel.index)].photo_row
        content = BoxLayout(orientation="vertical", padding=dp(14), spacing=dp(10))
        content.add_widget(self.label(f"确定删除 {row['photo_date']} 的这张照片吗？", 13, TEXT))
        content.add_widget(self.label("删除前会自动创建完整备份。", 11, MUTED))
        actions = BoxLayout(size_hint_y=None, height=dp(42), spacing=dp(8))
        popup = Popup(title="删除照片", title_font="NotoSansSC", content=content,
                      size_hint=(.88, None), height=dp(170), background="",
                      separator_color=(0, 0, 0, 0))
        actions.add_widget(self.button("取消", lambda *_: popup.dismiss(), 40, tone="secondary"))
        actions.add_widget(self.button("确认删除", lambda *_: self.delete_current_photo(popup), 40, tone="primary"))
        content.add_widget(actions)
        popup.open()

    def delete_current_photo(self, confirm_popup=None):
        if not getattr(self, "photo_pages", None) or self.photo_carousel is None:
            if confirm_popup:
                confirm_popup.dismiss()
            return
        index = int(self.photo_carousel.index)
        if index < 0 or index >= len(self.photo_pages):
            if confirm_popup:
                confirm_popup.dismiss()
            return
        row = self.photo_pages[index].photo_row
        try:
            self.storage.create_full_backup()
            self.storage.delete_body_photo(row["id"])
            if confirm_popup:
                confirm_popup.dismiss()
            self.refresh_calendar_photo_data(preferred_date=getattr(self, "calendar_selected_date", datetime.now().date()))
            if getattr(self, "calendar_grid", None) is not None:
                self.render_calendar()
            self.refresh_photo_carousel(preferred_date=self.progress_filter_date or row["photo_date"])
            self.info("已删除照片", "照片已从时间线移除，原图已随删除前备份保留。")
        except Exception as exc:
            if confirm_popup:
                confirm_popup.dismiss()
            self.info("删除照片失败", str(exc))
