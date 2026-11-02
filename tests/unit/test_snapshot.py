"""The weekly data file: building it, reading it back, and searching from it."""

import json
from datetime import UTC, datetime, timedelta

import httpx
import respx

from cfa.aggregate import merge
from cfa.models.field_value import FieldValue, Status
from cfa.pipeline import run_all, run_search
from cfa.snapshot import Snapshot, SnapshotSchool, decode, encode, load_snapshot
from cfa.sources.base import FetchResult
from cfa.sources.cds.adapter import CdsAdapter
from cfa.sources.registry import parse_registry
from cfa.sources.scorecard import ScorecardAdapter
from cfa.sources.urban_ipeds import UrbanIpedsAdapter
from cfa.tools.build_snapshot import build
from tests.adapters.test_bulk import BASE, SCORECARD, adm, directory_row, router
from tests.adapters.test_urban import fixture_router
from tests.conftest import API, CDS

ALABAMA_PDF = "https://www.ua.example.edu/cds_2025-2026.pdf"
REG = parse_registry(f"""
schema_version: 1
schools:
  - unitid: 100751
    name: The University of Alabama
    cds: [{{year: "2025-2026", url: "{ALABAMA_PDF}", format: pdf}}]
""")


@respx.mock
async def test_round_trip_keeps_every_field(http):
    """Values, years, statuses and notes come back exactly, so merged records are identical."""
    respx.get(url__startswith=BASE).mock(side_effect=fixture_router)
    recorded = json.loads((API / "scorecard_100751.json").read_text())
    respx.get(url__startswith=SCORECARD).respond(200, json=recorded)
    respx.get(ALABAMA_PDF).respond(
        200, headers={"content-type": "application/pdf"}, content=(CDS / "alabama_2025-26.pdf").read_bytes()
    )
    results = [
        await UrbanIpedsAdapter(http, this_year=2026).fetch(100751),
        await ScorecardAdapter(http, "KEY").fetch(100751),
        await CdsAdapter(http, REG).fetch(100751),
    ]
    assert all(r.ok for r in results)
    school = SnapshotSchool(100751, "Alabama", "AL", True, ALABAMA_PDF, {r.source: r for r in results})
    built = datetime(2026, 11, 2, 9, 0, tzinfo=UTC)
    back = decode(encode(Snapshot(built, {100751: school}, ["IPEDS (Urban)"])))
    assert back.built_at == built
    again = list(back.schools[100751].results.values())
    before, after = merge(100751, "x", results), merge(100751, "x", again)
    assert after.fields == before.fields
    assert after.value("gpa_dist") == before.value("gpa_dist") and after.value("gpa_dist")
    assert after.value("net_price_by_income") == before.value("net_price_by_income")


async def test_unreadable_or_old_files_are_not_used(http):
    snap = Snapshot(datetime.now(UTC) - timedelta(days=40), {}, [])
    with respx.mock:
        respx.get("https://data.example/old.gz").respond(200, content=encode(snap))
        respx.get("https://data.example/bad.gz").respond(200, content=b"not gzip")
        respx.get("https://data.example/gone.gz").respond(404)
        fresh = encode(Snapshot(datetime.now(UTC), {}, []))
        respx.get("https://data.example/new.gz").respond(200, content=fresh)
        old = await load_snapshot(http, "https://data.example/old.gz")
        bad = await load_snapshot(http, "https://data.example/bad.gz")
        gone = await load_snapshot(http, "https://data.example/gone.gz")
        new = await load_snapshot(http, "https://data.example/new.gz")
    assert old.snapshot is None and "out of date" in old.note
    assert bad.snapshot is None and "unreadable" in bad.note
    assert gone.snapshot is None and "could not be downloaded" in gone.note
    assert new.snapshot is not None


@respx.mock
async def test_build_keeps_results_and_drops_passing_failures():
    tables = {
        ("directory", 2025): [
            directory_row(1, "Alpha University"),
            directory_row(2, "Beta For-Profit", sector=3),
            directory_row(100751, "The University of Alabama", state="AL", fips=1, sector=1),
        ],
        ("admissions-enrollment", 2024): [adm(1, 1000, 300)],
    }
    handle, _calls = router(tables)
    respx.get(url__startswith=BASE).mock(side_effect=handle)
    respx.get(url__startswith=SCORECARD).respond(503)  # down this week: left out, read live
    respx.get(ALABAMA_PDF).respond(
        200, headers={"content-type": "application/pdf"}, content=(CDS / "alabama_2025-26.pdf").read_bytes()
    )
    snap = await build(REG, api_key="KEY")
    assert set(snap.schools) == {1, 100751}  # only colleges a search lists: no for-profit
    assert snap.schools[1].candidate
    assert snap.sources == ["Common Data Set", "IPEDS (Urban)"]
    alabama = snap.schools[100751]
    assert alabama.state == "AL" and alabama.cds_url == ALABAMA_PDF
    assert set(alabama.results) == {"IPEDS (Urban)", "Common Data Set"}
    assert alabama.results["Common Data Set"].data["gpa_dist"].ok
    assert set(snap.schools[1].results) == {"IPEDS (Urban)"}  # no document listed: nothing stored


