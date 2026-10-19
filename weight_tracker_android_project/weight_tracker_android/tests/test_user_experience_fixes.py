"""Source guards for the high-priority data and UX fixes.

These complement behavior-level storage/geometry tests; Android SAF flows still
require a device build for end-to-end verification.
"""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class UserExperienceFixSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bridge = (ROOT / "services/android_bridge.py").read_text(encoding="utf-8")
        cls.settings = (ROOT / "ui/settings_feature.py").read_text(encoding="utf-8")
        cls.records = (ROOT / "ui/records_feature.py").read_text(encoding="utf-8")
        cls.widgets = (ROOT / "ui/widgets.py").read_text(encoding="utf-8")
        cls.app = (ROOT / "app.py").read_text(encoding="utf-8")
        cls.profile = (ROOT / "ui/screens/profile_screen.py").read_text(encoding="utf-8")
        cls.progress = (ROOT / "ui/screens/progress_screen.py").read_text(encoding="utf-8")

    def test_android_csv_export_uses_document_picker_and_all_records(self):
        self.assertIn("CSV_SAVE_REQUEST = 4105", self.bridge)
        self.assertIn("Intent.ACTION_CREATE_DOCUMENT", self.settings)
        self.assertIn("copy_path_to_uri", self.settings)
        self.assertIn("rows = storage.list_records()", self.settings)
        self.assertNotIn("self.storage.export_csv(path, self.rows)", self.settings)
        self.assertIn("已导出全部历史记录", self.settings)

    def test_plot_drawing_and_hit_test_share_target_aware_bounds(self):
        self.assertIn("from services.plot_geometry import value_bounds", self.widgets)
        self.assertIn("lo, hi = value_bounds(self.points, self.target)", self.widgets)
        self.assertEqual(self.widgets.count("lo, hi = value_bounds(self.points, self.target)"), 2)

    def test_permanent_delete_has_confirmation_and_refreshes_existing_dialog(self):
        self.assertIn("确认永久删除", self.settings)
        self.assertIn("永久删除后无法从回收站恢复", self.settings)
        self.assertIn("self._refresh_recycle_list()", self.settings)
        self.assertIn("def _refresh_recycle_list", self.settings)

    def test_recycle_bin_shows_empty_state_and_restores_in_place(self):
        self.assertIn("回收站为空", self.settings)
        self.assertIn("def restore_recycle", self.settings)
        restore_source = self.settings.split("def restore_recycle", 1)[1].split("def perm_recycle", 1)[0]
        self.assertIn("self._refresh_recycle_list()", restore_source)
        self.assertNotIn("self.open_recycle()", restore_source)

    def test_statistics_preferences_are_loaded_and_persisted(self):
        self.assertIn('"show_bmi", "show_labels"', self.app)
        self.assertIn('_parse_bool_setting(settings.get("show_bmi")', self.app)
        self.assertIn('_parse_bool_setting(settings.get("show_labels")', self.app)
        self.assertIn('self.storage.set_setting("show_bmi", self.show_bmi)', self.records)
        self.assertIn('self.storage.set_setting("show_labels", self.show_labels)', self.records)
        self.assertIn("CheckBox(active=bool(self.show_bmi)", self.profile)
        self.assertIn("CheckBox(active=bool(self.show_labels)", self.profile)

    def test_photo_timeline_includes_year_in_thumbnail_labels(self):
        self.assertIn('"caption": row["photo_date"]', self.progress)

    def test_comparison_requires_two_photos_and_calendar_mismatch_is_explained(self):
        self.assertIn('if len(getattr(self, "photo_rows", [])) < 2', self.progress)
        self.assertIn("前后对比至少需要两张体型照片", self.progress)
        self.assertIn("所选日期", self.progress)
        self.assertIn("当前显示", self.progress)

    def test_corrupt_android_thumbnail_has_bounded_recovery_path(self):
        self.assertIn("def _recover_failed_thumbnail", self.progress)
        self.assertIn("_thumbnail_recovery_attempts", self.progress)
        self.assertIn("_generate_missing_thumbnail(photo_id)", self.progress)
        self.assertIn("原图仍保留", self.progress)
        self.assertIn("self.photo_retry_button = self.button(\"重试预览\", self.retry_current_photo_preview", self.progress)
        self.assertIn("def retry_current_photo_preview", self.progress)


if __name__ == "__main__":
    unittest.main()
