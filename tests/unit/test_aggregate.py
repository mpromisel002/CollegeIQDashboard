from cfa.aggregate import CDS, SCORECARD, URBAN, merge
from cfa.models.field_value import FieldValue, Status
from cfa.sources.base import FetchResult


def res(source, status=Status.OK, **values):
    return FetchResult(source, status, {k: FieldValue.of(v, source, "2025") for k, v in values.items()})


def test_priority_and_computed_rate():
    rec = merge(
        1,
        "X",
        [
            res(URBAN, name="Urban Name", applicants_total=1000, admits_total=400),
            res(CDS, applicants_total=1100, admits_total=330),
            res(SCORECARD, acceptance_rate=50.0, undergrad_size=9000),
        ],
    )
    assert rec.name == "Urban Name"
    assert rec.get("applicants_total").source == CDS
    assert rec.get("acceptance_rate").value == 30.0
    assert rec.get("undergrad_size").source == SCORECARD


def test_scorecard_rate_fallback():
    rec = merge(1, "X", [res(SCORECARD, acceptance_rate=42.0)])
    assert rec.get("acceptance_rate").value == 42.0


def test_groups_come_from_one_source():
    rec = merge(1, "X", [res(CDS, sat_math_25=600), res(URBAN, sat_math_25=610, sat_math_75=700)])
    assert rec.get("sat_math_25").value == 610 and rec.get("sat_math_75").value == 700


def test_crosscheck_replaces_cds_typo_with_ipeds():
    rec = merge(
        1,
        "X",
        [
            res(URBAN, applicants_total=35000, admits_total=29000),
            res(CDS, applicants_total=195000, admits_total=29700),
        ],
    )
    assert rec.get("applicants_total").source == URBAN
    assert "disagrees" in rec.get("applicants_total").note


def test_unavailable_status_surfaces_for_retry():
    urban = FetchResult(
        URBAN,
        Status.SOURCE_UNAVAILABLE,
        {"city": FieldValue.missing(URBAN, Status.SOURCE_UNAVAILABLE, "down")},
    )
    sc = FetchResult(
        SCORECARD, Status.AUTH_MISSING, {"city": FieldValue.missing(SCORECARD, Status.AUTH_MISSING, "no key")}
    )
    rec = merge(1, "Fallback", [urban, sc])
    assert rec.get("city").status is Status.SOURCE_UNAVAILABLE
    assert rec.name == "Fallback"


def test_rd_estimate():
    rec = merge(
        1,
        "X",
        [
            res(
                CDS,
                applicants_total=1000,
                admits_total=300,
                ed_offered=True,
                ed_applicants=100,
                ed_admits=50,
                ea_offered=False,
            )
        ],
    )
    rd = rec.get("rd_applicants")
    assert rd.value == 900 and rd.estimated
    assert rec.get("rd_admits").value == 250
    assert rec.get("rd_rate").value == round(100 * 250 / 900, 1)


def test_rd_needs_all_inputs():
    rec = merge(1, "X", [res(CDS, applicants_total=1000, admits_total=300, ed_offered=True)])
    assert not rec.get("rd_applicants").ok
