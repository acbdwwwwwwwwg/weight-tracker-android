"""Explicit display/storage unit conversions for body weight.

The database and legacy CSV format stay in 斤 (jin). UI conversion is always
performed at the boundary, so switching units never rewrites historical data.
"""
from __future__ import annotations

SUPPORTED_WEIGHT_UNITS = ("斤", "kg")


def normalize_weight_unit(value: str | None) -> str:
    return "kg" if str(value or "斤").strip().casefold() == "kg" else "斤"


def jin_to_display(value_jin: float, unit: str = "斤") -> float:
    value = float(value_jin)
    return value / 2.0 if normalize_weight_unit(unit) == "kg" else value


def display_to_jin(value_display: float, unit: str = "斤") -> float:
    value = float(value_display)
    return value * 2.0 if normalize_weight_unit(unit) == "kg" else value


def unit_label(unit: str = "斤") -> str:
    return normalize_weight_unit(unit)


def format_weight(value_jin: float | None, unit: str = "斤", decimals: int = 1) -> str:
    if value_jin is None:
        return "--"
    return f"{jin_to_display(value_jin, unit):.{int(decimals)}f} {unit_label(unit)}"
