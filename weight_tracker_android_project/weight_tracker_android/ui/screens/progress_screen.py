"""Body-photo timeline page, isolated from calendar navigation and storage."""
from datetime import datetime
import os
from threading import Thread

from kivy.clock import Clock
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.carousel import Carousel
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.widget import Widget

from ui.theme import CARD, CARD_ALT, MUTED, PRIMARY, TEXT
from services.android_bridge import IS_ANDROID, create_photo_thumbnail
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
        # Navigation owns first render/refresh; keeping builders side-effect free
        # prevents duplicate full-list queries and duplicate page creation.
        return scroll

    def refresh_photo_carousel(self, preferred_date=None):
        """Load metadata and create only a three-page sliding window."""
        carousel = getattr(self, "photo_carousel", None)
        if carousel is None:
            return
        rows = self.storage.list_body_photos()
        self.photo_rows = rows
        for old_page in getattr(self, "photo_pages", []):
            old_page.unload()
        self.photo_pages = []
        self._photo_rebuilding = True
        try:
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
                self._photo_window_start = 0
                self._photo_current_index = 0
                self.photo_date_label.text = "暂无照片"
                self.photo_counter_label.text = "0 张照片"
                if getattr(self, "progress_summary_label", None):
                    self.progress_summary_label.text = "从第一张照片开始记录变化"
                return

            target_index = 0
            exact = next((i for i, row in enumerate(rows) if preferred_date and row["photo_date"] == preferred_date), None)
            if exact is not None:
                target_index = exact
            elif preferred_date:
                later = next((i for i, row in enumerate(rows) if row["photo_date"] >= preferred_date), None)
                target_index = later if later is not None else len(rows) - 1
            self._photo_current_index = target_index
            self._build_photo_window(target_index)
            if hasattr(self, "photo_counter_label"):
                self.photo_counter_label.text = f"共 {len(rows)} 张 · 按日期和时间排序"
            if getattr(self, "progress_summary_label", None):
                self.progress_summary_label.text = f"记录跨度 {rows[0]['photo_date']} — {rows[-1]['photo_date']} · {len(rows)} 张照片"
        finally:
            self._photo_rebuilding = False
        Clock.schedule_once(lambda *_: self._load_photo_window(), 0)

    def _build_photo_window(self, center_index):
        """Rebase Carousel around the current photo; widget count stays <= 3."""
        carousel = self.photo_carousel
        total = len(self.photo_rows)
        if total <= 3:
            start = 0
        else:
            start = max(0, min(int(center_index) - 1, total - 3))
        end = min(total, start + 3)
        self._photo_window_start = start
        for old_page in getattr(self, "photo_pages", []):
            old_page.unload()
        self.photo_pages = []
        carousel.clear_widgets()
        for absolute_index in range(start, end):
            row = self.photo_rows[absolute_index]
            original = self.storage.body_photo_path(row)
            thumb = self.storage.body_photo_thumbnail_path(row)
            page = PhotoPage(row, thumb if thumb.exists() else None, original_path=original)
            self.photo_pages.append(page)
            carousel.add_widget(page)
        self._photo_rebuilding = True
        try:
            carousel.index = int(center_index) - start
        finally:
            self._photo_rebuilding = False

    def _load_photo_window(self):
        if not getattr(self, "photo_pages", None) or getattr(self, "photo_carousel", None) is None:
            return
        current = max(0, min(int(self.photo_carousel.index), len(self.photo_pages) - 1))
        for index, page in enumerate(self.photo_pages):
            if abs(index - current) <= 1:
                page.load()
                if not page.photo_path or not page.photo_path.exists():
                    self._generate_missing_thumbnail(page)
            else:
                page.unload()
        self._update_photo_caption()

    def _generate_missing_thumbnail(self, page):
        if not IS_ANDROID:
            page.photo_path = page.original_path
            page.load()
            return
        if not page.original_path or not page.original_path.exists():
            page.photo_path = None
            page.preview_status.text = "原图文件不存在"
            page.load()
            return
        photo_id = int(page.photo_row["id"])
        jobs = getattr(self, "_thumbnail_jobs", None)
        if jobs is None:
            self._thumbnail_jobs = set()
            jobs = self._thumbnail_jobs
        if photo_id in jobs:
            return
        if photo_id in getattr(self, "_thumbnail_failed_ids", set()):
            page.preview_status.text = "预览生成失败，原图仍已保存"
            return
        jobs.add(photo_id)
        original = page.original_path
        thumb = self.storage.body_photo_thumbnail_dir / f"{photo_id}.jpg"
        temp = thumb.with_suffix(".jpg.part")
        storage = self.storage

        def worker():
            try:
                create_photo_thumbnail(original, temp, max_dimension=640, quality=82)
                os.replace(temp, thumb)
                storage.set_body_photo_thumbnail(photo_id, thumb)
                def done(_dt):
                    jobs.discard(photo_id)
                    if getattr(self, "current_screen", None) == "progress" and page in getattr(self, "photo_pages", []):
                        page.photo_path = thumb
                        page.load()
                Clock.schedule_once(done, 0)
            except Exception:
                try:
                    temp.unlink()
                except OSError:
                    pass
                def failed(_dt):
                    jobs.discard(photo_id)
                    failed_ids = getattr(self, "_thumbnail_failed_ids", None)
                    if failed_ids is not None:
                        failed_ids.add(photo_id)
                    # Never decode a full-resolution legacy original on the UI thread.
                    # Keep the record and expose a clear preview state instead.
                    if getattr(self, "current_screen", None) == "progress" and page in getattr(self, "photo_pages", []):
                        page.photo_path = None
                        page.preview_status.text = "预览生成失败，原图仍已保存"
                        page.load()
                Clock.schedule_once(failed, 0)
        Thread(target=worker, name=f"photo-thumb-{photo_id}", daemon=True).start()

    def on_photo_index(self, _carousel, new_index):
        if getattr(self, "_photo_rebuilding", False) or not getattr(self, "photo_pages", None):
            return
        local = max(0, min(int(new_index), len(self.photo_pages) - 1))
        absolute = self._photo_window_start + local
        self._photo_current_index = absolute
        # Recenter only when a swipe reaches either end of the three-page window.
        # Directly assigning the central index after rebuild avoids growing a huge Carousel.
        if len(self.photo_rows) > 3 and local in (0, len(self.photo_pages) - 1):
            if (local == 0 and absolute > 0) or (local == len(self.photo_pages) - 1 and absolute < len(self.photo_rows) - 1):
                # Let the Carousel finish its swipe animation before rebasing the window.
                Clock.schedule_once(lambda *_args, i=absolute: self._recenter_photo_window(i), 0.24)
                return
        Clock.schedule_once(lambda *_: self._load_photo_window(), 0)

    def _recenter_photo_window(self, absolute_index):
        if not self.photo_rows or self.photo_carousel is None:
            return
        self._photo_rebuilding = True
        try:
            self._photo_current_index = max(0, min(int(absolute_index), len(self.photo_rows) - 1))
            self._build_photo_window(self._photo_current_index)
        finally:
            self._photo_rebuilding = False
        Clock.schedule_once(lambda *_: self._load_photo_window(), 0)

    def _update_photo_caption(self):
        if not getattr(self, "photo_pages", None) or getattr(self, "photo_carousel", None) is None:
            return
        local = max(0, min(int(self.photo_carousel.index), len(self.photo_pages) - 1))
        absolute = min(len(self.photo_rows) - 1, self._photo_window_start + local)
        row = self.photo_rows[absolute]
        self.photo_date_label.text = f"{row['photo_date']} · {row['created_at'][11:16]}"
        if hasattr(self, "photo_counter_label"):
            self.photo_counter_label.text = f"第 {absolute + 1} / {len(self.photo_rows)} 张"

    def jump_to_selected_photo(self, *_):
        date_value = getattr(self, "calendar_selected_date", datetime.now().date()).isoformat()
        self.progress_filter_date = date_value
        if not getattr(self, "photo_rows", None):
            self.info("没有照片", f"{date_value} 暂无体型照片。添加后会显示在时间线上。")
            return
        for index, row in enumerate(self.photo_rows):
            if row["photo_date"] == date_value:
                self._recenter_photo_window(index)
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
        local = max(0, min(int(self.photo_carousel.index), len(self.photo_pages) - 1))
        absolute = min(len(self.photo_rows) - 1, self._photo_window_start + local)
        if absolute < 0:
            if confirm_popup:
                confirm_popup.dismiss()
            return
        row = self.photo_rows[absolute]
        photo_id = int(row["id"])
        date_to_show = self.progress_filter_date or row["photo_date"]
        storage = self.storage
        if confirm_popup:
            confirm_popup.dismiss()

        def worker():
            # Keep deletion atomic from the user's perspective: do not delete if backup fails.
            backup_path = storage.create_full_backup()
            if backup_path is None:
                raise RuntimeError("无法创建删除前备份，因此照片没有被删除。")
            storage.delete_body_photo(photo_id)
            return {"backup": str(backup_path), "date": row["photo_date"]}

        def complete(_result):
            if getattr(self, "_calendar_total_photo_count", None) is not None:
                self._calendar_total_photo_count = max(0, self._calendar_total_photo_count - 1)
            self._calendar_cache_month = None
            if getattr(self, "calendar_grid", None) is not None:
                self.render_calendar()
            self.refresh_calendar_photo_data(preferred_date=getattr(self, "calendar_selected_date", datetime.now().date()))
            self.refresh_photo_carousel(preferred_date=date_to_show)
            self.refresh_home_summary()
            self.info("已删除照片", "照片已从时间线移除，删除前的完整备份已保存。")

        self.run_background_task("正在备份并删除照片", worker, on_success=complete)

