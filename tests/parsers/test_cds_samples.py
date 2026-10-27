"""Parser tests on real Common Data Set files. Expected values were checked by hand against
each document (text layer, rendered page, or filled form-field values)."""

from functools import cache

import pytest

from cfa.models.field_value import Status
from cfa.sources.cds.adapter import parse_document
from tests.conftest import CDS


@cache
def parsed(name: str):
    fmt = "xlsx" if name.endswith(".xlsx") else "pdf"
    sections, err = parse_document((CDS / name).read_bytes(), fmt, "2025-2026")
    assert not err
    return {k: fv for s in sections.values() for k, fv in s.fields.items()}, sections


def val(name, key):
    fields, _ = parsed(name)
    return fields[key].value if fields[key].ok else fields[key].status


EXPECTED = {
    "alabama_2025-26.pdf": {
        "applicants_total": 61994,
        "applicants_men": 25528,
        "applicants_women": 36466,
        "applicants_another": 0,
        "admits_total": 44124,
        "admits_men": 17977,
        "admits_women": 26147,
        "sat_ebrw_25": 560,
        "sat_ebrw_75": 680,
        "sat_math_25": 530,
        "sat_math_75": 680,
        "act_25": 22,
        "act_75": 31,
        "sat_submit_pct": 19.0,
        "act_submit_pct": 53.0,
        "gpa_avg": 3.85,
        "greek_men_pct": 30.1,
        "greek_women_pct": 44.1,
        "housing_pct": 26.4,
        "retention_rate": 88.0,
        "grad_rate_6yr": 73.7,
        "ed_offered": False,
        "ea_offered": False,
        "study_abroad": True,
        "test_policy": "Considered if submitted (test-optional)",
    },
    "dartmouth_2025-26.pdf": {
        "applicants_total": 28230,
        "applicants_men": 14155,
        "applicants_women": 14063,
        "admits_total": 1699,
        "admits_men": 917,
        "admits_women": 782,
        "ed_offered": True,
        "ed_applicants": 3552,
        "ed_admits": 768,
        "ed_rate": 21.6,
        "sat_math_25": 720,
        "sat_math_75": 790,
        "act_25": 32,
        "act_75": 35,
        "greek_men_pct": 26.0,
        "greek_women_pct": 29.0,
        "housing_pct": 85.0,
        "test_policy": "Required",
        "gpa_dist": Status.NOT_REPORTED,
        "gpa_avg": Status.NOT_REPORTED,
    },
    "rice_2025-26.pdf": {
        "applicants_total": 36791,
        "admits_total": 2948,
        "ed_applicants": 5748,
        "ed_admits": 647,
        "sat_math_25": 760,
        "sat_math_75": 800,
        "act_25": 34,
        "act_75": 36,
        "greek_men_pct": 0.0,
        "greek_women_pct": 0.0,
        "housing_pct": 59.0,
        "test_policy": "Recommended",
    },
    "duke_2025-26.pdf": {
        "applicants_total": 55541,
        "applicants_men": 25641,
        "applicants_women": 29900,
        "admits_total": 2910,
        "ed_offered": True,
        "ed_applicants": Status.NOT_REPORTED,
        "sat_math_25": 770,
        "sat_math_75": 790,
        "greek_men_pct": 30.0,
        "greek_women_pct": 42.0,
        "test_policy": "Considered if submitted (test-optional)",
    },
    "montana_2025-26.pdf": {  # filled AcroForm: values come from form fields
        "applicants_men": 3900,
        "applicants_women": 5180,
        "admits_men": 3643,
        "admits_women": 5000,
        "act_25": 19,
        "act_75": 26,
        "sat_submit_pct": 10.0,
        "gpa_avg": 3.41,
        "greek_men_pct": 6.0,
        "greek_women_pct": 6.0,
        "housing_pct": 42.0,
        # Only the "students who submitted scores" GPA column was filled, never the "all students" one.
        "gpa_dist": Status.NOT_REPORTED,
    },
    "vanderbilt_2025-26.xlsx": {
        "applicants_total": 48196,
        "applicants_men": 21595,
        "applicants_women": 26601,
        "admits_total": 2593,
        "ed_applicants": 6202,
        "sat_math_25": 770,
        "sat_math_75": 790,
        "act_25": 34,
        "act_75": 35,
        "sat_submit_pct": 24.0,
        "gpa_avg": 3.9,
        "greek_men_pct": 27.4,
        "greek_women_pct": 31.6,
        "test_policy": "Considered if submitted (test-optional)",
    },
    "purdue_2025-26.xlsx": {
        "sat_math_25": 600,
        "sat_math_75": 760,
        "act_25": 28,
        "act_75": 34,
        "sat_submit_pct": 83.8,
        "greek_men_pct": 15.0,
        "greek_women_pct": 17.2,
        "gpa_avg": 3.81,
        "ed_offered": False,
    },
}
CASES = [(f, k, v) for f, exp in EXPECTED.items() for k, v in exp.items()]


