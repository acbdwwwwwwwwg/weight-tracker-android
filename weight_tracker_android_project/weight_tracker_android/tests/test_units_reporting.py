"""Pure unit-conversion and shareable report formatting tests."""
import unittest

from services.units import display_to_jin, format_weight, jin_to_display, normalize_weight_unit
from services.reporting import format_health_report


class WeightUnitTests(unittest.TestCase):
    def test_switching_display_unit_does_not_change_canonical_storage(self):
        self.assertAlmostEqual(display_to_jin(65.5, "kg"), 131.0)
        self.assertAlmostEqual(jin_to_display(131.0, "kg"), 65.5)
        self.assertAlmostEqual(display_to_jin(jin_to_display(131, "kg"), "kg"), 131)

    def test_unknown_unit_falls_back_to_jin(self):
        self.assertEqual(normalize_weight_unit("lbs"), "斤")
        self.assertEqual(format_weight(131, "lbs"), "131.0 斤")

    def test_format_report_has_weekly_monthly_data_units_and_local_data_notice(self):
        summary = {
            "title": "2026年10月", "start_date": "2026-10-01", "end_date": "2026-10-19",
            "weight_count": 3, "weight_average_jin": 130, "seven_day_average_jin": 129,
            "seven_day_days": 5, "daily_average_change_jin": -2, "grouped_trend": [("2026-W42", 129)],
            "calories_total": 4500, "food_entries": 12, "calories_daily_average": 1500,
            "protein_total_g": 330, "training_entries": 4, "training_days": 3,
            "workout_days": 3, "training_minutes": 180, "photo_count": 2,
            "start_weight_jin": 140, "current_weight_jin": 130, "target_weight_jin": 120,
            "goal_progress_percent": 50,
            "latest_measurement": {"measured_at": "2026-10-18", "waist_cm": 80, "hip_cm": None,
                                   "chest_cm": None, "body_fat_pct": 22.5},
        }
        text = format_health_report(summary, "kg")
        self.assertIn("记录平均：65.0 kg", text)
        self.assertIn("首末日均变化：-1.0 kg", text)
        self.assertIn("总摄入：4500 kcal", text)
        self.assertIn("目标进度：50%", text)
        self.assertIn("本报告是本机记录的汇总", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
