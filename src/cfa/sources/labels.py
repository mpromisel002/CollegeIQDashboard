"""Code-to-label maps for IPEDS / Scorecard coded values (verified in docs/DATA_SOURCES.md)."""

from __future__ import annotations

# urban_centric_locale / Scorecard school.locale (NCES 12-category locale codes)
LOCALE_LABELS: dict[int, str] = {
    11: "City: Large",
    12: "City: Midsize",
    13: "City: Small",
    21: "Suburb: Large",
    22: "Suburb: Midsize",
    23: "Suburb: Small",
    31: "Town: Fringe",
    32: "Town: Distant",
    33: "Town: Remote",
    41: "Rural: Fringe",
    42: "Rural: Distant",
    43: "Rural: Remote",
}
SETTING_BY_TENS: dict[int, str] = {1: "City", 2: "Suburb", 3: "Town", 4: "Rural"}

# Urban ipeds/admissions-requirements reqt_test_scores
URBAN_TEST_POLICY: dict[int, str] = {
    0: "Neither required nor recommended",
    1: "Required",
    2: "Recommended",
    3: "Considered but not required",
}

# Scorecard latest.admissions.test_requirements (IPEDS ADMCON7 coding)
SCORECARD_TEST_POLICY: dict[int, str] = {
    1: "Required",
    2: "Recommended",
    3: "Neither required nor recommended",
    5: "Considered but not required",
}


def locale_label(code: int | None) -> tuple[str | None, str | None]:
    """Return (detailed label, setting) for a 2-digit NCES locale code."""
    if code is None:
        return None, None
    code = int(code)
    return LOCALE_LABELS.get(code), SETTING_BY_TENS.get(code // 10) if code in LOCALE_LABELS else None


def format_phone(raw: str | None) -> str | None:
    if not raw:
        return None
    digits = "".join(ch for ch in str(raw) if ch.isdigit())
    if len(digits) == 10:
        return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"
    if len(digits) == 11 and digits.startswith("1"):
        return f"({digits[1:4]}) {digits[4:7]}-{digits[7:]}"
    return str(raw)
