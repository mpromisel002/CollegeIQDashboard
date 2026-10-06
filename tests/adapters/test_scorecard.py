import json

import respx

from cfa.models.field_value import Status
from cfa.sources.scorecard import ScorecardAdapter
from tests.conftest import API

URL = "https://api.data.gov/ed/collegescorecard/v1/schools"


@respx.mock
async def test_recorded_fixture(http):
    respx.get(url__startswith=URL).respond(200, json=json.loads((API / "scorecard_100751.json").read_text()))
    res = await ScorecardAdapter(http, "KEY").fetch(100751)
    assert res.status is Status.OK
    assert res.data["acceptance_rate"].value == 76.6
    assert res.data["undergrad_size"].value == 33227
    assert res.data["zip"].value == "35487"
    assert res.data["setting"].value == "City"
    assert res.data["test_policy"].value == "Considered but not required"
    assert res.data["act_75"].value == 31


@respx.mock
async def test_privacy_suppressed(http):
    respx.get(url__startswith=URL).respond(
        200,
        json={
            "results": [
                {
                    "latest.admissions.admission_rate.overall": "PrivacySuppressed",
                    "latest.student.size": None,
                    "school.name": "X",
                }
            ]
        },
    )
    res = await ScorecardAdapter(http, "KEY").fetch(1)
    assert res.status is Status.PARTIAL
    assert res.data["acceptance_rate"].value is None
    assert res.data["acceptance_rate"].status is Status.NOT_REPORTED


async def test_no_key(http):
    res = await ScorecardAdapter(http, None).fetch(1)
    assert res.status is Status.AUTH_MISSING
    assert res.data["undergrad_size"].status is Status.AUTH_MISSING
    assert (await ScorecardAdapter(http, None).health_check()).status is Status.AUTH_MISSING


@respx.mock
async def test_bad_key(http):
    respx.get(url__startswith=URL).respond(403, json={"error": {"code": "API_KEY_INVALID"}})
    assert (await ScorecardAdapter(http, "BAD").fetch(1)).status is Status.AUTH_MISSING


@respx.mock
async def test_not_found_and_bad_json(http):
    respx.get(url__startswith=URL).respond(200, json={"metadata": {}, "results": []})
    assert (await ScorecardAdapter(http, "K").fetch(1)).status is Status.NOT_REPORTED
    respx.get(url__startswith=URL).respond(200, content=b"not json")
    assert (await ScorecardAdapter(http, "K").fetch(2)).status is Status.PARSE_FAILED


@respx.mock
async def test_out_of_range_values_dropped(http):
    respx.get(url__startswith=URL).respond(
        200,
        json={
            "results": [
                {
                    "latest.admissions.sat_scores.25th_percentile.math": 1200,
                    "latest.admissions.admission_rate.overall": 1.7,
                }
            ]
        },
    )
    res = await ScorecardAdapter(http, "K").fetch(1)
    assert res.data["sat_math_25"].value is None and res.data["acceptance_rate"].value is None
