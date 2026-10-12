import respx

from cfa.sources.registry import parse_registry
from cfa.tools import validate_registry as vr
from tests.conftest import no_wait

REG = """
schema_version: 1
schools:
  - unitid: 1
    name: Blocked U
    cds: [{year: "2025-2026", url: "https://blocked.edu/cds.pdf", format: pdf}]
  - unitid: 2
    name: Moved U
    cds: [{year: "2025-2026", url: "https://moved.edu/cds.pdf", format: pdf}]
"""


@respx.mock
def test_blocked_is_separate_from_broken(tmp_path, monkeypatch, capsys):
    respx.get("https://blocked.edu/cds.pdf").respond(403)
    respx.get("https://moved.edu/cds.pdf").respond(404)
    path = tmp_path / "schools.yaml"
    path.write_text(REG)
    parse_registry(REG)  # schema sanity
    real = vr.HttpClient
    monkeypatch.setattr(vr, "HttpClient", lambda: real(wait=no_wait))
    assert vr.main(["--registry", str(path), "--allow-blocked"]) == 1  # the 404 still fails
    out = capsys.readouterr().out
    assert "BLOCKED (download" in out and "FAIL (download" in out
    assert "1 blocked (HTTP 403)" in out


@respx.mock
def test_only_blocked_passes_with_flag(tmp_path, monkeypatch):
    respx.get("https://blocked.edu/cds.pdf").respond(403)
    path = tmp_path / "schools.yaml"
    path.write_text(REG.split("  - unitid: 2")[0])
    real = vr.HttpClient
    monkeypatch.setattr(vr, "HttpClient", lambda: real(wait=no_wait))
    assert vr.main(["--registry", str(path), "--allow-blocked"]) == 0
    assert vr.main(["--registry", str(path)]) == 1
