"""Merge adapter results field-by-field using the PLAN §2 priority order (PLAN §5.1 rule 8)."""

from __future__ import annotations

from cfa.models.college import FIELDS, CollegeRecord
from cfa.models.field_value import FieldValue, Status
from cfa.sources.base import FetchResult

URBAN = "IPEDS (Urban)"
SCORECARD = "College Scorecard"
CDS = "Common Data Set"
DERIVED = "Derived"

# Field -> sources in priority order. Fields listed together in GROUPS must come from one source.
PRIORITY: dict[str, tuple[str, ...]] = {
    "name": (URBAN, SCORECARD),
    "address": (URBAN,),
    "city": (URBAN, SCORECARD),
    "state": (URBAN, SCORECARD),
    "zip": (URBAN, SCORECARD),
    "phone": (URBAN,),
    "website": (URBAN, SCORECARD),
    "locale": (URBAN, SCORECARD),
    "setting": (URBAN, SCORECARD),
    "control": (URBAN,),
    **{
        f"{k}_{g}": (CDS, URBAN)
        for k in ("applicants", "admits")
        for g in ("total", "men", "women", "another")
    },
    **{
        k: (CDS,)
        for k in (
            "ed_offered",
            "ed_applicants",
            "ed_admits",
            "ed_rate",
            "ea_offered",
            "ea_applicants",
            "ea_admits",
            "ea_rate",
        )
    },
    "gpa_avg": (CDS,),
    "gpa_dist": (CDS,),
    **{
        k: (CDS, URBAN, SCORECARD)
        for k in ("sat_ebrw_25", "sat_ebrw_75", "sat_math_25", "sat_math_75", "act_25", "act_75")
    },
    "sat_submit_pct": (CDS, URBAN),
    "act_submit_pct": (CDS, URBAN),
    "test_policy": (CDS, URBAN, SCORECARD),
    "greek_men_pct": (CDS,),
    "greek_women_pct": (CDS,),
    "housing_pct": (CDS,),
    "undergrad_size": (SCORECARD, URBAN),
    "athletics": (URBAN,),
    "study_abroad": (CDS, URBAN),
    "retention_rate": (CDS, URBAN, SCORECARD),
    "grad_rate_6yr": (CDS, URBAN, SCORECARD),
    "admission_factors": (CDS,),
    "tuition_in_state": (SCORECARD, URBAN),
    "tuition_out_state": (SCORECARD, URBAN),
    **{
        k: (SCORECARD,)
        for k in ("cost_attendance", "net_price_avg", "net_price_by_income", "pell_rate", "median_debt")
    },
    **{
        k: (CDS,)
        for k in (
            "need_grant_pct",
            "need_met_pct",
            "avg_aid_package",
            "avg_need_grant",
            "merit_aid_pct",
            "avg_merit_award",
        )
    },
}

GROUPS: tuple[tuple[str, ...], ...] = (
    ("sat_ebrw_25", "sat_ebrw_75"),
    ("sat_math_25", "sat_math_75"),
    ("act_25", "act_75"),
    ("applicants_total", "admits_total"),
    ("applicants_men", "admits_men"),
    ("applicants_women", "admits_women"),
    ("applicants_another", "admits_another"),
)

# CDS counts that disagree with IPEDS by more than this factor are treated as unreliable.
CROSSCHECK_RATIO = 1.5


def _pick_missing(candidates: list[FieldValue]) -> FieldValue:
    if not candidates:
        return FieldValue.missing()
    for fv in candidates:  # a retryable failure is the most useful thing to show
        if fv.status in (Status.SOURCE_UNAVAILABLE, Status.RATE_LIMITED):
            return fv
    return candidates[0]


def _by_source(results: list[FetchResult]) -> dict[str, FetchResult]:
    return {r.source: r for r in results}


def merge(
    unitid: int, fallback_name: str, results: list[FetchResult], links: dict[str, str] | None = None
) -> CollegeRecord:
    src = _by_source(results)
    fields: dict[str, FieldValue] = {}

    def get(source: str, key: str) -> FieldValue | None:
        r = src.get(source)
        return r.data.get(key) if r else None

    done: set[str] = set()
    for group in GROUPS:
        order = PRIORITY[group[0]]
        chosen = None
        for s in order:
            vals = [get(s, k) for k in group]
            if all(v is not None and v.ok for v in vals):
                chosen = s
                break
        if chosen:
            for k in group:
                fields[k] = get(chosen, k)  # type: ignore[assignment]
            done.update(group)

    for key, order in PRIORITY.items():
        if key in done:
            continue
        cands = [fv for s in order if (fv := get(s, key)) is not None]
        fields[key] = next((fv for fv in cands if fv.ok), None) or _pick_missing(cands)

    sc_rate = get(SCORECARD, "acceptance_rate")
    if sc_rate is not None:
        fields["acceptance_rate"] = sc_rate
    _crosscheck_counts(fields, src)
    _derive(fields)
    if not fields["name"].ok:
        fields["name"] = FieldValue.of(fallback_name, "Registry", None)
    for key in FIELDS:
        fields.setdefault(key, FieldValue.missing())
    record = CollegeRecord(unitid, str(fields["name"].value), fields, dict(links or {}))
    record.source_status = {r.source: r.as_field() for r in results}
    return record