def stored(unitid, name, state, *, candidate=True, cds_url=None, **values):
    values = {"name": name, "state": state, **values}
    data = {k: FieldValue.of(v, "IPEDS (Urban)", "2024") for k, v in values.items()}
    results = {"IPEDS (Urban)": FetchResult("IPEDS (Urban)", Status.OK, data)}
    if cds_url:
        cds = {"gpa_avg": FieldValue.of(3.9, "Common Data Set", "2025-2026")}
        results["Common Data Set"] = FetchResult("Common Data Set", Status.OK, cds, year="2025-2026")
    return unitid, SnapshotSchool(unitid, name, state, candidate, cds_url, results)


SNAP = Snapshot(
    datetime.now(UTC),
    dict(
        [
            stored(1, "Alpha University", "PA", applicants_total=1000, admits_total=300),
            stored(2, "Beta For-Profit", "PA", candidate=False),
            stored(3, "Gamma College", "NY"),
            stored(100751, "The University of Alabama", "AL", cds_url=ALABAMA_PDF),
        ]
    ),
    ["IPEDS (Urban)", "Common Data Set"],
)


@respx.mock
async def test_search_answers_from_the_file_without_loading_ipeds(http):
    ipeds = respx.get(url__startswith=BASE).respond(503)
    pdf = respx.get(ALABAMA_PDF).respond(404)
    pa = await run_search(REG, states=["PA"], http=http, snapshot=SNAP)
    assert [r.name for r in pa.records] == ["Alpha University"]
    assert pa.records[0].value("acceptance_rate") == 30.0 and pa.searched_states == ["PA"]
    everywhere = await run_search(REG, states=[], http=http, snapshot=SNAP)
    names = [r.name for r in everywhere.records]
    assert names == ["Alpha University", "Gamma College", "The University of Alabama"]
    alabama = everywhere.records[-1]
    assert alabama.value("gpa_avg") == 3.9  # the stored Common Data Set, not read again
    assert not ipeds.called and not pdf.called
    curated = await run_all(REG, http=http, snapshot=SNAP)
    assert [r.value("gpa_avg") for r in curated.records] == [3.9] and not pdf.called


@respx.mock
async def test_changed_or_new_documents_are_read_live(http):
    new_pdf = "https://www.ua.example.edu/cds_2026-2027.pdf"
    reg = parse_registry(f"""
schema_version: 1
schools:
  - unitid: 100751
    name: The University of Alabama
    cds: [{{year: "2026-2027", url: "{new_pdf}", format: pdf}}]
  - unitid: 221999
    name: Vanderbilt University
""")
    respx.get(new_pdf).respond(
        200, headers={"content-type": "application/pdf"}, content=(CDS / "alabama_2025-26.pdf").read_bytes()
    )
    respx.get(url__startswith=BASE).mock(side_effect=fixture_router)  # Vanderbilt: added since the build
    updates = []
    res = await run_search(reg, states=["AL", "TN"], http=http, snapshot=SNAP, on_update=updates.append)
    names = [r.name for r in res.records]
    assert names == ["The University of Alabama", "Vanderbilt University"]
    assert [r.name for r in updates] == ["The University of Alabama"]  # read again: new document
    assert res.records[0].value("gpa_avg") != 3.9
    assert res.records[1].value("state") == "TN"


async def test_file_without_scorecard_uses_the_live_key(http):
    with respx.mock:
        respx.get(url__startswith=BASE).respond(503)
        sc = respx.get(url__startswith=SCORECARD).mock(
            side_effect=lambda req: httpx.Response(
                200, json={"metadata": {"total": 1}, "results": [{"id": 1, "latest.student.size": 900}]}
            )
        )
        res = await run_search(REG, states=["PA"], http=http, snapshot=SNAP, api_key="KEY")
    assert sc.called and res.records[0].value("undergrad_size") == 900


def test_a_file_of_some_states_only_answers_searches_inside_them():
    part = Snapshot(datetime.now(UTC), {}, [], ["NY", "PA"])
    assert part.covers(["PA"]) and part.covers(["PA", "NY"])
    assert not part.covers(["PA", "OH"]) and not part.covers([])
    assert SNAP.covers([]) and SNAP.covers(["OH"])
    assert decode(encode(part)).states == ["NY", "PA"]
