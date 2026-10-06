"""Convert upstream "missing" encodings to None (PLAN §5.1 rule 4). Never display them as numbers."""

from __future__ import annotations

from typing import Any

URBAN_SENTINELS = {-1, -2, -3}
SCORECARD_SENTINELS = {"PrivacySuppressed", "NULL", ""}


def urban(v: Any) -> Any:
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    if isinstance(v, int | float) and v in URBAN_SENTINELS:
        return None
    if isinstance(v, str):
        s = v.strip()
        if s in {"-1", "-2", "-3", "-1.0", "-2.0", "-3.0", ""}:
            return None
        return s
    return v


def urban_num(v: Any) -> float | None:
    v = urban(v)
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if f < 0 else f


def scorecard(v: Any) -> Any:
    if v is None:
        return None
    if isinstance(v, str) and v.strip() in SCORECARD_SENTINELS:
        return None
    return v


def scorecard_num(v: Any) -> float | None:
    v = scorecard(v)
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if f < 0 else f
