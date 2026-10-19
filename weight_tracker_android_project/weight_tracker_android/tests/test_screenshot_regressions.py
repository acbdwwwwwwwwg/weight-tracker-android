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

    def test_daily_aggregate_point_opens_source_record_picker_not_last_row_directly(self):
        records = (ROOT / "ui/records_feature.py").read_text(encoding="utf-8")
        self.assertIn('"aggregate_date": day', records)
        self.assertIn('"records": day_records', records)
        self.assertIn('self.open_day_record_picker(row)', records)
        self.assertIn("请选择要编辑的原始记录", records)
        self.assertIn("self.edit_record(item)", records)

    def test_chart_draws_point_value_labels_when_preference_enabled(self):
        self.assertIn("show_labels = BooleanProperty(False)", self.widgets)
        self.assertIn("if self.show_labels:", self.widgets)
        self.assertIn('self._add_caption(f"{yv:.1f}"', self.widgets)
        self.assertIn('self.plot.show_labels = bool(show_labels)', self.records)

    def test_chart_has_date_axis_labels_and_uses_actual_day_values(self):
        self.assertIn("normalized_x_positions(self.points)", self.widgets)
        self.assertIn("date_tick_indices(self.points, maximum=3)", self.widgets)
        self.assertIn("format_date_tick(xv, self.points)", self.widgets)
        self.assertIn('"aggregate_date": day', self.records)
        self.assertIn('"records": day_records', self.records)
        self.assertIn("points.append((day, average, None, aggregate))", self.records)
        self.assertIn("def open_day_record_picker", self.records)
        self.assertIn("每日平均", self.records)
        self.assertIn("BMI 趋势", self.records)
        self.assertIn("self.trend_title_label", self.home)
        self.assertIn("self.stat_titles", self.records)
        self.assertIn("latest_global = storage.latest_record()", self.records)
        self.assertIn('"bmi": latest_bmi', self.records)
        self.assertIn('"diff": f"{delta:+.1f}"', self.records)
        self.assertIn('"diff": f"日均变{unit}"', self.records)

    def test_date_axis_helpers_preserve_real_spacing(self):
        self.assertIn("date.fromisoformat(value[:10]).toordinal()", self.geometry)
        self.assertIn("(value - low) / (high - low)", self.geometry)

    def test_photo_recycle_layout_is_explicitly_activated_and_sized(self):
        self.assertIn("self.photo_thumbnail_view.layout_manager = self.photo_thumbnail_layout", self.progress)
        self.assertIn("rv.refresh_from_data()", self.progress)
        self.assertIn("dp(82) * len(data)", self.progress)
        self.assertIn('"caption": row["photo_date"]', self.progress)
        self.assertIn("_schedule_nearby_thumbnail_repairs", self.progress)
        self.assertIn('text="无预览"', self.widgets)
        self.assertIn('self.thumbnail_placeholder.text = "预览失败"', self.widgets)
        self.assertIn("on_thumbnail_error", self.progress)
        self.assertIn("preview_failed", self.progress)
        self.assertIn("callback(int(self.photo_id)", self.widgets)

    def test_restore_reloads_settings_and_invalidates_stale_thumbnail_jobs(self):
        settings = (ROOT / "ui/settings_feature.py").read_text(encoding="utf-8")
        self.assertIn("_reload_runtime_settings_after_restore", settings)
        self.assertIn("self.storage.get_settings()", settings)
        self.assertIn("_photo_storage_generation", settings)
        self.assertIn("self._thumbnail_jobs.clear()", settings)

    def test_input_validation_and_timezone_normalization_are_wired(self):
        storage = (ROOT / "storage.py").read_text(encoding="utf-8")
        self.assertIn("validate_recorded_at", storage)
        self.assertIn("normalize_recorded_at", storage)
        self.assertIn("MAX_WEIGHT_JIN", storage)
        self.assertIn("MIN_HEIGHT_CM", storage)

    def test_home_icon_uses_a_glyph_supported_by_the_configured_font(self):
        self.assertIn('("home", "◆", "首页")', self.navigation)


    def test_restore_preview_estimates_space_and_blocks_overwrite_when_insufficient(self):
        storage = (ROOT / "storage.py").read_text(encoding="utf-8")
        settings = (ROOT / "ui/settings_feature.py").read_text(encoding="utf-8")
        self.assertIn("_restore_space_estimate", storage)
        self.assertIn('"estimated_peak_bytes"', storage)
        self.assertIn('"space_sufficient"', storage)
        self.assertIn("confirm_button.disabled = not space_sufficient", settings)
        self.assertIn("当前数据没有被覆盖", settings)

    def test_csv_partial_import_has_explicit_failure_summary(self):
        settings = (ROOT / "ui/settings_feature.py").read_text(encoding="utf-8")
        self.assertIn("CSV 部分导入完成", settings)
        self.assertIn("失败行不会写入数据库", settings)
        self.assertIn("另有 {len(failed) - 5} 行错误未在弹窗中展开", settings)



    def test_android_uses_user_selected_media_access_not_broad_media_permissions(self):
        spec = (ROOT / "buildozer.spec").read_text(encoding="utf-8")
        self.assertIn("android.permissions =", spec)
        self.assertNotIn("READ_MEDIA_IMAGES", spec)
        self.assertNotIn("READ_MEDIA_VIDEO", spec)
        self.assertNotIn("READ_MEDIA_AUDIO", spec)
        self.assertIn("android.allow_backup = True", spec)



if __name__ == "__main__":
    unittest.main()
