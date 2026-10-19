"""Pure unit tests for chart scaling shared by drawing and hit-testing."""
import unittest

from services.plot_geometry import value_bounds


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


if __name__ == "__main__":
    unittest.main()
