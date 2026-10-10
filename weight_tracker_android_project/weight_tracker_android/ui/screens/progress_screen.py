"""Single-image body-photo browser, reusable timeline, and separate comparison mode."""
from datetime import datetime
from pathlib import Path
import os
from threading import Thread
from time import perf_counter

from kivy.clock import Clock
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.image import Image
from kivy.uix.popup import Popup
from kivy.uix.recycleview import RecycleView
from kivy.uix.recycleboxlayout import RecycleBoxLayout
from kivy.factory import Factory
from kivy.uix.widget import Widget

from services.android_bridge import IS_ANDROID, create_photo_thumbnail
from services.photo_cache import PhotoImageCache, proxy_texture
from services.performance import mark
from ui.theme import CARD, CARD_ALT, CARD_DARK, MUTED, PRIMARY, TEXT
from ui.widgets import PhotoSwipeSurface, PhotoThumbnailTile, RoundedPanel

if "PhotoThumbnailTile" not in Factory.classes:
    Factory.register("PhotoThumbnailTile", cls=PhotoThumbnailTile)


class ProgressScreenMixin:
    """Build and maintain the photo gallery without rebuilding pages on swipes."""

    PHOTO_CACHE_CAPACITY = 5

    def build_progress_screen(self):
        from kivy.uix.scrollview import ScrollView

        scroll = ScrollView(do_scroll_x=False, do_scroll_y=True, bar_width=dp(3),
                            scroll_type=["bars", "content"])
        content = BoxLayout(orientation="vertical", padding=(dp(14), dp(14), dp(14), dp(16)),
                            spacing=dp(12), size_hint_y=None)
        content.bind(minimum_height=content.setter("height"))

        header = RoundedPanel(orientation="vertical", padding=(dp(16), dp(13)), spacing=dp(4),
                              size_hint_y=None, height=dp(82), panel_color=CARD)
        header.add_widget(self.label("BODY TIMELINE", 10, PRIMARY, True))
        header.add_widget(self.label("体型变化", 19, TEXT, True))
        header.add_widget(self.label("单图快速浏览 · 时间线定位 · 独立前后对比", 11, MUTED))
        content.add_widget(header)

        summary = RoundedPanel(orientation="horizontal", padding=(dp(14), dp(12)), spacing=dp(9),
                               size_hint_y=None, height=dp(80), panel_color=CARD)
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

        mode_row = BoxLayout(orientation="horizontal", spacing=dp(7), size_hint_y=None, height=dp(42))
        self.photo_browse_mode_button = self.button("照片浏览", self.show_photo_browser, 42, tone="primary")
        self.photo_compare_mode_button = self.button("前后对比", self.show_photo_comparison, 42, tone="secondary")
        mode_row.add_widget(self.photo_browse_mode_button)
        mode_row.add_widget(self.photo_compare_mode_button)
        content.add_widget(mode_row)

        self.photo_mode_host = BoxLayout(orientation="vertical", size_hint_y=None, height=dp(660))
        self.photo_browser_panel = self._build_photo_browser_panel()
        self.photo_compare_panel = self._build_photo_compare_panel()
        self.photo_mode_host.add_widget(self.photo_browser_panel)
        content.add_widget(self.photo_mode_host)
        # Kept as a stable non-None compatibility handle for add/restore flows;
        # this is now a single-image browser with a recycled thumbnail timeline.
        self.photo_browser_card = self.photo_mode_host

        tip = RoundedPanel(orientation="vertical", padding=(dp(12), dp(10)), spacing=dp(3),
                           size_hint_y=None, height=dp(66), panel_color=CARD_ALT)
        tip.add_widget(self.label("记录建议", 12, TEXT, True))
        tip.add_widget(self.label("尽量使用相似光线、距离和姿势拍摄，长期对比更直观。", 10, MUTED))
        content.add_widget(tip)
        scroll.add_widget(content)

        self._photo_image_cache = PhotoImageCache(self.PHOTO_CACHE_CAPACITY)
        self._photo_rows_refresh_token = 0
        self._main_image_request_token = 0
        self._compare_request_tokens = {"before": 0, "after": 0}
        self._thumbnail_jobs = getattr(self, "_thumbnail_jobs", set())
        self._thumbnail_failed_ids = getattr(self, "_thumbnail_failed_ids", set())
        self._photo_current_index = max(0, int(getattr(self, "_photo_current_index", 0)))
        self._photo_mode = "browse"
        self._compare_before_index = getattr(self, "_compare_before_index", None)
        self._compare_after_index = getattr(self, "_compare_after_index", None)
        return scroll

    def _build_photo_browser_panel(self):
        panel = BoxLayout(orientation="vertical", spacing=dp(8), size_hint_y=None, height=dp(660))

        photo_card = RoundedPanel(orientation="vertical", padding=(dp(10), dp(9)), spacing=dp(5),
                                  size_hint_y=None, height=dp(450), panel_color=CARD)
        top = BoxLayout(size_hint_y=None, height=dp(26), spacing=dp(5))
        top.add_widget(self.label("照片预览", 13, TEXT, True))
        top.add_widget(Widget())
        self.photo_date_label = self.label("暂无照片", 10, MUTED, True)
        top.add_widget(self.photo_date_label)
        photo_card.add_widget(top)

        self.main_photo_image = Image(source="", allow_stretch=True, keep_ratio=True,
                                      size_hint=(1, 1), pos_hint={"x": 0, "y": 0})
        self.main_photo_surface = PhotoSwipeSurface(on_swipe=self._on_photo_swipe,
                                                    min_distance_dp=24,
                                                    size_hint_y=None, height=dp(276))
        self.main_photo_surface.add_widget(self.main_photo_image)
        photo_card.add_widget(self.main_photo_surface)
        self.photo_status_label = self.label("添加一张照片，开启自己的变化记录", 10, MUTED)
        self.photo_status_label.size_hint_y = None
        self.photo_status_label.height = dp(18)
        photo_card.add_widget(self.photo_status_label)

        controls = BoxLayout(size_hint_y=None, height=dp(42), spacing=dp(8))
        self.photo_previous_button = self.button("‹ 上一张", lambda *_: self.show_photo_index(self._photo_current_index - 1),
                                                 42, tone="secondary")
        self.photo_counter_label = self.label("0 张照片", 11, TEXT, True)
        self.photo_next_button = self.button("下一张 ›", lambda *_: self.show_photo_index(self._photo_current_index + 1),
                                             42, tone="secondary")
        controls.add_widget(self.photo_previous_button)
        controls.add_widget(self.photo_counter_label)
        controls.add_widget(self.photo_next_button)
        photo_card.add_widget(controls)

        select_row = BoxLayout(size_hint_y=None, height=dp(42), spacing=dp(8))
        select_row.add_widget(self.button("设为前期", lambda *_: self.set_compare_anchor("before"), 42, tone="soft"))
        select_row.add_widget(self.button("设为后期", lambda *_: self.set_compare_anchor("after"), 42, tone="soft"))
        photo_card.add_widget(select_row)
        panel.add_widget(photo_card)

        timeline = RoundedPanel(orientation="vertical", padding=(dp(9), dp(7)), spacing=dp(4),
                                size_hint_y=None, height=dp(132), panel_color=CARD)
        timeline_header = BoxLayout(size_hint_y=None, height=dp(20))
        timeline_header.add_widget(self.label("时间线 · 点击缩略图直接跳转", 11, TEXT, True))
        self.photo_selection_hint = self.label("选择前期和后期照片", 9, MUTED)
        timeline_header.add_widget(self.photo_selection_hint)
        timeline.add_widget(timeline_header)
        self.photo_thumbnail_view = RecycleView(size_hint_y=None, height=dp(88),
                                                do_scroll_x=True, do_scroll_y=False,
                                                scroll_type=["bars", "content"], bar_width=dp(2))
        self.photo_thumbnail_view.viewclass = "PhotoThumbnailTile"
        self.photo_thumbnail_layout = RecycleBoxLayout(
            orientation="horizontal", spacing=dp(6), padding=(dp(2), dp(1)),
            default_size=(dp(76), dp(86)), default_size_hint=(None, None),
            size_hint=(None, None), height=dp(86),
        )
        self.photo_thumbnail_layout.bind(minimum_width=self.photo_thumbnail_layout.setter("width"))
        self.photo_thumbnail_view.add_widget(self.photo_thumbnail_layout)
        timeline.add_widget(self.photo_thumbnail_view)
        panel.add_widget(timeline)

        actions = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(8))
        actions.add_widget(self.button("跳到日历选中日", self.jump_to_selected_photo, 44, tone="secondary"))
        actions.add_widget(self.button("删除当前照片", self.confirm_delete_current_photo, 44, tone="secondary"))
        panel.add_widget(actions)
        return panel

    def _build_photo_compare_panel(self):
        panel = RoundedPanel(orientation="vertical", padding=(dp(10), dp(9)), spacing=dp(7),
                             size_hint_y=None, height=dp(550), panel_color=CARD)
        head = BoxLayout(size_hint_y=None, height=dp(42), spacing=dp(7))
        head.add_widget(self.label("前后变化对比", 14, TEXT, True))
        head.add_widget(Widget())
        head.add_widget(self.button("交换前后", self.swap_compare_photos, 40, tone="soft"))
        panel.add_widget(head)
        panel.add_widget(self._build_compare_side("before"))
        panel.add_widget(self._build_compare_side("after"))
        footer = BoxLayout(size_hint_y=None, height=dp(42), spacing=dp(8))
        footer.add_widget(self.button("返回照片浏览", self.show_photo_browser, 42, tone="primary"))
        panel.add_widget(footer)
        return panel

    def _build_compare_side(self, side):
        side_label = "前期" if side == "before" else "后期"
        card = RoundedPanel(orientation="vertical", padding=(dp(8), dp(6)), spacing=dp(3),
                            size_hint_y=None, height=dp(210), panel_color=CARD_DARK, corner_radius=12)
        header = BoxLayout(size_hint_y=None, height=dp(42), spacing=dp(6))
        header.add_widget(self.button("‹", lambda *_args, s=side: self.step_compare_photo(s, -1), 38, tone="soft"))
        date_label = self.label(f"{side_label}照片", 10, TEXT, True)
        header.add_widget(date_label)
        header.add_widget(self.button("›", lambda *_args, s=side: self.step_compare_photo(s, 1), 38, tone="soft"))
        card.add_widget(header)

        image = Image(source="", allow_stretch=True, keep_ratio=True,
                      size_hint=(1, 1))
        card.add_widget(image)
        status = self.label("选择要对比的照片", 9, MUTED)
        status.size_hint_y = None
        status.height = dp(16)
        card.add_widget(status)

        if side == "before":
            self.compare_before_date_label = date_label
            self.compare_before_image = image
            self.compare_before_status = status
        else:
            self.compare_after_date_label = date_label
            self.compare_after_image = image
            self.compare_after_status = status
        return card

    def refresh_photo_browser(self, preferred_date=None):
        """Refresh photo metadata asynchronously; existing widgets stay alive."""
        if getattr(self, "photo_browser_card", None) is None:
            return
        self._photo_rows_refresh_token = getattr(self, "_photo_rows_refresh_token", 0) + 1
        token = self._photo_rows_refresh_token
        storage = self.storage
        mark("photo_metadata_query_start")

        def worker():
            query_started = perf_counter()
            try:
                rows = storage.list_body_photos()
                thumb_sources = {}
                original_sources = {}
                for row in rows:
                    photo_id = int(row["id"])
                    try:
                        thumb_path = storage.body_photo_thumbnail_path(row)
                        if thumb_path.exists():
                            thumb_sources[photo_id] = str(thumb_path)
                        elif not IS_ANDROID:
                            original_path = storage.body_photo_path(row)
                            if original_path.exists():
                                thumb_sources[photo_id] = str(original_path)
                    except (OSError, ValueError):
                        pass
                    try:
                        original_path = storage.body_photo_path(row)
                        if original_path.exists():
                            original_sources[photo_id] = str(original_path)
                    except (OSError, ValueError):
                        pass
                mark("photo_metadata_query_complete", query_started, rows=len(rows))
            except Exception as exc:
                Clock.schedule_once(lambda _dt, err=exc: self._photo_rows_failed(token, err), 0)
                return
            Clock.schedule_once(
                lambda _dt: self._apply_photo_rows(rows, preferred_date, token, thumb_sources, original_sources), 0
            )

        Thread(target=worker, name="photo-metadata-query", daemon=True).start()

    def _photo_rows_failed(self, token, error):
        if token != self._photo_rows_refresh_token:
            return
        self.photo_status_label.text = f"读取照片记录失败：{error}"
        self.photo_status_label.opacity = 1

    def invalidate_photo_browser_cache(self):
        """Drop cached textures after restore replaces files at existing paths."""
        cache = getattr(self, "_photo_image_cache", None)
        if cache is not None:
            cache.clear()
        self._main_image_request_token = getattr(self, "_main_image_request_token", 0) + 1
        tokens = getattr(self, "_compare_request_tokens", None)
        if tokens is not None:
            tokens["before"] += 1
            tokens["after"] += 1
        self._photo_loaded_path = None
        for widget_name in ("main_photo_image", "compare_before_image", "compare_after_image"):
            widget = getattr(self, widget_name, None)
            if widget is not None:
                widget.texture = None

    def _apply_photo_rows(self, rows, preferred_date, token, thumb_sources=None, original_sources=None):
        if token != self._photo_rows_refresh_token:
            return
        started = perf_counter()
        old_rows = getattr(self, "photo_rows", [])
        old_index = max(0, int(getattr(self, "_photo_current_index", 0)))
        old_id = old_rows[old_index]["id"] if old_rows and old_index < len(old_rows) else None
        old_before_id = (old_rows[self._compare_before_index]["id"]
                         if old_rows and self._compare_before_index is not None and
                         0 <= self._compare_before_index < len(old_rows) else None)
        old_after_id = (old_rows[self._compare_after_index]["id"]
                        if old_rows and self._compare_after_index is not None and
                        0 <= self._compare_after_index < len(old_rows) else None)
        preferred = preferred_date.isoformat() if hasattr(preferred_date, "isoformat") else preferred_date
        self._main_image_request_token += 1
        self.photo_rows = list(rows)
        self._photo_thumb_sources = dict(thumb_sources or {})
        self._photo_original_sources = dict(original_sources or {})

        if not self.photo_rows:
            self._photo_thumb_sources.clear()
            self._photo_original_sources.clear()
            self._photo_current_index = 0
            self._compare_before_index = self._compare_after_index = None
            self.main_photo_image.texture = None
            self.compare_before_image.texture = None
            self.compare_after_image.texture = None
            self._photo_loaded_path = None
            self.photo_status_label.text = "还没有体型照片，点击上方按钮添加第一张。"
            self.photo_status_label.opacity = 1
            self.photo_date_label.text = "暂无照片"
            self.photo_counter_label.text = "0 张照片"
            self.progress_summary_label.text = "从第一张照片开始记录变化"
            self.photo_thumbnail_view.data = []
            self.photo_previous_button.disabled = True
            self.photo_next_button.disabled = True
            self._update_compare_selection_hint()
            if self._photo_mode == "compare":
                self.show_photo_browser()
            mark("photo_metadata_applied", started)
            return

        target = None
        if preferred:
            target = next((i for i, row in enumerate(self.photo_rows)
                           if row["photo_date"] == str(preferred)), None)
            if target is None:
                target = next((i for i, row in enumerate(self.photo_rows)
                               if row["photo_date"] >= str(preferred)), None)
                if target is None:
                    target = len(self.photo_rows) - 1
        if target is None and old_id is not None:
            target = next((i for i, row in enumerate(self.photo_rows) if row["id"] == old_id), None)
        if target is None:
            target = min(old_index, len(self.photo_rows) - 1)
        self._photo_current_index = target

        if old_before_id is not None:
            self._compare_before_index = next(
                (i for i, row in enumerate(self.photo_rows) if row["id"] == old_before_id), None
            )
        if self._compare_before_index is None or self._compare_before_index >= len(self.photo_rows):
            self._compare_before_index = max(0, target - 1)
        if old_after_id is not None:
            self._compare_after_index = next(
                (i for i, row in enumerate(self.photo_rows) if row["id"] == old_after_id), None
            )
        if self._compare_after_index is None or self._compare_after_index >= len(self.photo_rows):
            self._compare_after_index = target

        first_date = self.photo_rows[0]["photo_date"]
        last_date = self.photo_rows[-1]["photo_date"]
        self.progress_summary_label.text = f"记录跨度 {first_date} — {last_date} · 共 {len(self.photo_rows)} 张"
        self._refresh_thumbnail_data()
        self._show_photo_index(target, scroll_thumbnail=True)
        self._update_compare_selection_hint()
        if getattr(self, "_photo_mode", "browse") == "compare":
            self._render_compare_side("before")
            self._render_compare_side("after")
        mark("photo_metadata_applied", started)

    def _thumbnail_source(self, row):
        # All filesystem existence checks are performed by refresh worker. The UI
        # thread only does an O(1) dictionary lookup while binding 100s of tiles.
        source = getattr(self, "_photo_thumb_sources", {}).get(int(row["id"]), "")
        return str(source) if source else ""

    def _original_source(self, row):
        source = getattr(self, "_photo_original_sources", {}).get(int(row["id"]))
        return Path(source) if source else None

    def _refresh_thumbnail_data(self):
        callback = self.show_photo_index
        selection_provider = self._is_photo_selected
        data = []
        for index, row in enumerate(getattr(self, "photo_rows", [])):
            data.append({
                "photo_index": index,
                "source": self._thumbnail_source(row),
                "caption": row["photo_date"][5:],
                "on_select": callback,
                "selection_provider": selection_provider,
            })
        self.photo_thumbnail_view.data = data
        Clock.schedule_once(lambda _dt, i=self._photo_current_index: self._ensure_thumbnail_visible(i), 0)

    def _is_photo_selected(self, index):
        return int(index) == int(getattr(self, "_photo_current_index", -1))

    def _update_selected_thumbnail(self):
        layout = getattr(self, "photo_thumbnail_layout", None)
        if layout is None:
            return
        for tile in tuple(layout.children):
            if hasattr(tile, "photo_index"):
                tile.selected = int(tile.photo_index) == int(self._photo_current_index)

    def _ensure_thumbnail_visible(self, index):
        rows = getattr(self, "photo_rows", [])
        rv = getattr(self, "photo_thumbnail_view", None)
        layout = getattr(self, "photo_thumbnail_layout", None)
        if not rows or rv is None or layout is None or rv.width <= 0:
            return
        index = max(0, min(int(index), len(rows) - 1))
        for tile in tuple(layout.children):
            if getattr(tile, "photo_index", -1) == index and tile.x >= rv.x and tile.right <= rv.right:
                return
        content_width = max(0, float(layout.width) - float(rv.width))
        if content_width <= 0:
            return
        item_width = dp(82)
        left = max(0, index * item_width - dp(10))
        rv.scroll_x = max(0.0, min(1.0, left / content_width))

    def _show_photo_index(self, index, scroll_thumbnail=False):
        selection_started = perf_counter()
        rows = getattr(self, "photo_rows", [])
        if not rows:
            self.photo_counter_label.text = "0 张照片"
            self.photo_date_label.text = "暂无照片"
            return
        index = max(0, min(int(index), len(rows) - 1))
        self._photo_current_index = index
        row = rows[index]
        created = str(row.get("created_at", ""))
        when = created[11:16] if len(created) >= 16 else ""
        self.photo_date_label.text = f"{row['photo_date']} · {when}"
        self.photo_counter_label.text = f"第 {index + 1} / {len(rows)} 张"
        self.photo_previous_button.disabled = index <= 0
        self.photo_next_button.disabled = index >= len(rows) - 1
        self._update_selected_thumbnail()
        if scroll_thumbnail:
            Clock.schedule_once(lambda _dt, i=index: self._ensure_thumbnail_visible(i), 0)
        mark("photo_selection_ui_updated", selection_started, index=index)

        row_id = int(row["id"])
        self._main_image_request_token += 1
        request_token = self._main_image_request_token
        path = self._thumbnail_source(row)
        if not path:
            original_path = self._original_source(row)
            if IS_ANDROID and original_path:
                # Never show the previous photo under the newly selected date.
                # A legacy thumbnail is generated in the background and replaces
                # this placeholder when ready.
                self.main_photo_image.texture = None
                self._photo_loaded_path = None
                if row_id in self._thumbnail_failed_ids:
                    self.photo_status_label.text = "预览生成失败，原图仍已保存"
                else:
                    self.photo_status_label.text = "正在准备这张照片的预览…"
                    self._generate_missing_thumbnail(row_id)
                self.photo_status_label.opacity = 1
            else:
                self.main_photo_image.texture = None
                self._photo_loaded_path = None
                self.photo_status_label.text = "原图不存在或预览不可用"
                self.photo_status_label.opacity = 1
            self._prefetch_photo_neighbors(index)
            return

        if getattr(self, "_photo_loaded_path", None) == path and self.main_photo_image.texture is not None:
            self.photo_status_label.text = ""
            self.photo_status_label.opacity = 0
            self._prefetch_photo_neighbors(index)
            return

        self.photo_status_label.text = "正在载入预览…" if self.main_photo_image.texture is None else "切换中…"
        self.photo_status_label.opacity = 1
        texture_request_started = perf_counter()

        def loaded(proxy):
            if request_token != self._main_image_request_token or index != self._photo_current_index:
                return
            texture = proxy_texture(proxy)
            if texture is None:
                return
            self.main_photo_image.texture = texture
            self._photo_loaded_path = path
            self.photo_status_label.text = ""
            self.photo_status_label.opacity = 0
            mark("photo_main_texture_ready", texture_request_started, index=index)

        def failed(_proxy, error=None):
            if request_token != self._main_image_request_token or index != self._photo_current_index:
                return
            self.main_photo_image.texture = None
            self._photo_loaded_path = None
            self.photo_status_label.text = f"预览加载失败：{error or '图片无法解码'}"
            self.photo_status_label.opacity = 1

        self._photo_image_cache.request(path, on_load=loaded, on_error=failed)
        self._prefetch_photo_neighbors(index)

    def _prefetch_photo_neighbors(self, index):
        rows = getattr(self, "photo_rows", [])
        if not rows:
            return
        for neighbor in range(max(0, index - 2), min(len(rows), index + 3)):
            row = rows[neighbor]
            source = self._thumbnail_source(row)
            if source:
                self._photo_image_cache.prefetch(source)
            elif IS_ANDROID and abs(neighbor - index) <= 1 and self._original_source(row):
                self._generate_missing_thumbnail(int(row["id"]))

    def _on_photo_swipe(self, direction):
        if getattr(self, "_photo_mode", "browse") != "browse":
            return
        if direction == "previous":
            self.show_photo_index(self._photo_current_index - 1)
        else:
            self.show_photo_index(self._photo_current_index + 1)

    def show_photo_index(self, index, *_args):
        if not getattr(self, "photo_rows", None):
            return
        self._photo_mode = "browse"
        if self.photo_mode_host.children and self.photo_mode_host.children[0] is not self.photo_browser_panel:
            self.photo_mode_host.clear_widgets()
            self.photo_mode_host.add_widget(self.photo_browser_panel)
            self.photo_mode_host.height = self.photo_browser_panel.height
        self.photo_browse_mode_button.fill_color = PRIMARY
        self.photo_compare_mode_button.fill_color = CARD_ALT
        self._show_photo_index(index, scroll_thumbnail=True)

    def _generate_missing_thumbnail(self, photo_id):
        if not IS_ANDROID:
            return
        photo_id = int(photo_id)
        if photo_id in self._thumbnail_jobs or photo_id in self._thumbnail_failed_ids:
            return
        row = next((item for item in self.photo_rows if int(item["id"]) == photo_id), None)
        if row is None:
            return
        original = self._original_source(row)
        if original is None:
            self._thumbnail_failed_ids.add(photo_id)
            if self._photo_current_index < len(self.photo_rows) and int(self.photo_rows[self._photo_current_index]["id"]) == photo_id:
                self.photo_status_label.text = "原图文件不存在"
                self.photo_status_label.opacity = 1
            return

        self._thumbnail_jobs.add(photo_id)
        thumb = self.storage.body_photo_thumbnail_dir / f"{photo_id}.jpg"
        temp = thumb.with_suffix(".jpg.part")
        storage = self.storage

        def worker():
            try:
                create_photo_thumbnail(original, temp, max_dimension=640, quality=82)
                os.replace(temp, thumb)
                storage.set_body_photo_thumbnail(photo_id, thumb)
                Clock.schedule_once(lambda _dt: self._thumbnail_generation_succeeded(photo_id, thumb), 0)
            except Exception as exc:
                try:
                    temp.unlink()
                except OSError:
                    pass
                Clock.schedule_once(lambda _dt, err=exc: self._thumbnail_generation_failed(photo_id, err), 0)

        Thread(target=worker, name=f"photo-thumb-{photo_id}", daemon=True).start()

    def _thumbnail_generation_succeeded(self, photo_id, thumb):
        self._thumbnail_jobs.discard(int(photo_id))
        self._thumbnail_failed_ids.discard(int(photo_id))
        # The generated preview has a new/valid path. Invalidate only that key;
        # the remaining LRU entries continue to serve adjacent photos.
        self._photo_image_cache.invalidate(thumb)
        self._photo_thumb_sources[int(photo_id)] = str(thumb)
        self._refresh_thumbnail_data()
        if (self.photo_rows and 0 <= self._photo_current_index < len(self.photo_rows) and
                int(self.photo_rows[self._photo_current_index]["id"]) == int(photo_id)):
            self._photo_loaded_path = None
            self._show_photo_index(self._photo_current_index)
        if self._photo_mode == "compare":
            if (self._compare_before_index is not None and
                    0 <= int(self._compare_before_index) < len(self.photo_rows) and
                    int(self.photo_rows[int(self._compare_before_index)]["id"]) == int(photo_id)):
                self._render_compare_side("before")
            if (self._compare_after_index is not None and
                    0 <= int(self._compare_after_index) < len(self.photo_rows) and
                    int(self.photo_rows[int(self._compare_after_index)]["id"]) == int(photo_id)):
                self._render_compare_side("after")

    def _thumbnail_generation_failed(self, photo_id, error):
        self._thumbnail_jobs.discard(int(photo_id))
        self._thumbnail_failed_ids.add(int(photo_id))
        if (self.photo_rows and 0 <= self._photo_current_index < len(self.photo_rows) and
                int(self.photo_rows[self._photo_current_index]["id"]) == int(photo_id)):
            self.main_photo_image.texture = None
            self._photo_loaded_path = None
            self.photo_status_label.text = f"预览生成失败：{error}。原图仍保留。"
            self.photo_status_label.opacity = 1
        self._refresh_thumbnail_data()
        if self._photo_mode == "compare":
            self._render_compare_side("before")
            self._render_compare_side("after")

    def show_photo_browser(self, *_args):
        self._photo_mode = "browse"
        self.photo_mode_host.clear_widgets()
        self.photo_mode_host.add_widget(self.photo_browser_panel)
        self.photo_mode_host.height = self.photo_browser_panel.height
        self.photo_browse_mode_button.fill_color = PRIMARY
        self.photo_compare_mode_button.fill_color = CARD_ALT
        self._show_photo_index(self._photo_current_index, scroll_thumbnail=False)

    def set_compare_anchor(self, side):
        if not getattr(self, "photo_rows", None):
            self.info("没有照片", "添加至少一张体型照片后才能选择对比照片。")
            return
        if side == "before":
            self._compare_before_index = self._photo_current_index
        else:
            self._compare_after_index = self._photo_current_index
        self._update_compare_selection_hint()
        if self._photo_mode == "compare":
            self._render_compare_side(side)

    def _update_compare_selection_hint(self):
        if not hasattr(self, "photo_selection_hint"):
            return
        rows = getattr(self, "photo_rows", [])
        if not rows:
            self.photo_selection_hint.text = "选择前期和后期照片后进行对比"
            return
        before = self._compare_before_index
        after = self._compare_after_index
        b = rows[before]["photo_date"] if before is not None and 0 <= before < len(rows) else "未选"
        a = rows[after]["photo_date"] if after is not None and 0 <= after < len(rows) else "未选"
        self.photo_selection_hint.text = f"前期：{b}  ·  后期：{a}"

    def show_photo_comparison(self, *_args):
        if not getattr(self, "photo_rows", None):
            self.info("没有照片", "至少添加一张体型照片后才能使用前后对比。")
            return
        if self._compare_after_index is None or not 0 <= self._compare_after_index < len(self.photo_rows):
            self._compare_after_index = self._photo_current_index
        if self._compare_before_index is None or not 0 <= self._compare_before_index < len(self.photo_rows):
            self._compare_before_index = 0
        if self._compare_after_index is None or not 0 <= self._compare_after_index < len(self.photo_rows):
            self._compare_after_index = self._photo_current_index
        if len(self.photo_rows) > 1 and self._compare_before_index == self._compare_after_index:
            self._compare_before_index = 0
            self._compare_after_index = len(self.photo_rows) - 1
        self._photo_mode = "compare"
        self.photo_mode_host.clear_widgets()
        self.photo_mode_host.add_widget(self.photo_compare_panel)
        self.photo_mode_host.height = self.photo_compare_panel.height
        self.photo_browse_mode_button.fill_color = CARD_ALT
        self.photo_compare_mode_button.fill_color = PRIMARY
        self._update_compare_selection_hint()
        self._render_compare_side("before")
        self._render_compare_side("after")

    def _render_compare_side(self, side):
        rows = getattr(self, "photo_rows", [])
        if not rows:
            return
        index = self._compare_before_index if side == "before" else self._compare_after_index
        index = max(0, min(int(index or 0), len(rows) - 1))
        if side == "before":
            self._compare_before_index = index
            image, date_label, status = (self.compare_before_image, self.compare_before_date_label,
                                         self.compare_before_status)
        else:
            self._compare_after_index = index
            image, date_label, status = (self.compare_after_image, self.compare_after_date_label,
                                         self.compare_after_status)
        row = rows[index]
        created = str(row.get("created_at", ""))
        date_label.text = f"{row['photo_date']} {created[11:16]} · {index + 1}/{len(rows)}"
        source = self._thumbnail_source(row)
        if not source:
            original = self._original_source(row)
            if IS_ANDROID and original and int(row["id"]) not in self._thumbnail_failed_ids:
                status.text = "正在准备预览…"
                self._generate_missing_thumbnail(int(row["id"]))
            elif int(row["id"]) in self._thumbnail_failed_ids:
                status.text = "预览生成失败，原图仍已保存"
                image.texture = None
            else:
                status.text = "原图不存在或预览不可用"
                image.texture = None
            status.opacity = 1
            return
        self._compare_request_tokens[side] += 1
        token = self._compare_request_tokens[side]
        status.text = "载入中…" if image.texture is None else ""
        status.opacity = 1 if image.texture is None else 0

        def loaded(proxy):
            if token != self._compare_request_tokens[side] or self._photo_mode != "compare":
                return
            current = self._compare_before_index if side == "before" else self._compare_after_index
            if current != index:
                return
            texture = proxy_texture(proxy)
            if texture is None:
                return
            image.texture = texture
            status.text = ""
            status.opacity = 0

        def failed(_proxy, error=None):
            if token != self._compare_request_tokens[side] or self._photo_mode != "compare":
                return
            image.texture = None
            status.text = f"预览加载失败：{error or '图片无法解码'}"
            status.opacity = 1

        self._photo_image_cache.request(source, on_load=loaded, on_error=failed)
        self._prefetch_photo_neighbors(index)

    def step_compare_photo(self, side, delta):
        if not getattr(self, "photo_rows", None):
            return
        if side == "before":
            self._compare_before_index = max(0, min(len(self.photo_rows) - 1,
                                                    int(self._compare_before_index or 0) + int(delta)))
        else:
            self._compare_after_index = max(0, min(len(self.photo_rows) - 1,
                                                   int(self._compare_after_index or 0) + int(delta)))
        self._update_compare_selection_hint()
        self._render_compare_side(side)

    def swap_compare_photos(self, *_args):
        self._compare_before_index, self._compare_after_index = (
            self._compare_after_index, self._compare_before_index)
        self._update_compare_selection_hint()
        self._render_compare_side("before")
        self._render_compare_side("after")

    def jump_to_selected_photo(self, *_):
        date_value = getattr(self, "calendar_selected_date", datetime.now().date()).isoformat()
        self.progress_filter_date = date_value
        if not getattr(self, "photo_rows", None):
            self.info("没有照片", f"{date_value} 暂无体型照片。添加后会显示在时间线上。")
            return
        for index, row in enumerate(self.photo_rows):
            if row["photo_date"] == date_value:
                self.show_photo_browser()
                self.show_photo_index(index)
                return
        self.info("没有当天照片", f"{date_value} 暂无体型照片，时间线仍保留全部历史记录。")

    def confirm_delete_current_photo(self, *_):
        if not getattr(self, "photo_rows", None):
            self.info("没有照片", "当前没有可删除的照片。")
            return
        row = self.photo_rows[max(0, min(self._photo_current_index, len(self.photo_rows) - 1))]
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
        if not getattr(self, "photo_rows", None):
            if confirm_popup:
                confirm_popup.dismiss()
            return
        absolute = max(0, min(int(self._photo_current_index), len(self.photo_rows) - 1))
        row = self.photo_rows[absolute]
        photo_id = int(row["id"])
        date_to_show = self.progress_filter_date or row["photo_date"]
        storage = self.storage
        if confirm_popup:
            confirm_popup.dismiss()

        try:
            original = self.storage.body_photo_path(row)
            thumb = self.storage.body_photo_thumbnail_path(row)
        except (OSError, ValueError):
            original = thumb = None

        def worker():
            # Do not delete if the protective full backup cannot be completed.
            backup_path = storage.create_full_backup()
            if backup_path is None:
                raise RuntimeError("无法创建删除前备份，因此照片没有被删除。")
            storage.delete_body_photo(photo_id)
            return {"backup": str(backup_path), "date": row["photo_date"]}

        def complete(_result):
            if original is not None:
                self._photo_image_cache.invalidate(original)
            if thumb is not None:
                self._photo_image_cache.invalidate(thumb)
            self._photo_loaded_path = None
            if getattr(self, "_calendar_total_photo_count", None) is not None:
                self._calendar_total_photo_count = max(0, self._calendar_total_photo_count - 1)
            self._calendar_cache_month = None
            if getattr(self, "calendar_grid", None) is not None:
                self.render_calendar()
            self.refresh_calendar_photo_data(preferred_date=getattr(self, "calendar_selected_date", datetime.now().date()))
            self.refresh_photo_browser(preferred_date=date_to_show)
            self.refresh_home_summary()
            self.info("已删除照片", "照片已从时间线移除，删除前的完整备份已保存。")

        self.run_background_task("正在备份并删除照片", worker, on_success=complete)
