"""Pure unit tests for chart scaling, true date spacing, and date captions."""
import unittest

from services.plot_geometry import (
    date_tick_indices,
    format_date_tick,
    normalized_x_positions,
    value_bounds,
)


class PlotGeometryTests(unittest.TestCase):
    def test_target_above_series_is_included_in_axis_bounds(self):
        self.assertEqual(value_bounds([(0, 60), (1, 65)], 80), (60.0, 80.0))

    def test_target_below_series_is_included_in_axis_bounds(self):
        self.assertEqual(value_bounds([(0, 60), (1, 65)], 45), (45.0, 65.0))

    def test_target_inside_series_does_not_expand_bounds(self):
        self.assertEqual(value_bounds([(0, 60), (1, 65)], 62), (60.0, 65.0))

    def test_missing_target_does_not_affect_bounds(self):
        self.assertEqual(value_bounds([(0, 60), (1, 65)], 0), (60.0, 65.0))

    def test_empty_points_have_safe_default(self):
        self.assertEqual(value_bounds([], 80), (0.0, 1.0))

    def test_flat_series_returns_equal_bounds_for_renderer_fallback(self):
        self.assertEqual(value_bounds([(0, 62), (1, 62)], 0), (62.0, 62.0))

    def test_date_spacing_uses_elapsed_days_not_record_index(self):
        points = [("2026-10-01", 136), ("2026-10-02", 135), ("2026-10-19", 131)]
        x = normalized_x_positions(points)
        self.assertAlmostEqual(x[0], 0.0)
        self.assertAlmostEqual(x[1], 1 / 18)
        self.assertAlmostEqual(x[2], 1.0)

    def test_one_point_is_centered(self):
        self.assertEqual(normalized_x_positions([("2026-10-19", 131)]), [0.5])

    def test_numeric_x_values_remain_supported(self):
        self.assertEqual(normalized_x_positions([(10, 60), (20, 61), (30, 62)]), [0, 0.5, 1])

    def test_date_ticks_are_limited_and_include_endpoints(self):
        points = [(f"2026-10-{day:02d}", 130 + day) for day in range(1, 11)]
        self.assertEqual(date_tick_indices(points, 3), [0, 4, 9])

    def test_date_labels_are_compact_within_one_year(self):
        points = [("2026-10-01", 136), ("2026-10-19", 131)]
        self.assertEqual(format_date_tick(points[0][0], points), "10/01")

    def test_date_labels_disambiguate_multiple_years(self):
        points = [("2025-12-31", 140), ("2026-01-02", 139)]
        self.assertEqual(format_date_tick(points[0][0], points), "25/12/31")


if __name__ == "__main__":
    unittest.main()
