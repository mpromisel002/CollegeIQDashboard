import pytest
import yaml
from pydantic import ValidationError

from cfa.cache import SessionCache
from cfa.sources import sentinels
from cfa.sources.cds.fetch import check_format
from cfa.sources.labels import format_phone, locale_label
from cfa.sources.registry import parse_registry


@pytest.mark.parametrize("v", [-1, -2, -3, "-1", "-2", "-3", None, ""])
def test_urban_sentinels(v):
    assert sentinels.urban(v) is None


def test_urban_keeps_real_values():
    assert sentinels.urban(0) == 0 and sentinels.urban(25613) == 25613 and sentinels.urban_num("12") == 12.0


@pytest.mark.parametrize("v", ["PrivacySuppressed", None, "NULL"])
def test_scorecard_sentinels(v):
    assert sentinels.scorecard(v) is None and sentinels.scorecard_num(v) is None


def test_locale_and_phone():
    assert locale_label(12) == ("City: Midsize", "City")
    assert locale_label(41) == ("Rural: Fringe", "Rural")
    assert locale_label(99) == (None, None)
    assert format_phone("6174951000") == "(617) 495-1000"


def test_cache_clear():
    c = SessionCache(ttl=60)
    c.set("a", 1)
    assert c.get("a") == 1 and len(c) == 1
    c.clear()
    assert c.get("a") is None


def test_check_format():
    assert check_format(b"%PDF-1.7 ...", "application/pdf", "pdf")[0]
    ok, note = check_format(b"<html><body>moved</body></html>", "text/html", "pdf")
    assert not ok and "web page" in note
    assert check_format(
        b"PK\x03\x04", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx"
    )[0]
    assert not check_format(b"%PDF", "application/pdf", "xlsx")[0]
    assert not check_format(b"%PDF-1.4", "image/png", "pdf")[0]


REG = """
schema_version: 1
schools:
  - unitid: 1
    name: A
    cds:
      - {year: "2024-2025", url: "https://a.edu/old.pdf", format: pdf}
      - {year: "2025-2026", url: "https://a.edu/new.xlsx", format: xlsx}
"""


def test_registry_latest_and_validation():
    reg = parse_registry(REG)
    assert reg.get(1).latest_cds.url.endswith("new.xlsx")
    with pytest.raises((ValidationError, yaml.YAMLError)):
        parse_registry(REG.replace("format: pdf", "format: doc"))
    with pytest.raises((ValidationError, yaml.YAMLError)):
        parse_registry(REG + "  - {unitid: 1, name: dup}\n")
    with pytest.raises((ValidationError, yaml.YAMLError)):
        parse_registry(REG.replace("https://a.edu/old", "http://a.edu/old"))


def test_bundled_registry_is_valid():
    from cfa.sources.registry import load_bundled

    reg = load_bundled()
    assert len(reg.schools) >= 25
    assert all(s.latest_cds is not None for s in reg.schools)
