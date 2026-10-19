"""Pure chart geometry helpers shared by drawing and hit-testing.

The app stores the first field of a point as an ISO date string. Numeric x-values
remain supported for compatibility with older callers and isolated unit tests.
"""
from datetime import date, datetime


def value_bounds(points, target=0.0):
    """Return inclusive y-axis bounds, keeping flat/single-point data visible.

    A zero-height data range puts a point on the bottom edge in a number of
    renderers. Expand flat ranges symmetrically so new users with only one
    measurement see a centered point instead of an apparently empty chart.
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
    if abs(high - low) < 1e-9:
        center = (low + high) / 2.0
        padding = max(abs(center) * 0.03, 0.5)
        low, high = center - padding, center + padding
    return low, high


def _date_ordinal(value):
    """Convert date-like x data to an ordinal, or return None if not a date."""
    if isinstance(value, datetime):
        return float(value.date().toordinal())
    if isinstance(value, date):
        return float(value.toordinal())
    if isinstance(value, str):
        try:
            return float(date.fromisoformat(value[:10]).toordinal())
        except (TypeError, ValueError):
            return None
    return None


def normalized_x_positions(points):
    """Return x positions in [0, 1], proportional to elapsed date/time when possible.

    One point is centered. Flat numeric inputs spread evenly to retain the old
    index-based behavior; valid dates always honor real date gaps.
    """
    if not points:
        return []
    x_raw = [point[0] for point in points]
    date_values = [_date_ordinal(value) for value in x_raw]
    if all(value is not None for value in date_values):
        values = date_values
    else:
        values = []
        for index, value in enumerate(x_raw):
            try:
                values.append(float(value))
            except (TypeError, ValueError):
                values.append(float(index))
    if len(values) == 1:
        return [0.5]
    low, high = min(values), max(values)
    if high <= low:
        step = 1.0 / (len(values) - 1)
        return [index * step for index in range(len(values))]
    return [(value - low) / (high - low) for value in values]


def date_tick_indices(points, maximum=3):
    """Choose stable, evenly distributed point indices for date-axis captions."""
    count = len(points)
    if count <= 0:
        return []
    if count <= maximum:
        return list(range(count))
    if maximum <= 1:
        return [0]
    indices = [round(i * (count - 1) / (maximum - 1)) for i in range(maximum)]
    # Remove collisions caused by rounding while preserving chronological order.
    return list(dict.fromkeys(indices))


def format_date_tick(value, points):
    """Format compact but unambiguous date captions for the current series."""
    if isinstance(value, datetime):
        current = value.date()
    elif isinstance(value, date):
        current = value
    elif isinstance(value, str):
        try:
            current = date.fromisoformat(value[:10])
        except (TypeError, ValueError):
            return str(value)
    else:
        return ""

    years = set()
    for point in points:
        if len(point) < 1:
            continue
        ordinal = _date_ordinal(point[0])
        if ordinal is not None:
            years.add(date.fromordinal(int(ordinal)).year)
    return current.strftime("%y/%m/%d" if len(years) > 1 else "%m/%d")