@pytest.mark.parametrize("name,key,expected", CASES, ids=[f"{f}:{k}" for f, k, _ in CASES])
def test_expected_values(name, key, expected):
    assert val(name, key) == expected


def test_alabama_gpa_distribution_all_students_column():
    d = val("alabama_2025-26.pdf", "gpa_dist")
    assert d["4.0"] == 40 and d["3.75-3.99"] == 19 and d["3.50-3.74"] == 17 and d["2.50-2.99"] == 3
    assert 99 <= sum(d.values()) <= 101


def test_xlsx_fraction_gpa_distribution_scaled_to_percent():
    assert val("vanderbilt_2025-26.xlsx", "gpa_dist")["4.0"] == 31.6
    assert val("purdue_2025-26.xlsx", "gpa_dist")["4.0"] == 42.66


def test_alabama_admission_factors_match_rendered_grid():
    f = val("alabama_2025-26.pdf", "admission_factors")
    assert f["Rigor of secondary school record"] == "Very Important"
    assert f["Class rank"] == "Considered"
    assert f["Extracurricular activities"] == "Important"
    assert f["Volunteer work"] == "Important"
    assert f["Religious affiliation/commitment"] == "Not Considered"
    assert f["Level of applicant's interest"] == "Not Considered"
    assert len(f) == 18


def test_every_sample_has_no_parse_crash():
    for name in EXPECTED:
        _, sections = parsed(name)
        assert set(sections) >= {"C1", "C7", "C8", "C9", "C11", "C12", "C21", "C22", "E1", "F1", "B22", "B11"}


# H2/H2A (first-time, full-time first-years), checked by hand against each document.
H2_EXPECTED = {
    "alabama_2025-26.pdf": {  # A 7,973; E 3,433; N 3,206
        "need_grant_pct": 43.1,
        "need_met_pct": 62.7,
        "avg_aid_package": 19857,
        "avg_need_grant": 17406,
        "merit_aid_pct": 40.2,
        "avg_merit_award": 16895,
    },
    "purdue_2025-26.xlsx": {  # A 11,339; E 2,742; I 65.2718%; N 2,358
        "need_grant_pct": 24.2,
        "need_met_pct": 65.3,
        "avg_aid_package": 14569,
        "avg_need_grant": 13698,
        "merit_aid_pct": 20.8,
        "avg_merit_award": 5789,
    },
}


@pytest.mark.parametrize(
    "name,key,expected", [(f, k, v) for f, e in H2_EXPECTED.items() for k, v in e.items()]
)
def test_h2_aid_values(name, key, expected):
    assert val(name, key) == expected


def test_h2_absent_section_is_not_reported():
    _, sections = parsed("montana_2025-26.pdf")  # Montana's CDS has no part H
    assert sections["H2"].status is Status.NOT_REPORTED
