"""CollegeRecord: every displayed field is a FieldValue keyed by a name from FIELDS."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from cfa.models.field_value import FieldValue, Status


class Kind(StrEnum):
    TEXT = "text"
    COUNT = "count"
    PERCENT = "percent"  # stored as 0-100
    GPA = "gpa"
    SCORE = "score"
    BOOL = "bool"
    MAP = "map"  # dict value (GPA distribution, admission factors)


@dataclass(frozen=True)
class FieldSpec:
    key: str
    label: str
    group: str
    kind: Kind


_SPECS: list[FieldSpec] = [
    # General
    FieldSpec("name", "Name", "General", Kind.TEXT),
    FieldSpec("address", "Street address", "General", Kind.TEXT),
    FieldSpec("city", "City", "General", Kind.TEXT),
    FieldSpec("state", "State", "General", Kind.TEXT),
    FieldSpec("zip", "Postal code", "General", Kind.TEXT),
    FieldSpec("phone", "Phone", "General", Kind.TEXT),
    FieldSpec("website", "Website", "General", Kind.TEXT),
    FieldSpec("locale", "Degree of urbanization", "General", Kind.TEXT),
    FieldSpec("setting", "Campus setting", "General", Kind.TEXT),
    FieldSpec("control", "Type of institution", "General", Kind.TEXT),
    # Applicants / admits
    FieldSpec("applicants_total", "Applicants (total)", "Admissions", Kind.COUNT),
    FieldSpec("applicants_men", "Applicants (men)", "Admissions", Kind.COUNT),
    FieldSpec("applicants_women", "Applicants (women)", "Admissions", Kind.COUNT),
    FieldSpec("applicants_another", "Applicants (another gender)", "Admissions", Kind.COUNT),
    FieldSpec("admits_total", "Admitted (total)", "Admissions", Kind.COUNT),
    FieldSpec("admits_men", "Admitted (men)", "Admissions", Kind.COUNT),
    FieldSpec("admits_women", "Admitted (women)", "Admissions", Kind.COUNT),
    FieldSpec("admits_another", "Admitted (another gender)", "Admissions", Kind.COUNT),
    FieldSpec("acceptance_rate", "Acceptance rate", "Admissions", Kind.PERCENT),
    FieldSpec("ed_offered", "Early Decision offered", "Admissions", Kind.BOOL),
    FieldSpec("ed_applicants", "ED applicants", "Admissions", Kind.COUNT),
    FieldSpec("ed_admits", "ED admitted", "Admissions", Kind.COUNT),
    FieldSpec("ed_rate", "ED admit rate", "Admissions", Kind.PERCENT),
    FieldSpec("ea_offered", "Early Action offered", "Admissions", Kind.BOOL),
    FieldSpec("ea_applicants", "EA applicants", "Admissions", Kind.COUNT),
    FieldSpec("ea_admits", "EA admitted", "Admissions", Kind.COUNT),
    FieldSpec("ea_rate", "EA admit rate", "Admissions", Kind.PERCENT),
    FieldSpec("rd_applicants", "RD applicants (estimated)", "Admissions", Kind.COUNT),
    FieldSpec("rd_admits", "RD admitted (estimated)", "Admissions", Kind.COUNT),
    FieldSpec("rd_rate", "RD admit rate (estimated)", "Admissions", Kind.PERCENT),
    # GPA
    FieldSpec("gpa_avg", "Average HS GPA", "GPA", Kind.GPA),
    FieldSpec("gpa_dist", "GPA distribution", "GPA", Kind.MAP),
    # Tests
    FieldSpec("sat_ebrw_25", "SAT EBRW 25th", "Test scores", Kind.SCORE),
    FieldSpec("sat_ebrw_75", "SAT EBRW 75th", "Test scores", Kind.SCORE),
    FieldSpec("sat_math_25", "SAT Math 25th", "Test scores", Kind.SCORE),
    FieldSpec("sat_math_75", "SAT Math 75th", "Test scores", Kind.SCORE),
    FieldSpec("act_25", "ACT Composite 25th", "Test scores", Kind.SCORE),
    FieldSpec("act_75", "ACT Composite 75th", "Test scores", Kind.SCORE),
    FieldSpec("sat_submit_pct", "% submitting SAT", "Test scores", Kind.PERCENT),
    FieldSpec("act_submit_pct", "% submitting ACT", "Test scores", Kind.PERCENT),
    FieldSpec("test_policy", "Test policy", "Test scores", Kind.TEXT),
    # Culture
    FieldSpec("greek_men_pct", "% men in fraternities", "Campus culture", Kind.PERCENT),
    FieldSpec("greek_women_pct", "% women in sororities", "Campus culture", Kind.PERCENT),
    FieldSpec("housing_pct", "% undergrads in college housing", "Campus culture", Kind.PERCENT),
    FieldSpec("undergrad_size", "Undergraduate enrollment", "Campus culture", Kind.COUNT),
    FieldSpec("athletics", "Athletic association", "Campus culture", Kind.TEXT),
    FieldSpec("study_abroad", "Study abroad offered", "Campus culture", Kind.BOOL),
    FieldSpec("retention_rate", "First-year retention", "Campus culture", Kind.PERCENT),
    FieldSpec("grad_rate_6yr", "6-year graduation rate", "Campus culture", Kind.PERCENT),
    FieldSpec("admission_factors", "Admission factor importance", "Selectivity", Kind.MAP),
]

FIELDS: dict[str, FieldSpec] = {s.key: s for s in _SPECS}

GPA_BINS: tuple[str, ...] = (
    "4.0",
    "3.75-3.99",
    "3.50-3.74",
    "3.25-3.49",
    "3.00-3.24",
    "2.50-2.99",
    "2.00-2.49",
    "1.00-1.99",
    "<1.00",
)
# (low, high) GPA bounds for each bin, used for percentile interpolation.
GPA_BIN_BOUNDS: dict[str, tuple[float, float]] = {
    "4.0": (4.0, 4.0),
    "3.75-3.99": (3.75, 3.99),
    "3.50-3.74": (3.50, 3.74),
    "3.25-3.49": (3.25, 3.49),
    "3.00-3.24": (3.00, 3.24),
    "2.50-2.99": (2.50, 2.99),
    "2.00-2.49": (2.00, 2.49),
    "1.00-1.99": (1.00, 1.99),
    "<1.00": (0.0, 0.99),
}

ADMISSION_FACTORS: tuple[str, ...] = (
    "Rigor of secondary school record",
    "Class rank",
    "Academic GPA",
    "Standardized test scores",
    "Application essay",
    "Recommendation(s)",
    "Interview",
    "Extracurricular activities",
    "Talent/ability",
    "Character/personal qualities",
    "First generation",
    "Alumni/ae relation",
    "Geographical residence",
    "State residency",
    "Religious affiliation/commitment",
    "Volunteer work",
    "Work experience",
    "Level of applicant's interest",
)
IMPORTANCE_LEVELS: tuple[str, ...] = ("Very Important", "Important", "Considered", "Not Considered")


@dataclass
class CollegeRecord:
    unitid: int
    name: str
    fields: dict[str, FieldValue] = field(default_factory=dict)
    links: dict[str, str] = field(default_factory=dict)
    source_status: dict[str, FieldValue] = field(default_factory=dict)

    def get(self, key: str) -> FieldValue:
        return self.fields.get(key) or FieldValue.missing()

    def value(self, key: str) -> object | None:
        fv = self.fields.get(key)
        return fv.value if fv is not None and fv.ok else None

    def num(self, key: str) -> float | None:
        v = self.value(key)
        if isinstance(v, bool) or not isinstance(v, int | float):
            return None
        return float(v)

    def coverage(self) -> dict[str, bool]:
        return {k: self.get(k).ok for k in FIELDS}

    def worst_status(self) -> Status:
        statuses = {fv.status for fv in self.source_status.values()}
        for s in (Status.SOURCE_UNAVAILABLE, Status.RATE_LIMITED, Status.AUTH_MISSING, Status.PARSE_FAILED):
            if s in statuses:
                return s
        return Status.OK
