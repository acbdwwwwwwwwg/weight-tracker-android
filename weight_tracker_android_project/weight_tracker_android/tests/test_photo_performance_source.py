"""Source-level guards for performance regressions when Kivy is unavailable in CI."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class PhotoPerformanceSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.progress = (ROOT / "ui/screens/progress_screen.py").read_text(encoding="utf-8")
        cls.widgets = (ROOT / "ui/widgets.py").read_text(encoding="utf-8")
        cls.cache = (ROOT / "services/photo_cache.py").read_text(encoding="utf-8")
        cls.app = (ROOT / "app.py").read_text(encoding="utf-8")
        cls.records = (ROOT / "ui/records_feature.py").read_text(encoding="utf-8")
        cls.theme = (ROOT / "ui/theme.py").read_text(encoding="utf-8")
        cls.main = (ROOT / "main.py").read_text(encoding="utf-8")

    def test_photo_browser_no_longer_uses_carousel_or_page_rebuild_timer(self):
        self.assertNotIn("Carousel", self.progress)
        self.assertNotIn("PhotoPage", self.progress)
        self.assertNotIn("_recenter_photo_window", self.progress)
        self.assertNotIn("0.24", self.progress)

    def test_normal_photo_switch_does_not_force_reload(self):
        self.assertNotIn(".reload(", self.widgets)
        self.assertNotIn(".reload(", self.progress)
        self.assertIn("Loader.image(key, nocache=True)", self.cache)
        self.assertIn("nocache=True", self.widgets)
        self.assertIn("proxy.bind(on_load=loaded)", self.cache)

    def test_cache_has_hard_capacity_and_neighbor_prefetch(self):
        self.assertIn("PHOTO_CACHE_CAPACITY = 5", self.progress)
        self.assertIn("PhotoImageCache(self.PHOTO_CACHE_CAPACITY)", self.progress)
        self.assertIn("index - 2", self.progress)
        self.assertIn("index + 3", self.progress)

    def test_timeline_uses_recycled_horizontal_list_and_fast_swipes(self):
        self.assertIn("RecycleView", self.progress)
        self.assertIn("RecycleBoxLayout", self.progress)
        self.assertIn("PhotoThumbnailTile", self.widgets)
        self.assertIn("min_distance_dp=24", self.progress)
        self.assertIn('"previous" if dx > 0 else "next"', self.widgets)
        self.assertIn("前后变化对比", self.progress)

    def test_metadata_file_existence_checks_run_in_worker(self):
        self.assertIn("def worker():", self.progress)
        self.assertIn("thumb_path.exists()", self.progress)
        self.assertIn("_photo_thumb_sources", self.progress)
        source_helper = self.progress.split("def _thumbnail_source(self, row):", 1)[1].split("def _original_source", 1)[0]
        self.assertNotIn(".exists(", source_helper)

    def test_startup_and_home_queries_are_backgrounded_and_instrumented(self):
        self.assertIn('Thread(target=worker, name="startup-storage-init"', self.app)
        self.assertIn('Thread(target=worker, name="home-summary-query"', self.app)
        self.assertIn('Thread(target=worker, name="weight-trend-query"', self.records)
        for phase in ("python_entry", "app_import_complete", "startup_shell_ready", "startup_storage_ready", "startup_first_screen_ready"):
            self.assertIn(phase, self.main + self.app)

    def test_android_font_resolution_checks_system_font_before_bundled_file(self):
        self.assertIn("if ANDROID_AVAILABLE", self.theme)
        self.assertLess(self.theme.index('Path("/system/fonts/NotoSansCJK-Regular.ttc")'),
                        self.theme.index('FONT_CANDIDATES.extend([FONT_DIR'))


if __name__ == "__main__":
    unittest.main()
