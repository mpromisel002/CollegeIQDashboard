from pathlib import Path

import respx

from cfa.models.field_value import Status
from cfa.sources import sentinels
from cfa.sources.cds.adapter import CdsAdapter
from cfa.sources.labels import format_phone
from cfa.sources.registry import load_registry, parse_registry
from tests.conftest import CDS

REMOTE = "https://raw.example.test/schools.yaml"
GOOD = """
schema_version: 1
schools:
  - unitid: 7
    name: Seven
    cds: [{year: "2025-2026", url: "https://seven.edu/cds.pdf", format: pdf}]
"""


@respx.mock
async def test_remote_registry_preferred(http):
    respx.get(REMOTE).respond(200, text=GOOD)
    load = await load_registry(http, REMOTE)
    assert load.origin == "remote" and load.warning is None and load.registry.get(7)


@respx.mock
async def test_malformed_remote_falls_back_with_banner(http):
    respx.get(REMOTE).respond(200, text="schema_version: 2\nschools: oops")
    load = await load_registry(http, REMOTE)
    assert load.origin == "bundled" and "malformed" in load.warning
    assert len(load.registry.schools) >= 25


@respx.mock
async def test_unreachable_remote_falls_back(http):
    respx.get(REMOTE).respond(503)
    load = await load_registry(http, REMOTE)
    assert load.origin == "bundled" and "bundled" in load.warning


@respx.mock
async def test_no_usable_registry(http, tmp_path: Path):
    respx.get(REMOTE).respond(404)
    load = await load_registry(http, REMOTE, bundled=tmp_path / "missing.yaml")
    assert load.origin == "empty" and load.registry.schools == []


REG = parse_registry(GOOD)


@respx.mock
async def test_cds_health_check_and_cache(http):
    route = respx.get("https://seven.edu/cds.pdf").respond(
        200, content=(CDS / "alabama_2025-26.pdf").read_bytes(), headers={"Content-Type": "application/pdf"}
    )
    adapter = CdsAdapter(http, REG)
    assert (await adapter.health_check()).status is Status.OK
    first = await adapter.fetch(7)
    calls = route.call_count
    second = await adapter.fetch(7)
    assert second is first and route.call_count == calls


async def test_cds_health_check_without_documents(http):
    empty = parse_registry("schema_version: 1\nschools: []")
    assert (await CdsAdapter(http, empty).health_check()).status is Status.NOT_REPORTED


class BrokenExecutor:
    def submit(self, *a, **k):
        raise RuntimeError("pool is gone")


@respx.mock
async def test_cds_parse_falls_back_when_pool_breaks(http):
    respx.get("https://seven.edu/cds.pdf").respond(
        200, content=(CDS / "alabama_2025-26.pdf").read_bytes(), headers={"Content-Type": "application/pdf"}
    )
    res = await CdsAdapter(http, REG, executor=BrokenExecutor()).fetch(7)
    assert res.data["applicants_total"].value == 61994


def test_small_helpers():
    assert format_phone("16174951000") == "(617) 495-1000"
    assert format_phone("12345") == "12345"
    assert format_phone(None) is None
    assert sentinels.urban(True) is True
    assert sentinels.urban(" 5 ") == "5"
    assert sentinels.urban_num("x") is None
    assert sentinels.urban_num(-7) is None
    assert sentinels.scorecard_num("abc") is None
    assert sentinels.scorecard_num(True) is None
