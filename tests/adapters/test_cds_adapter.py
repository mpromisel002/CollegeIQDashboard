import respx

from cfa.models.field_value import Status
from cfa.sources.cds.adapter import CdsAdapter
from cfa.sources.registry import parse_registry
from tests.conftest import CDS

URL = "https://example.edu/cds.pdf"
REG = parse_registry(f"""
schema_version: 1
schools:
  - unitid: 100751
    name: The University of Alabama
    cds: [{{year: "2025-2026", url: "{URL}", format: pdf}}]
  - unitid: 2
    name: No CDS
""")


@respx.mock
async def test_fetch_and_parse(http):
    respx.get(URL).respond(
        200, content=(CDS / "alabama_2025-26.pdf").read_bytes(), headers={"Content-Type": "application/pdf"}
    )
    res = await CdsAdapter(http, REG).fetch(100751)
    assert res.status in (Status.OK, Status.PARTIAL)
    assert res.data["applicants_total"].value == 61994
    assert res.data["applicants_total"].year == "2025-2026"
    assert res.details["C1"] == "OK"


@respx.mock
async def test_moved_link_returns_html(http):
    respx.get(URL).respond(200, content=b"<html>Page moved</html>", headers={"Content-Type": "text/html"})
    res = await CdsAdapter(http, REG).fetch(100751)
    assert res.status is Status.SOURCE_UNAVAILABLE
    assert "web page" in res.note


@respx.mock
async def test_corrupt_pdf(http):
    respx.get(URL).respond(200, content=b"%PDF-1.7 garbage", headers={"Content-Type": "application/pdf"})
    res = await CdsAdapter(http, REG).fetch(100751)
    assert res.status is Status.PARSE_FAILED
    assert all(not fv.ok for fv in res.data.values())


@respx.mock
async def test_too_large(http):
    respx.get(URL).respond(200, content=b"%PDF" + b"0" * 2000, headers={"Content-Type": "application/pdf"})
    adapter = CdsAdapter(http, REG)
    from cfa.sources.cds import fetch as fetch_mod

    status, content, note = await fetch_mod.fetch_cds(http, URL, "pdf", max_bytes=100)
    assert status is Status.PARSE_FAILED and content is None and "larger" in note
    assert adapter is not None


async def test_no_cds_listed(http):
    res = await CdsAdapter(http, REG).fetch(2)
    assert res.status is Status.NOT_REPORTED


@respx.mock
async def test_server_down(http):
    respx.get(URL).respond(503)
    res = await CdsAdapter(http, REG).fetch(100751)
    assert res.status is Status.SOURCE_UNAVAILABLE
