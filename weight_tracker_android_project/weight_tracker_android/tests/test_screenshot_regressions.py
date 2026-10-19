"""Source-level regression guards for issues found in the user's APK screenshots.

These do not replace rendering tests on an Android device, but they prevent the
known date-axis/label and RecycleView initialization fixes from being removed.
"""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ScreenshotRegressionSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.widgets = (ROOT / "ui/widgets.py").read_text(encoding="utf-8")
        cls.geometry = (ROOT / "services/plot_geometry.py").read_text(encoding="utf-8")
        cls.records = (ROOT / "ui/records_feature.py").read_text(encoding="utf-8")
        cls.progress = (ROOT / "ui/screens/progress_screen.py").read_text(encoding="utf-8")
        cls.home = (ROOT / "ui/screens/home_screen.py").read_text(encoding="utf-8")
        cls.navigation = (ROOT / "ui/navigation.py").read_text(encoding="utf-8")

    def test_chart_draws_point_value_labels_when_preference_enabled(self):
        self.assertIn("show_labels = BooleanProperty(False)", self.widgets)
        self.assertIn("if self.show_labels:", self.widgets)
        self.assertIn('self._add_caption(f"{yv:.1f}"', self.widgets)
        self.assertIn('self.plot.show_labels = bool(show_labels)', self.records)

    def test_chart_has_date_axis_labels_and_uses_actual_day_values(self):
        self.assertIn("normalized_x_positions(self.points)", self.widgets)
        self.assertIn("date_tick_indices(self.points, maximum=3)", self.widgets)
        self.assertIn("format_date_tick(xv, self.points)", self.widgets)
        self.assertIn("points.append((day, value, record.get(\"id\"), record))", self.records)
        self.assertIn("BMI 趋势", self.records)
        self.assertIn("self.trend_title_label", self.home)

    def test_date_axis_helpers_preserve_real_spacing(self):
        self.assertIn("date.fromisoformat(value[:10]).toordinal()", self.geometry)
        self.assertIn("(value - low) / (high - low)", self.geometry)

    def test_photo_recycle_layout_is_explicitly_activated_and_sized(self):
        self.assertIn("self.photo_thumbnail_view.layout_manager = self.photo_thumbnail_layout", self.progress)
        self.assertIn("rv.refresh_from_data()", self.progress)
        self.assertIn("dp(82) * len(data)", self.progress)
        self.assertIn('"caption": row["photo_date"]', self.progress)

    def test_home_icon_uses_a_glyph_supported_by_the_configured_font(self):
        self.assertIn('("home", "◆", "首页")', self.navigation)


if __name__ == "__main__":
    unittest.main()
