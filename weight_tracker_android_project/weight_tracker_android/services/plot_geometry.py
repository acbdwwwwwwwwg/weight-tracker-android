"""Pure plot-coordinate helpers shared by drawing and hit-testing.

Keeping bounds in one function prevents the drawn line and touch detector from
using different ranges when a target line is visible.
"""

def value_bounds(points, target=0.0):
    """Return the inclusive y-axis bounds for points and an optional target.

    The caller handles empty data separately. For flat series this deliberately
    returns equal bounds; renderers should use a non-zero fallback span.
    """
    values = [float(point[1]) for point in points]
    if not values:
        return (0.0, 1.0)
    low, high = min(values), max(values)
    try:
        target_value = float(target or 0.0)
    except (TypeError, ValueError):
        target_value = 0.0
    if target_value:
        low = min(low, target_value)
        high = max(high, target_value)
    return low, high
