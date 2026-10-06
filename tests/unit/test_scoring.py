import pytest

from cfa.models.student import Athletics, GreekDirection, Setting, SizePref, StudentProfile
from cfa.scoring import academic, culture
from tests.conftest import make_record

DIST = {
    "4.0": 20,
    "3.75-3.99": 30,
    "3.50-3.74": 25,
    "3.25-3.49": 15,
    "3.00-3.24": 10,
    "2.50-2.99": 0,
    "2.00-2.49": 0,
    "1.00-1.99": 0,
    "<1.00": 0,
}


def school(**kw):
    base = dict(
        acceptance_rate=60.0,
        gpa_dist=DIST,
        sat_ebrw_25=550,
        sat_ebrw_75=650,
        sat_math_25=550,
        sat_math_75=650,
        act_25=24,
        act_75=30,
    )
    base.update(kw)
    return make_record(**base)


def test_gpa_percentile_interpolates():
    assert academic.gpa_percentile(3.0, DIST) == 0.0
    assert academic.gpa_percentile(3.25, DIST) == 10.0
    assert academic.gpa_percentile(3.375, DIST) == 17.5
    assert academic.gpa_percentile(4.0, DIST) == 90.0  # mid-rank within the 4.0 bin


def test_reach_by_admit_rate_regardless_of_stats():
    s = StudentProfile(gpa_unweighted=4.0, sat_ebrw=800, sat_math=800)
    fit = academic.classify(s, school(acceptance_rate=9.0))
    assert fit.tier == academic.REACH and "admit rate 9% (<15%)" in fit.reason


def test_reach_by_low_tests():
    s = StudentProfile(gpa_unweighted=3.9, sat_ebrw=450, sat_math=450)
    assert academic.classify(s, school()).tier == academic.REACH


def test_reach_by_bottom_quartile_gpa():
    s = StudentProfile(gpa_unweighted=3.1, submits_tests=False)
    assert academic.classify(s, school()).tier == academic.REACH


def test_safety():
    s = StudentProfile(gpa_unweighted=4.0, sat_ebrw=700, sat_math=700)
    fit = academic.classify(s, school())
    assert fit.tier == academic.SAFETY, fit.reason


def test_safety_test_optional_requires_top_gpa():
    assert (
        academic.classify(StudentProfile(gpa_unweighted=4.0, submits_tests=False), school()).tier
        == academic.SAFETY
    )
    # ~68th percentile: above the median but not in the top quarter
    assert (
        academic.classify(StudentProfile(gpa_unweighted=3.9, submits_tests=False), school()).tier
        == academic.TARGET
    )


def test_target_when_middle():
    s = StudentProfile(gpa_unweighted=3.6, sat_ebrw=600, sat_math=600)
    assert academic.classify(s, school()).tier == academic.TARGET


def test_target_when_selective_but_not_reach():
    s = StudentProfile(gpa_unweighted=3.9, sat_ebrw=700, sat_math=700)
    assert academic.classify(s, school(acceptance_rate=30.0)).tier == academic.TARGET


def test_unclassified_without_admit_rate():
    s = StudentProfile(gpa_unweighted=3.9, sat_ebrw=700, sat_math=700)
    rec = make_record(gpa_dist=DIST)
    assert academic.classify(s, rec).tier == academic.UNCLASSIFIED


def test_unclassified_without_gpa_or_tests():
    s = StudentProfile(gpa_unweighted=3.9, submits_tests=False)
    assert academic.classify(s, make_record(acceptance_rate=60.0)).tier == academic.UNCLASSIFIED


def test_act_used_when_better_than_sat():
    s = StudentProfile(gpa_unweighted=3.9, sat_ebrw=500, sat_math=500, act=32)
    assert academic.classify(s, school()).test_position == academic.ABOVE


# ------------------------------------------------------------------ culture


def test_culture_no_preferences():
    assert culture.score(StudentProfile(), school()).score is None


def test_culture_greek_wants_and_avoids():
    rec = make_record(greek_men_pct=30.0, greek_women_pct=30.0)
    wants = StudentProfile(greek_direction=GreekDirection.WANTS, greek_importance=3)
    avoids = StudentProfile(greek_direction=GreekDirection.AVOIDS, greek_importance=3)
    assert culture.score(wants, rec).score == 100
    assert culture.score(avoids, rec).score == 0


def test_culture_setting_adjacency_and_size():
    rec = make_record(setting="Suburb", undergrad_size=20000)
    s = StudentProfile(
        setting_pref=Setting.CITY, setting_importance=1, size_pref=SizePref.LARGE, size_importance=1
    )
    fit = culture.score(s, rec)
    assert fit.parts == {"Setting": 50.0, "Size": 100.0}
    assert fit.score == 75.0


def test_culture_weights():
    rec = make_record(housing_pct=40.0, state="AL", study_abroad=True)
    s = StudentProfile(
        housing_importance=1, preferred_states=["TN"], region_importance=3, study_abroad_importance=0
    )
    assert culture.score(s, rec).score == pytest.approx((40 * 1 + 0 * 3) / 4)


def test_culture_missing_data_not_scored():
    rec = make_record(setting="City")
    s = StudentProfile(
        setting_pref=Setting.CITY, setting_importance=2, athletics_pref=Athletics.NCAA, athletics_importance=3
    )
    fit = culture.score(s, rec)
    assert fit.score == 100.0
    assert fit.not_scored == ["Athletics"]
    assert "not scored: Athletics" in fit.explain()


def test_size_band():
    assert culture.size_band(4999) is SizePref.SMALL
    assert culture.size_band(5000) is SizePref.MEDIUM
    assert culture.size_band(30000) is SizePref.HUGE
