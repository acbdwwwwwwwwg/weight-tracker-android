"""Pure utilities shared by UI feature modules."""
from datetime import datetime


def as_dt(value: str) -> datetime:
    return datetime.fromisoformat(value)
