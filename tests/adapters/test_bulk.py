"""Bulk (many-school) loading: IPEDS by state, Scorecard by batches of ids, and run_search."""

import re

import httpx
import respx

from cfa.models.field_value import Status
from cfa.pipeline import run_search
from cfa.sources.registry import parse_registry
from cfa.sources.scorecard import ScorecardAdapter
from cfa.sources.urban_ipeds import UrbanIpedsAdapter, is_candidate_college

BASE = "https://educationdata.urban.org/api/v1/college-university/ipeds"
SCORECARD = "https://api.data.gov/ed/collegescorecard/v1/schools"
PATH = re.compile(r"/ipeds/([a-z-]+)/(\d{4})/")


def directory_row(unitid, name, state="PA", fips=42, **kw):
    row = {
        "unitid": unitid,
        "inst_name": name,
        "city": "Town",
        "state_abbr": state,
        "fips": fips,
        "sector": 2,
        "inst_category": 2,
        "currently_active_ipeds": 1,
        "cc_basic_2021": 21,
        "inst_control": 2,
        "urban_centric_locale": 21,
    }
    row.update(kw)
    return row


def adm(unitid, applied, admitted):
    return {"unitid": unitid, "sex": 99, "number_applied": applied, "number_admitted": admitted}


def router(tables):
    """tables: {(topic, year): rows}; missing => empty result. Records each request's query."""
    calls = []

    def handle(request: httpx.Request) -> httpx.Response:
        m = PATH.search(request.url.path)
        calls.append((m.group(1), int(m.group(2)), request.url.params.get("fips")))
        rows = tables.get((m.group(1), int(m.group(2))), [])
        return httpx.Response(200, json={"count": len(rows), "next": None, "results": rows})

    return handle, calls


@respx.mock
async def test_prefetch_serves_fetch_from_memory_and_fills_partial_years(http):
    tables = {
        ("directory", 2025): [directory_row(1, "Alpha"), directory_row(2, "Beta")],
        # 2025 is a partial release (only Alpha); Beta must come from 2024, not be "not reported"
        ("admissions-enrollment", 2025): [adm(1, 1000, 500)],
        ("admissions-enrollment", 2024): [adm(1, 900, 450), adm(2, 2000, 400)],
    }
    handle, calls = router(tables)
    route = respx.get(url__startswith=BASE).mock(side_effect=handle)
    urban = UrbanIpedsAdapter(http, this_year=2026)
    await urban.prefetch([42])
    assert {r["unitid"] for r in urban.directory_rows} == {1, 2}
    before = route.call_count
    a, b, c = await urban.fetch(1), await urban.fetch(2), await urban.fetch(3)
    assert route.call_count == before  # all answered from the bulk load
    assert a.data["applicants_total"].value == 1000 and a.data["applicants_total"].year == "2025"
    assert b.data["applicants_total"].value == 2000 and b.data["applicants_total"].year == "2024"
    assert a.data["name"].value == "Alpha" and a.data["control"].value == "Private nonprofit"
    assert c.data["name"].status is Status.NOT_REPORTED  # not in these states
    assert all(fips == "42" for _t, _y, fips in calls)


@respx.mock
async def test_prefetch_groups_states_for_the_whole_country(http):
    handle, calls = router({("directory", 2025): [directory_row(1, "Alpha")]})
    respx.get(url__startswith=BASE).mock(side_effect=handle)
    await UrbanIpedsAdapter(http, this_year=2026).prefetch(None)
    directory_scopes = {fips for t, y, fips in calls if t == "directory" and y == 2025}
    assert len(directory_scopes) == 6  # 56 states and territories, 10 per request
    assert all(len(s.split(",")) <= 10 for s in directory_scopes)


@respx.mock
async def test_prefetch_failure_does_not_fall_back_to_per_school_requests(http):
    route = respx.get(url__startswith=BASE).respond(503)
    urban = UrbanIpedsAdapter(http, this_year=2026)
    await urban.prefetch([42])
    before = route.call_count
    res = await urban.fetch(1)
    assert route.call_count == before
    assert res.status is Status.SOURCE_UNAVAILABLE
    assert urban.directory_rows == []


def test_candidate_colleges():
    assert is_candidate_college(directory_row(1, "Four-year private"))
    assert is_candidate_college(directory_row(1, "Public", sector=1))
    assert not is_candidate_college(directory_row(1, "For-profit", sector=3))
    assert not is_candidate_college(directory_row(1, "Two-year", sector=4, inst_category=4))
    assert not is_candidate_college(directory_row(1, "Graduate only", inst_category=1))
    assert not is_candidate_college(directory_row(1, "Closed", currently_active_ipeds=0))
    assert not is_candidate_college(directory_row(1, "Seminary", cc_basic_2021=24))
    assert not is_candidate_college(directory_row(1, "Law school", cc_basic_2021=31))


@respx.mock
async def test_scorecard_prefetch_batches_ids(http):
    def handle(request: httpx.Request) -> httpx.Response:
        ids = [int(i) for i in request.url.params["id"].split(",")]
        rows = [{"id": i, "school.name": f"S{i}", "latest.student.size": 100} for i in ids if i != 7]
        return httpx.Response(200, json={"metadata": {"total": len(rows)}, "results": rows})

    route = respx.get(url__startswith=SCORECARD).mock(side_effect=handle)
    sc = ScorecardAdapter(http, "KEY")
    await sc.prefetch(list(range(1, 151)))
    assert route.call_count == 2  # 150 schools, 100 per request
    before = route.call_count
    assert (await sc.fetch(5)).data["undergrad_size"].value == 100
    assert (await sc.fetch(7)).status is Status.NOT_REPORTED
    assert route.call_count == before


async def test_scorecard_prefetch_without_key_is_a_no_op(http):
    sc = ScorecardAdapter(http, None)
    await sc.prefetch([1, 2])
    assert (await sc.fetch(1)).status is Status.AUTH_MISSING


REG = parse_registry("""
schema_version: 1
schools:
  - unitid: 3
    name: Gamma College
""")


@respx.mock
async def test_run_search_lists_every_college_in_the_states(http):
    tables = {
        ("directory", 2025): [
            directory_row(1, "Alpha University"),
            directory_row(2, "Beta For-Profit", sector=3),
            directory_row(3, "Gamma College", sector=1),
            directory_row(4, "Delta College"),
        ],
        ("admissions-enrollment", 2024): [adm(1, 1000, 300), adm(4, 500, 450)],
    }
    handle, _calls = router(tables)
    respx.get(url__startswith=BASE).mock(side_effect=handle)
    seen = []
    result = await run_search(REG, states=["PA"], http=http, progress=lambda d, n, label: seen.append(label))
    assert [r.name for r in result.records] == ["Alpha University", "Delta College", "Gamma College"]
    assert result.searched_states == ["PA"] and not result.note
    alpha = result.records[0]
    assert alpha.value("acceptance_rate") == 30.0 and alpha.value("state") == "PA"
    assert alpha.links == {}  # not on the curated list: no CDS link
    assert any("Finding four-year colleges in PA" in s for s in seen)


@respx.mock
async def test_run_search_falls_back_to_curated_list_when_ipeds_is_down(http):
    respx.get(url__startswith=BASE).respond(503)
    result = await run_search(REG, states=[], http=http)
    assert "curated list" in result.note
    assert [r.unitid for r in result.records] == [3]
