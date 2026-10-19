"""Source guards for Phase 3/4 UI wiring; true Android behavior is device-tested."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class Phase34SourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = (ROOT / "app.py").read_text(encoding="utf-8")
        cls.storage = (ROOT / "storage.py").read_text(encoding="utf-8")
        cls.journal = (ROOT / "ui/journal_feature.py").read_text(encoding="utf-8")
        cls.journal_screen = (ROOT / "ui/screens/journal_screen.py").read_text(encoding="utf-8")
        cls.home = (ROOT / "ui/screens/home_screen.py").read_text(encoding="utf-8")
        cls.profile = (ROOT / "ui/screens/profile_screen.py").read_text(encoding="utf-8")
        cls.widgets = (ROOT / "ui/widgets.py").read_text(encoding="utf-8")
        cls.progress = (ROOT / "ui/screens/progress_screen.py").read_text(encoding="utf-8")

    def test_journal_route_and_tab_are_wired(self):
        self.assertIn('"journal": self.build_journal_screen', self.app)
        self.assertIn('("journal", "✎", "日志")', (ROOT / "ui/navigation.py").read_text(encoding="utf-8"))
        self.assertIn("def refresh_journal", self.journal)

    def test_nutrition_training_measurements_and_undo_are_wired(self):
        for marker in ("add_food_log", "update_food_log", "add_strength_log", "update_strength_log",
                       "add_body_measurement", "update_body_measurement", "撤销删除"):
            self.assertIn(marker, self.journal)
        self.assertIn("calories_per_100g", self.storage)
        self.assertIn("load_kg", self.storage)
        self.assertIn("body_measurements", self.storage)

    def test_daily_lists_expand_instead_of_hiding_more_than_three_items(self):
        self.assertIn("for row in foods:", self.journal)
        self.assertIn("for row in training:", self.journal)
        self.assertIn("for row in measurements:", self.journal)
        self.assertNotIn("foods[:3]", self.journal)
        self.assertNotIn("training[:3]", self.journal)
        self.assertNotIn("measurements[:2]", self.journal)
        self.assertIn("journal_food_card.height = max", self.journal)

    def test_seven_day_average_reports_and_share_are_wired(self):
        self.assertIn("get_seven_day_weight_average", self.journal)
        self.assertIn("build_health_report", self.journal)
        self.assertIn("self.run_background_task(", self.journal)
        self.assertIn("Intent.ACTION_SEND", self.journal)
        self.assertIn("format_health_report", self.journal)

    def test_reminders_are_local_and_caveat_is_visible(self):
        self.assertIn("Clock.schedule_interval", self.app)
        self.assertIn("post_local_notification", self.journal)
        self.assertIn("强行停止或系统终止进程后不能保证准时触发", self.journal_screen)

    def test_unit_switch_updates_axis_and_unsaved_draft(self):
        units = (ROOT / "services/units.py").read_text(encoding="utf-8")
        self.assertIn("display_to_jin", units)
        self.assertIn("jin_to_display", units)
        self.assertIn("stored_jin = display_to_jin(old_display, old_unit)", self.app)
        self.assertIn('else str(self.value_unit or "斤")', self.widgets)
        self.assertIn('f"最高{self.weight_unit_label()}"', self.home)

    def test_photo_date_edit_and_extended_zip_export_exist(self):
        self.assertIn("update_body_photo_date", self.progress)
        self.assertIn("export_all_data", self.profile)
        self.assertIn("photo_index.csv", self.storage)
        self.assertIn("body_measurements.csv", self.storage)
        self.assertIn("strength_logs.csv", self.storage)
        self.assertIn("food_logs.csv", self.storage)

    def test_setting_dialogs_filter_numeric_input_and_measurement_form_scrolls(self):
        settings = (ROOT / "ui/settings_feature.py").read_text(encoding="utf-8")
        self.assertIn('input_filter="float"', settings)
        self.assertIn('tone="primary"', settings)
        self.assertIn('form_scroll = ScrollView', self.journal)
        self.assertIn('size_hint=(.95, .82)', self.journal)

    def test_android_widget_is_not_misrepresented_as_implemented(self):
        widget_doc = (ROOT / "WIDGET_FEASIBILITY.md").read_text(encoding="utf-8")
        self.assertIn("尚未实现", widget_doc)
        self.assertIn("AppWidgetProvider", widget_doc)


if __name__ == "__main__":
    unittest.main(verbosity=2)
