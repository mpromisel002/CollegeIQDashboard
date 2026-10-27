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
    assert res.data["tuition_in_state"].value == 12484 and res.data["tuition_out_state"].value == 35342
    assert res.data["net_price_avg"].value == 20202
    assert res.data["net_price_by_income"].value["$0–30k"] == 18067  # a public school's bracket


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


@respx.mock
async def test_cost_fields_and_net_price_by_income(http):
    row = {
        "id": 211291,
        "latest.cost.tuition.in_state": 70576,
        "latest.cost.tuition.out_of_state": 70576,
        "latest.cost.attendance.academic_year": 87696,
        "latest.cost.avg_net_price.overall": 50021,
        "latest.aid.pell_grant_rate": 0.1477,
        "latest.aid.median_debt.completers.overall": 26486,
        "latest.cost.net_price.private.by_income_level.0-30000": 17578,
        "latest.cost.net_price.public.by_income_level.0-30000": None,
        "latest.cost.net_price.private.by_income_level.110001-plus": 67428,
        "latest.cost.net_price.private.by_income_level.48001-75000": "PrivacySuppressed",
    }
    respx.get(url__startswith=URL).respond(200, json={"results": [row]})
    d = (await ScorecardAdapter(http, "KEY").fetch(211291)).data
    assert d["tuition_in_state"].value == 70576 and d["cost_attendance"].value == 87696
    assert d["net_price_avg"].value == 50021 and d["median_debt"].value == 26486
    assert d["pell_rate"].value == 14.8
    assert d["net_price_by_income"].value == {"$0–30k": 17578, "$110k+": 67428}
