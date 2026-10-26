"""The owner tool that proposes registry entries from a college's own site."""

import pytest
import respx

from cfa.sources.http import HttpClient
from cfa.tools.find_cds import (
    Candidate,
    Robots,
    check_school,
    doc_links,
    entries_yaml,
    infer_year,
    rank,
    year_pages,
)
from tests.conftest import CDS, no_wait


@pytest.mark.parametrize(
    "text,year",
    [
        ("CDS_2025-2026.pdf", "2025-2026"),
        ("CDS-2025-26_Final.xlsx", "2025-2026"),
        ("common-data-set-2024_2025.pdf", "2024-2025"),
        ("cds_2425.html", "2024-2025"),
        ("Common Data Set 25-26", "2025-2026"),
        ("report-2526.pdf", None),  # bare digits only count next to "CDS"
        ("CDS 2025-2027.pdf", None),  # not consecutive years
        ("budget 2025.pdf", None),
    ],
)
def test_infer_year(text, year):
    assert infer_year(text) == year


PAGE = """
<a href="/ir/files/CDS-2025-26_Final.xlsx">2025-2026</a>
<a href="https://ir.example.edu/files/CDS_2024-2025.pdf">CDS 2024-2025</a>
<a href="https://other.org/CDS_2025-2026.pdf">mirror elsewhere</a>
<a href="/ir/files/budget.pdf">Budget</a>
<a href="/ir/cds/2025-2026/">Common Data Set 2025-2026 (by section)</a>
<a href="/ir/cds/2019-2020/">Common Data Set 2019-2020</a>
"""


def test_doc_links_keep_cds_files_on_the_colleges_own_site():
    links = doc_links("https://www.example.edu/ir/common-data-set/", PAGE, "example.edu")
    assert [(c.url, c.year) for c in links] == [
        ("https://www.example.edu/ir/files/CDS-2025-26_Final.xlsx", "2025-2026"),
        ("https://ir.example.edu/files/CDS_2024-2025.pdf", "2024-2025"),
    ]


def test_year_pages_recent_only():
    assert year_pages("https://www.example.edu/ir/common-data-set/", PAGE, "example.edu") == [
        "https://www.example.edu/ir/cds/2025-2026/"
    ]


def test_rank_newest_first_and_drops_stale():
    ranked = rank(
        [
            Candidate("https://e.edu/a.pdf", year="2023-2024"),
            Candidate("https://e.edu/b.pdf", year=None),
            Candidate("https://e.edu/c.pdf", year="2025-2026"),
            Candidate("https://e.edu/d.pdf", year="2020-2021"),
        ]
    )
    assert [c.url for c in ranked] == ["https://e.edu/c.pdf", "https://e.edu/a.pdf", "https://e.edu/b.pdf"]


def test_entries_yaml_is_valid_registry():
    from cfa.sources.registry import parse_registry

    entry = {
        "unitid": 1,
        "name": 'St. Mary\'s "College"',
        "cds": [{"year": "2025-2026", "url": "https://e.edu/c.pdf", "format": "pdf"}],
    }
    reg = parse_registry("schema_version: 1\nschools:\n" + entries_yaml([entry]))
    assert reg.schools[0].name == 'St. Mary\'s "College"'


@respx.mock
async def test_check_school_finds_newest_passing_document():
    respx.get("https://www.alabama.example.edu/robots.txt").respond(404)
    respx.get("https://www.alabama.example.edu/ir/cds/").respond(
        200,
        headers={"content-type": "text/html"},
        text='<a href="/files/CDS_2025-2026.pdf">2025-2026</a>'
        '<a href="/files/CDS_2024-2025.pdf">2024-2025</a>',
    )
    respx.get("https://www.alabama.example.edu/files/CDS_2025-2026.pdf").respond(
        200, headers={"content-type": "application/pdf"}, content=(CDS / "alabama_2025-26.pdf").read_bytes()
    )
    item = {
        "unitid": 100751,
        "name": "Alabama",
        "domain": "alabama.example.edu",
        "urls": ["https://www.alabama.example.edu/ir/cds/", "https://elsewhere.org/cds.pdf"],
    }
    async with HttpClient(wait=no_wait) as http:
        out = await check_school(http, Robots(http), item)
    assert out.entry == {
        "unitid": 100751,
        "name": "Alabama",
        "cds": [
            {
                "year": "2025-2026",
                "url": "https://www.alabama.example.edu/files/CDS_2025-2026.pdf",
                "format": "pdf",
            }
        ],
    }
    assert out.tried == ["https://www.alabama.example.edu/files/CDS_2025-2026.pdf"]


@respx.mock
async def test_check_school_rejects_documents_without_gpa_and_respects_robots_and_403():
    respx.get("https://www.duke.example.edu/files/CDS_2025-2026.pdf").respond(
        200, headers={"content-type": "application/pdf"}, content=(CDS / "duke_2025-26.pdf").read_bytes()
    )
    respx.get("https://www.blocked.example.edu/robots.txt").respond(404)
    respx.get("https://www.blocked.example.edu/ir/").respond(403)
    respx.get("https://www.private.example.edu/robots.txt").respond(
        200, text="User-agent: *\nDisallow: /ir/\n"
    )
    page = respx.get("https://www.private.example.edu/ir/cds/").respond(200, text="never read")
    async with HttpClient(wait=no_wait) as http:
        robots = Robots(http)
        duke = await check_school(
            http,
            robots,
            {
                "unitid": 1,
                "name": "Duke",
                "domain": "duke.example.edu",
                "urls": ["https://www.duke.example.edu/files/CDS_2025-2026.pdf"],
            },
        )
        blocked = await check_school(
            http,
            robots,
            {
                "unitid": 2,
                "name": "B",
                "domain": "blocked.example.edu",
                "urls": ["https://www.blocked.example.edu/ir/"],
            },
        )
        private = await check_school(
            http,
            robots,
            {
                "unitid": 3,
                "name": "P",
                "domain": "private.example.edu",
                "urls": ["https://www.private.example.edu/ir/cds/"],
            },
        )
    assert duke.entry is None and "C11" in duke.reason
    assert blocked.entry is None and "refuses automated requests" in blocked.reason
    assert private.entry is None and not page.called


def test_shared_documents_are_not_assigned_automatically():
    from cfa.tools.find_cds import Outcome, drop_shared_documents

    def found(uid, name, url):
        return Outcome(
            uid,
            name,
            {"unitid": uid, "name": name, "cds": [{"year": "2025-2026", "url": url, "format": "pdf"}]},
        )

    outs = drop_shared_documents(
        [
            found(1, "State U", "https://s.edu/cds.pdf"),
            found(2, "State U Online", "https://s.edu/cds.pdf"),
            found(3, "Other College", "https://o.edu/cds.pdf"),
        ]
    )
    assert [o.entry is not None for o in outs] == [False, False, True]
    assert "choose by hand" in outs[0].reason
