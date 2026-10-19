"""Source guards for the UI polish pass; does not require Kivy or an Android device."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class UIPolishSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.theme = (ROOT / "ui/theme.py").read_text(encoding="utf-8")
        cls.widgets = (ROOT / "ui/widgets.py").read_text(encoding="utf-8")
        cls.app = (ROOT / "app.py").read_text(encoding="utf-8")
        cls.home = (ROOT / "ui/screens/home_screen.py").read_text(encoding="utf-8")
        cls.calendar = (ROOT / "ui/screens/calendar_screen.py").read_text(encoding="utf-8")
        cls.calendar_feature = (ROOT / "ui/calendar_feature.py").read_text(encoding="utf-8")
        cls.profile = (ROOT / "ui/screens/profile_screen.py").read_text(encoding="utf-8")
        cls.progress = (ROOT / "ui/screens/progress_screen.py").read_text(encoding="utf-8")

    def test_shared_tokens_and_refined_radius_defaults_exist(self):
        for token in ("CARD_RADIUS = 18", "CONTROL_RADIUS = 14", "TILE_RADIUS = 10", "MIN_TAP_HEIGHT = 44"):
            self.assertIn(token, self.theme)
        self.assertIn("corner_radius = NumericProperty(CARD_RADIUS)", self.widgets)
        self.assertIn("corner_radius = NumericProperty(CONTROL_RADIUS)", self.widgets)

    def test_disabled_controls_have_distinct_visual_state(self):
        self.assertIn("disabled=self._sync_button", self.widgets)
        self.assertIn("if self.disabled:", self.widgets)
        self.assertIn("DISABLED_SURFACE", self.widgets)

    def test_page_transition_uses_short_opacity_only_animation(self):
        self.assertIn('Animation(opacity=1, duration=0.14, t="out_quad")', self.app)
        self.assertNotIn("Animation(width=", self.app)
        self.assertNotIn("Animation(height=", self.app)
        self.assertNotIn("Animation(x=", self.app)
        self.assertNotIn("Animation(y=", self.app)

    def test_existing_primary_actions_remain_wired(self):
        for symbol in ("self.save_record", "self.toggle_today_workout", "self.open_progress_home", "self.prev_period", "self.next_period"):
            self.assertIn(symbol, self.home)
        for symbol in ("self.calendar_prev_month", "self.calendar_next_month", "self.toggle_selected_workout", "self.add_body_photo", "self.open_progress_for_selected_date"):
            self.assertIn(symbol, self.calendar)
        for symbol in ("self.export_csv", "self.import_csv", "self.open_recycle", "self.full_backup", "self.restore_full_backup", "self.ask_height", "self.ask_target"):
            self.assertIn(symbol, self.profile)
        for symbol in ("self.add_body_photo", "self.show_photo_index", "self.show_photo_comparison", "self.set_compare_anchor", "self.confirm_delete_current_photo", "self.jump_to_selected_photo"):
            self.assertIn(symbol, self.progress)

    def test_photo_performance_architecture_is_preserved(self):
        self.assertIn("PHOTO_CACHE_CAPACITY = 5", self.progress)
        self.assertIn("RecycleView", self.progress)
        self.assertIn("PhotoSwipeSurface", self.progress)
        self.assertNotIn("Carousel", self.progress)
        self.assertNotIn(".reload(", self.widgets)
        self.assertNotIn(".reload(", self.progress)

    def test_calendar_and_primary_photo_controls_have_comfortable_targets(self):
        self.assertIn("height=dp(6 * 44)", self.calendar)
        self.assertIn("size_hint_y=None, height=dp(44)", self.calendar_feature)
        self.assertIn("self.bottom_nav_host.height = dp(68)", self.app)
        self.assertIn('self.button("‹", self.calendar_prev_month, 40', self.calendar)
        self.assertIn('self.button("‹", lambda *_args, s=side: self.step_compare_photo(s, -1), 38', self.progress)
        self.assertIn('self.button("‹ 上一张"', self.progress)


if __name__ == "__main__":
    unittest.main()
