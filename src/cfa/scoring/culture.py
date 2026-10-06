"""Culture fit 0-100: importance-weighted average of the factors the student cares about (PLAN §6.3)."""

from __future__ import annotations

from dataclasses import dataclass, field

from cfa import config
from cfa.models.college import CollegeRecord
from cfa.models.student import Athletics, GreekDirection, Setting, SizePref, StudentProfile

SETTING_ORDER = [Setting.CITY, Setting.SUBURB, Setting.TOWN, Setting.RURAL]
SIZE_ORDER = [SizePref.SMALL, SizePref.MEDIUM, SizePref.LARGE, SizePref.HUGE]


def size_band(n: float) -> SizePref:
    a, b, c = config.SIZE_BANDS
    if n < a:
        return SizePref.SMALL
    if n < b:
        return SizePref.MEDIUM
    if n < c:
        return SizePref.LARGE
    return SizePref.HUGE


def greek_pct(college: CollegeRecord) -> float | None:
    vals = [v for v in (college.num("greek_men_pct"), college.num("greek_women_pct")) if v is not None]
    return sum(vals) / len(vals) if vals else None


@dataclass
class CultureFit:
    score: float | None
    parts: dict[str, float] = field(default_factory=dict)  # factor -> sub-score 0-100
    weights: dict[str, int] = field(default_factory=dict)
    not_scored: list[str] = field(default_factory=list)

    def explain(self) -> str:
        if self.score is None:
            return (
                "No culture preferences set"
                if not self.not_scored
                else ("Not scored: " + ", ".join(self.not_scored))
            )
        bits = [f"{k} {v:.0f} (x{self.weights[k]})" for k, v in self.parts.items()]
        text = "; ".join(bits)
        if self.not_scored:
            text += " | not scored: " + ", ".join(self.not_scored)
        return text


def _ladder(a: int, b: int) -> float:
    d = abs(a - b)
    return 100.0 if d == 0 else 50.0 if d == 1 else 0.0


def score(student: StudentProfile, college: CollegeRecord) -> CultureFit:
    parts: dict[str, float] = {}
    weights: dict[str, int] = {}
    not_scored: list[str] = []

    def add(name: str, weight: int, value: float | None) -> None:
        if weight <= 0:
            return
        if value is None:
            not_scored.append(name)
            return
        parts[name] = max(0.0, min(100.0, value))
        weights[name] = weight

    if student.greek_direction is not GreekDirection.NEUTRAL:
        g = greek_pct(college)
        val = None
        if g is not None:
            val = min(100.0, 100.0 * g / config.GREEK_FULL_SCORE_PCT)
            if student.greek_direction is GreekDirection.AVOIDS:
                val = 100.0 - val
        add("Greek life", student.greek_importance, val)

    if student.setting_pref is not Setting.ANY:
        s = college.value("setting")
        val = None
        if isinstance(s, str) and s in [x.value for x in SETTING_ORDER]:
            val = _ladder(SETTING_ORDER.index(Setting(s)), SETTING_ORDER.index(student.setting_pref))
        add("Setting", student.setting_importance, val)

    if student.size_pref is not SizePref.ANY:
        n = college.num("undergrad_size")
        val = (
            _ladder(SIZE_ORDER.index(size_band(n)), SIZE_ORDER.index(student.size_pref))
            if n is not None
            else None
        )
        add("Size", student.size_importance, val)

    add("Housing", student.housing_importance, college.num("housing_pct"))

    if student.athletics_pref is not Athletics.ANY:
        a = college.value("athletics")
        val = None if a is None else (100.0 if a == student.athletics_pref.value else 0.0)
        add("Athletics", student.athletics_importance, val)

    if student.preferred_states:
        st = college.value("state")
        val = None if st is None else (100.0 if str(st).upper() in student.preferred_states else 0.0)
        add("Region", student.region_importance, val)

    abroad = college.value("study_abroad")
    add(
        "Study abroad",
        student.study_abroad_importance,
        None if abroad is None else (100.0 if abroad is True else 0.0),
    )

    total_w = sum(weights.values())
    value = round(sum(parts[k] * weights[k] for k in parts) / total_w, 1) if total_w else None
    return CultureFit(value, parts, weights, not_scored)
