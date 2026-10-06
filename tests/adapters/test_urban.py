import json
import re

import httpx
import respx

from cfa.models.field_value import Status
from cfa.sources.urban_ipeds import UrbanIpedsAdapter
from tests.conftest import API

BASE = "https://educationdata.urban.org/api/v1/college-university/ipeds"
PATTERN = re.compile(r"/ipeds/([a-z-]+)/(\d{4})/(?:undergraduate/)?")


def fixture_router(request: httpx.Request) -> httpx.Response:
    m = PATTERN.search(request.url.path)
    unitid = request.url.params.get("unitid")
    path = API / f"urban_{m.group(1)}_{m.group(2)}_{unitid}.json"
    if path.exists():
        return httpx.Response(200, json=json.loads(path.read_text()))
    return httpx.Response(200, json={"count": 0, "next": None, "previous": None, "results": []})


@respx.mock
async def test_alabama_from_recorded_fixtures(http):
    respx.get(url__startswith=BASE).mock(side_effect=fixture_router)
    res = await UrbanIpedsAdapter(http, this_year=2026).fetch(100751)
    assert res.status is Status.PARTIAL  # IPEDS has no "gender not identified" counts for Alabama
    d = res.data
    assert d["applicants_another"].status is Status.NOT_REPORTED
    assert d["name"].value == "The University of Alabama"
    assert d["state"].value == "AL" and d["setting"].ok
    assert d["applicants_total"].ok and d["admits_total"].value <= d["applicants_total"].value
    assert d["applicants_total"].year == "2024"
    assert d["sat_math_25"].year == "2022"  # walked back four years to find data
    assert d["athletics"].value == "NCAA"
    assert 0 < d["retention_rate"].value <= 100
    assert 0 < d["grad_rate_6yr"].value <= 100
    assert d["undergrad_size"].value > 1000


@respx.mock
async def test_year_discovery_cached(http):
    route = respx.get(url__startswith=BASE).mock(side_effect=fixture_router)
    adapter = UrbanIpedsAdapter(http, this_year=2026)
    await adapter.fetch(100751)
    first = route.call_count
    adapter.cache.pop(("urban", 100751))
    await adapter.fetch(100751)
    assert route.call_count - first < first  # later fetches start at the discovered year


@respx.mock
async def test_no_data_any_year(http):
    respx.get(url__startswith=BASE).respond(200, json={"count": 0, "next": None, "results": []})
    res = await UrbanIpedsAdapter(http, this_year=2026).fetch(999999)
    assert res.status is Status.NOT_REPORTED
    assert res.data["city"].status is Status.NOT_REPORTED


@respx.mock
async def test_bad_json(http):
    respx.get(url__startswith=BASE).respond(200, content=b"<html>oops</html>")
    res = await UrbanIpedsAdapter(http, this_year=2026).fetch(100751)
    assert res.status is Status.PARSE_FAILED
    assert all(not fv.ok for fv in res.data.values())


@respx.mock
async def test_sentinels_never_numbers(http):
    row = {"unitid": 1, "year": 2025, "sex": 99, "number_applied": -1, "number_admitted": -2}

    def router(request):
        if "admissions-enrollment" in request.url.path:
            return httpx.Response(200, json={"count": 1, "next": None, "results": [row]})
        return httpx.Response(200, json={"count": 0, "next": None, "results": []})

    respx.get(url__startswith=BASE).mock(side_effect=router)
    res = await UrbanIpedsAdapter(http, this_year=2026).fetch(1)
    assert res.data["applicants_total"].value is None
    assert res.data["applicants_total"].status is Status.NOT_REPORTED


@respx.mock
async def test_admits_exceeding_applicants_rejected(http):
    row = {"unitid": 1, "year": 2025, "sex": 99, "number_applied": 10, "number_admitted": 50}

    def router(request):
        if "admissions-enrollment" in request.url.path:
            return httpx.Response(200, json={"count": 1, "next": None, "results": [row]})
        return httpx.Response(200, json={"count": 0, "next": None, "results": []})

    respx.get(url__startswith=BASE).mock(side_effect=router)
    res = await UrbanIpedsAdapter(http, this_year=2026).fetch(1)
    assert res.data["admits_total"].status is Status.PARSE_FAILED


@respx.mock
async def test_pagination_followed(http):
    page2 = f"{BASE}/grad-rates/2025/?unitid=1&page=2"
    rows = [{"subcohort": 2, "race": 99, "sex": 99, "completion_rate_150pct": 0.81}]

    def router(request):
        if "grad-rates" in request.url.path and request.url.params.get("page") == "2":
            return httpx.Response(200, json={"count": 2, "next": None, "results": rows})
        if "grad-rates" in request.url.path and "2025" in request.url.path:
            return httpx.Response(200, json={"count": 2, "next": page2, "results": [{"subcohort": 1}]})
        return httpx.Response(200, json={"count": 0, "next": None, "results": []})

    respx.get(url__startswith=BASE).mock(side_effect=router)
    res = await UrbanIpedsAdapter(http, this_year=2026).fetch(1)
    assert res.data["grad_rate_6yr"].value == 81.0


@respx.mock
async def test_source_down(http):
    respx.get(url__startswith=BASE).respond(503)
    res = await UrbanIpedsAdapter(http, this_year=2026).fetch(100751)
    assert res.status is Status.SOURCE_UNAVAILABLE
    assert res.data["name"].status is Status.SOURCE_UNAVAILABLE


@respx.mock
async def test_health_check(http):
    respx.get("https://educationdata.urban.org/api/v1/api-endpoints/").respond(200, json={})
    assert (await UrbanIpedsAdapter(http).health_check()).status is Status.OK
