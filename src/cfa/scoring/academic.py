"""Academic fit: Safety / Target / Reach (PLAN §6.2). Thresholds live in config.py."""

from __future__ import annotations

from dataclasses import dataclass, field

from cfa import config
from cfa.models.college import GPA_BINS, CollegeRecord
from cfa.models.student import StudentProfile

SAFETY, TARGET, REACH = "Safety", "Target", "Reach"
UNCLASSIFIED = "Unclassified (insufficient data)"

# Each bin covers [low, next bin's low). The 4.0 bin is the single value 4.0.
_BIN_RANGES: dict[str, tuple[float, float]] = {
    "4.0": (4.0, 4.0),
    "3.75-3.99": (3.75, 4.0),
    "3.50-3.74": (3.50, 3.75),
    "3.25-3.49": (3.25, 3.50),
    "3.00-3.24": (3.00, 3.25),
    "2.50-2.99": (2.50, 3.00),
    "2.00-2.49": (2.00, 2.50),
    "1.00-1.99": (1.00, 2.00),
    "<1.00": (0.0, 1.00),
}

BELOW, MIDDLE, ABOVE = "below 25th percentile", "25th-75th percentile", "above 75th percentile"


@dataclass
class AcademicFit:
    tier: str
    reason: str
    gpa_percentile: float | None = None
    test_position: str | None = None
    admit_rate: float | None = None
    missing: list[str] = field(default_factory=list)


def gpa_percentile(gpa: float, dist: dict[str, float]) -> float | None:
    """Estimated share (0-100) of enrolled first-years with a lower GPA than the student (C11)."""
    total = sum(dist.get(b, 0.0) for b in GPA_BINS)
    if total <= 0:
        return None
    below = 0.0
    for b in reversed(GPA_BINS):  # lowest bin first
        lo, hi = _BIN_RANGES[b]
        share = dist.get(b, 0.0)
        if b == "4.0":
            if gpa >= 4.0:
                below += share / 2  # mid-rank within the tied bin
            break
        if gpa >= hi:
            below += share
        elif gpa >= lo:
            below += share * (gpa - lo) / (hi - lo)
            break
        else:
            break
    return round(100 * below / total, 1)


def test_position(student: StudentProfile, college: CollegeRecord) -> tuple[str | None, str]:
    """Best position across the student's SAT and ACT versus the school's middle 50%."""
    if not student.submits_tests:
        return None, "student is not submitting tests"
    positions: list[tuple[int, str, str]] = []
    rank = {BELOW: 0, MIDDLE: 1, ABOVE: 2}
    sat = student.sat_total
    e25, e75 = college.num("sat_ebrw_25"), college.num("sat_ebrw_75")
    m25, m75 = college.num("sat_math_25"), college.num("sat_math_75")
    few_sat, few_act = _few_submitters(college, "sat_submit_pct"), _few_submitters(college, "act_submit_pct")
    if sat is not None and None not in (e25, e75, m25, m75) and not few_sat:
        lo, hi = e25 + m25, e75 + m75  # type: ignore[operator]
        pos = BELOW if sat < lo else ABOVE if sat > hi else MIDDLE
        positions.append((rank[pos], pos, f"SAT {sat} vs ~{int(lo)}-{int(hi)}"))
    a25, a75 = college.num("act_25"), college.num("act_75")
    if student.act is not None and a25 is not None and a75 is not None and not few_act:
        pos = BELOW if student.act < a25 else ABOVE if student.act > a75 else MIDDLE
        positions.append((rank[pos], pos, f"ACT {student.act} vs {int(a25)}-{int(a75)}"))
    if not positions:
        if few_sat or few_act:
            return None, f"too few enrolled students submitted scores (under {config.MIN_SUBMIT_PCT:g}%)"
        return None, "no comparable test scores"
    best = max(positions)
    return best[1], best[2]


def _few_submitters(college: CollegeRecord, key: str) -> bool:
    """A middle-50% range from a handful of students (e.g. 1 of 600) says nothing about the school."""
    pct = college.num(key)
    return pct is not None and pct < config.MIN_SUBMIT_PCT


def classify(student: StudentProfile, college: CollegeRecord) -> AcademicFit:
    rate = college.num("acceptance_rate")
    dist = college.value("gpa_dist")
    pct = (
        gpa_percentile(student.gpa_unweighted, dist)
        if student.gpa_unweighted is not None and isinstance(dist, dict)
        else None
    )
    pos, test_note = test_position(student, college)
    missing = []
    if rate is None:
        missing.append("admit rate")
    if pct is None:
        missing.append("GPA distribution" if student.gpa_unweighted is not None else "student GPA")
    if pos is None:
        missing.append(f"test comparison ({test_note})")
    fit = AcademicFit(UNCLASSIFIED, "", pct, pos, rate, missing)
    if rate is not None and rate < config.REACH_ADMIT_RATE_PCT:
        fit.tier, fit.reason = REACH, f"Reach: admit rate {rate:g}% (<{config.REACH_ADMIT_RATE_PCT:g}%)"
        return fit
    if rate is None or (pct is None and pos is None):
        fit.reason = "Not enough data: missing " + ", ".join(missing)
        return fit
    if pos == BELOW:
        fit.tier, fit.reason = REACH, f"Reach: {test_note} ({BELOW})"
        return fit
    if pct is not None and pct < config.GPA_BOTTOM_QUARTILE:
        fit.tier, fit.reason = REACH, f"Reach: GPA in bottom 25% of enrolled students (~{pct:g}th percentile)"
        return fit
    tests_ok = pos == ABOVE or (pos is None and pct is not None and pct > config.GPA_MEDIAN)
    gpa_ok = pct is not None and pct >= config.GPA_TOP_QUARTILE
    if rate >= config.SAFETY_ADMIT_RATE_PCT and tests_ok and gpa_ok:
        tests = test_note if pos == ABOVE else "not using tests, GPA above median"
        fit.tier = SAFETY
        fit.reason = f"Safety: admit rate {rate:g}%, {tests}, GPA ~{pct:g}th percentile"
        return fit
    # Most schools outside the curated list publish no GPA distribution (it comes only from the
    # Common Data Set). There, tests above the 75th percentile and a high admit rate are enough.
    school_has_no_gpa = pct is None and student.gpa_unweighted is not None
    if rate >= config.SAFETY_ADMIT_RATE_PCT and pos == ABOVE and school_has_no_gpa:
        fit.tier = SAFETY
        fit.reason = f"Safety: admit rate {rate:g}%, {test_note} ({ABOVE}); school publishes no GPA data"
        return fit
    parts = [f"admit rate {rate:g}%"]
    if pct is not None:
        parts.append(f"GPA ~{pct:g}th percentile")
    if pos is not None:
        parts.append(f"{test_note} ({pos})")
    if missing:
        parts.append("not available: " + ", ".join(missing))
    fit.tier, fit.reason = TARGET, "Target: " + "; ".join(parts)
    return fit