def _crosscheck_counts(fields: dict[str, FieldValue], src: dict[str, FetchResult]) -> None:
    """Guard against typos in a school's CDS by comparing totals with IPEDS (PLAN R3)."""
    cds_apps = fields.get("applicants_total")
    urban = src.get(URBAN)
    if cds_apps is None or not cds_apps.ok or cds_apps.source != CDS or urban is None:
        return
    ipeds = urban.data.get("applicants_total")
    if ipeds is None or not ipeds.ok or not ipeds.value:
        return
    ratio = cds_apps.value / ipeds.value
    if 1 / CROSSCHECK_RATIO <= ratio <= CROSSCHECK_RATIO:
        return
    note = "CDS applicant count disagrees with IPEDS; showing IPEDS"
    for g in ("total", "men", "women", "another"):
        for kind in ("applicants", "admits"):
            k = f"{kind}_{g}"
            alt = urban.data.get(k)
            fields[k] = (
                FieldValue(alt.value, alt.source, alt.year, alt.status, note)
                if alt is not None
                else FieldValue.missing(URBAN, Status.NOT_REPORTED, note)
            )


def _derive(fields: dict[str, FieldValue]) -> None:
    apps, admits = fields["applicants_total"], fields["admits_total"]
    if apps.ok and admits.ok and apps.value > 0 and apps.source == admits.source:
        rate = round(100 * admits.value / apps.value, 1)
        fields["acceptance_rate"] = FieldValue(
            rate, f"{DERIVED} from {apps.source}", apps.year, Status.OK, "Admitted ÷ applicants"
        )
    elif "acceptance_rate" not in fields:
        fields["acceptance_rate"] = FieldValue.missing(
            DERIVED, Status.NOT_REPORTED, "Applicant/admit counts unavailable"
        )
    _derive_rd(fields)


def _plan_counts(fields: dict[str, FieldValue], prefix: str) -> tuple[int, int] | None:
    """(applicants, admits) for an early plan; (0, 0) when the school says it has no such plan."""
    offered = fields.get(f"{prefix}_offered")
    if offered is None or not offered.ok:
        return None
    if offered.value is False:
        return 0, 0
    a, d = fields.get(f"{prefix}_applicants"), fields.get(f"{prefix}_admits")
    if a is None or d is None or not (a.ok and d.ok):
        return None
    return int(a.value), int(d.value)


def _derive_rd(fields: dict[str, FieldValue]) -> None:
    apps, admits = fields["applicants_total"], fields["admits_total"]
    missing = FieldValue.missing(DERIVED, Status.NOT_REPORTED, "Needs total, ED and EA counts")
    for k in ("rd_applicants", "rd_admits", "rd_rate"):
        fields[k] = missing
    if not (apps.ok and admits.ok and apps.source == CDS and admits.source == CDS):
        return
    ed, ea = _plan_counts(fields, "ed"), _plan_counts(fields, "ea")
    if ed is None or ea is None:
        return
    rd_apps = int(apps.value) - ed[0] - ea[0]
    rd_admits = int(admits.value) - ed[1] - ea[1]
    if rd_apps <= 0 or rd_admits < 0 or rd_admits > rd_apps:
        fields["rd_applicants"] = fields["rd_admits"] = fields["rd_rate"] = FieldValue.missing(
            DERIVED, Status.PARSE_FAILED, "Early-round counts are inconsistent with totals"
        )
        return
    note = "Estimated: total minus ED and EA"
    fields["rd_applicants"] = FieldValue(rd_apps, DERIVED, apps.year, Status.OK, note, True)
    fields["rd_admits"] = FieldValue(rd_admits, DERIVED, apps.year, Status.OK, note, True)
    fields["rd_rate"] = FieldValue(
        round(100 * rd_admits / rd_apps, 1), DERIVED, apps.year, Status.OK, note, True
    )
