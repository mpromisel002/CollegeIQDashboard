import json

import pytest
from pydantic import ValidationError

from cfa.models.college import FIELDS, GPA_BINS
from cfa.models.field_value import FieldValue, Status
from cfa.models.student import StudentProfile
from tests.conftest import make_record


def test_field_value_of_none_is_not_reported():
    fv = FieldValue.of(None, "X", "2024")
    assert fv.status is Status.NOT_REPORTED and not fv.ok


def test_field_value_badge():
    assert FieldValue.of(5, "IPEDS", "2024").badge() == "IPEDS 2024"
    assert FieldValue.missing("IPEDS", Status.SOURCE_UNAVAILABLE).badge() == "Source unavailable"


def test_record_num_ignores_bool_and_missing():
    rec = make_record(acceptance_rate=12.5, study_abroad=True)
    assert rec.num("acceptance_rate") == 12.5
    assert rec.num("study_abroad") is None
    assert rec.num("gpa_avg") is None
    assert rec.get("gpa_avg").status is Status.NOT_REPORTED


def test_gpa_bins_match_spec():
    assert GPA_BINS[0] == "4.0" and GPA_BINS[-1] == "<1.00" and len(GPA_BINS) == 9
    assert "gpa_dist" in FIELDS


def test_profile_roundtrip(tmp_path):
    p = StudentProfile(name="A", gpa_unweighted=3.7, sat_ebrw=650, sat_math=700, preferred_states="al, tn")
    assert p.preferred_states == ["AL", "TN"]
    assert p.sat_total == 1350
    path = tmp_path / "p.json"
    p.save(path)
    assert StudentProfile.load(path) == p
    assert json.loads(path.read_text())["gpa_unweighted"] == 3.7


@pytest.mark.parametrize(
    "field,value", [("gpa_unweighted", 4.5), ("sat_math", 900), ("act", 40), ("greek_importance", 4)]
)
def test_profile_validation(field, value):
    with pytest.raises(ValidationError):
        StudentProfile(**{field: value})
