import asyncio

import httpx
import pytest
import respx
from PySide6.QtWidgets import QLabel, QPushButton

from cfa.models.field_value import FieldValue, Status
from cfa.models.student import GreekDirection, StudentProfile
from cfa.pipeline import RunResult, run_all
from cfa.scoring import academic, culture
from cfa.sources.http import HttpClient
from cfa.sources.registry import parse_registry
from cfa.ui import main_window as mw
from cfa.ui.college_detail import CollegeDetail, linkout_url
from cfa.ui.results_table import ResultRow
from cfa.ui.student_panel import StudentPanel
from tests.conftest import make_record, no_wait

DIST = {"4.0": 30, "3.75-3.99": 30, "3.50-3.74": 20, "3.25-3.49": 10, "3.00-3.24": 10}


def sample_records():
    a = make_record(
        1,
        "Alpha U",
        state="AL",
        acceptance_rate=80.0,
        gpa_dist=DIST,
        greek_men_pct=30.0,
        greek_women_pct=40.0,
        setting="City",
        undergrad_size=30000,
    )
    b = make_record(2, "Beta College", state="TN", acceptance_rate=8.0, setting="Suburb", undergrad_size=4000)
    b.fields["greek_men_pct"] = FieldValue.missing("Common Data Set", Status.SOURCE_UNAVAILABLE, "down")
    return [a, b]


def test_profile_entry(qtbot):
    panel = StudentPanel()
    qtbot.addWidget(panel)
    panel.name.setText("Jordan")
    panel.gpa.setValue(3.8)
    panel.sat_ebrw.setValue(650)
    panel.sat_math.setValue(700)
    panel.states.setText("al, tn")
    panel.greek_dir.setCurrentText("wants")
    panel.greek_imp.setCurrentIndex(3)
    p = panel.profile()
    assert p.name == "Jordan" and p.gpa_unweighted == pytest.approx(3.8)
    assert p.sat_total == 1350 and p.act is None
    assert p.preferred_states == ["AL", "TN"]
    assert p.greek_direction is GreekDirection.WANTS and p.greek_importance == 3
    other = StudentPanel()
    qtbot.addWidget(other)
    other.set_profile(p)
    assert other.profile() == p


@pytest.fixture
def window(qtbot, monkeypatch):
    async def fake_run_all(registry, **kw):
        kw["progress"](1, 2, "Alpha U")
        return RunResult(records=sample_records())

    async def fake_run_search(registry, **kw):
        window.search_calls.append(kw["states"])
        return RunResult(records=sample_records(), searched_states=kw["states"])

    monkeypatch.setattr(mw, "run_all", fake_run_all)
    monkeypatch.setattr(mw, "run_search", fake_run_search)
    monkeypatch.setattr(mw, "parse_pool", lambda: None)
    w = mw.MainWindow(load_remote_registry=False)
    w.search_calls = []
    window = w
    qtbot.addWidget(w)
    return w


def test_run_flow_with_mocked_adapters(qtbot, window):
    window.student.gpa.setValue(3.9)
    window.student.submits.setChecked(False)
    window.run_match()
    qtbot.waitUntil(lambda: window.table.proxy.rowCount() == 2, timeout=10000)
    rows = {r.record.name: r for r in window.table.visible_rows()}
    assert rows["Beta College"].academic.tier == academic.REACH
    assert len(window.cards.cards) == 2 and "Showing 2 of 2" in window.count_label.text()
    window.filters.check("tiers", "Reach")
    assert window.table.proxy.rowCount() == 1 and len(window.cards.cards) == 1
    window.filters.clear()
    window.filters.check("greek", "Has Greek life")
    assert window.table.proxy.rowCount() == 1
    window.filters.clear()
    window.filters.check("settings", "Suburb")
    window.filters.check("settings", "City")
    assert window.table.proxy.rowCount() == 2
    window.filters.clear()
    assert "problem" in window.health_label.text() or "OK" in window.health_label.text()


def run_and_wait(qtbot, window, n):
    window.run_match()
    qtbot.waitUntil(lambda: window.worker is None and bool(window.table.results_model.rows), timeout=10000)
    assert len(window.table.results_model.rows) == n


def test_preferred_states_hide_other_states(qtbot, window):
    window.student.states.setText("Tennessee")  # full names work as well as codes
    run_and_wait(qtbot, window, 2)
    assert [r.record.name for r in window.table.visible_rows()] == ["Beta College"]
    assert "in TN" in window.count_label.text() and "1 in other states hidden" in window.count_label.text()
    window.student.states.setText("tn, al")  # takes effect at once, no re-run needed
    assert window.table.proxy.rowCount() == 2
    window.student.states.setText("TN")
    window.student.only_states.setChecked(False)  # advisor can still look beyond the list
    assert window.table.proxy.rowCount() == 2
    window.student.only_states.setChecked(True)
    assert window.table.proxy.rowCount() == 1


def test_preferred_states_none_match_explains(qtbot, window):
    window.student.states.setText("CA")
    run_and_wait(qtbot, window, 2)
    assert window.table.proxy.rowCount() == 0 and window.cards.cards == []
    assert "None of the 2 schools are in CA" in window.cards.findChild(QLabel, "Empty").text()


def test_unknown_state_entries_are_flagged(qtbot):
    panel = StudentPanel()
    qtbot.addWidget(panel)
    panel.states.setText("PA, Pensylvania, NY")
    assert not panel.states_warning.isHidden()
    assert "Pensylvania" in panel.states_warning.text()
    assert panel.preferred_states() == (["PA", "NY"], True)
    panel.states.setText("PA NY")
    assert panel.states_warning.isHidden()


def test_unknown_school_state_is_hidden_when_filtering(qtbot):
    from cfa.ui.results_table import ResultsTable

    table = ResultsTable()
    qtbot.addWidget(table)
    profile = StudentProfile()
    recs = [make_record(1, "Known", state="PA"), make_record(2, "Unknown")]
    table.results_model.set_rows(
        [ResultRow(r, academic.classify(profile, r), culture.score(profile, r)) for r in recs]
    )
    table.proxy.set_filters(states={"PA"})
    assert [r.record.name for r in table.visible_rows()] == ["Known"]
    table.proxy.set_filters(states=set())
    assert table.proxy.rowCount() == 2


def test_worker_exception_shows_toast(qtbot, monkeypatch):
    async def boom(registry, **kw):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(mw, "run_all", boom)
    monkeypatch.setattr(mw, "run_search", boom)
    monkeypatch.setattr(mw, "parse_pool", lambda: None)
    w = mw.MainWindow(load_remote_registry=False)
    qtbot.addWidget(w)
    w.run_match()
    qtbot.waitUntil(lambda: w.worker is None, timeout=10000)
    assert "kaboom" in w.toast.text()
    assert w.student.run_btn.isEnabled()


def test_detail_view_with_missing_fields(qtbot):
    rec = sample_records()[1]
    profile = StudentProfile(gpa_unweighted=3.5)
    row = ResultRow(rec, academic.classify(profile, rec), culture.score(profile, rec))
    dlg = CollegeDetail(row)
    qtbot.addWidget(dlg)
    texts = [lbl.text() for lbl in dlg.findChildren(QLabel)]
    assert any(t == "Not reported" for t in texts)
    assert any(t == "Source unavailable" for t in texts)
    buttons = [b.text() for b in dlg.findChildren(QPushButton)]
    assert "Retry" in buttons and "View on Niche" in buttons
    with qtbot.waitSignal(dlg.retry_requested, timeout=1000):
        next(b for b in dlg.findChildren(QPushButton) if b.text() == "Retry").click()


def test_linkouts_never_fetch_only_open():
    rec = make_record(1, "Alpha U")
    assert linkout_url("niche", rec).startswith("https://www.google.com/search?q=")
    assert "collegetransitions.com" in linkout_url("collegetransitions_greek", rec)


REG = parse_registry("""
schema_version: 1
schools:
  - unitid: 100751
    name: The University of Alabama
    cds: [{year: "2025-2026", url: "https://oira.ua.edu/x.pdf", format: pdf}]
""")


@respx.mock
def test_network_off_shows_source_unavailable(qtbot):
    respx.route().mock(side_effect=httpx.ConnectError("network down"))

    async def go():
        async with HttpClient(wait=no_wait) as http:
            return await run_all(REG, api_key="KEY", http=http)

    result = asyncio.run(go())
    rec = result.records[0]
    assert rec.name == "The University of Alabama"  # registry fallback name
    assert rec.get("city").status is Status.SOURCE_UNAVAILABLE
    assert rec.get("greek_men_pct").status is Status.SOURCE_UNAVAILABLE
    profile = StudentProfile(gpa_unweighted=3.5)
    row = ResultRow(rec, academic.classify(profile, rec), culture.score(profile, rec))
    assert row.academic.tier == academic.UNCLASSIFIED
    dlg = CollegeDetail(row)
    qtbot.addWidget(dlg)
    assert sum(lbl.text() == "Source unavailable" for lbl in dlg.findChildren(QLabel)) > 10


def test_cards_are_paged(qtbot):
    from cfa.ui.results_cards import ResultCards

    cards = ResultCards()
    qtbot.addWidget(cards)
    profile = StudentProfile()
    rows = [
        ResultRow(r, academic.classify(profile, r), culture.score(profile, r))
        for r in (make_record(i, f"School {i:02d}", state="PA") for i in range(45))
    ]
    cards.set_rows(rows)
    assert len(cards.cards) == 20 and cards.page_label.text() == "1–20 of 45"
    assert not cards.prev_btn.isEnabled() and cards.next_btn.isEnabled()
    cards.next_btn.click()
    cards.next_btn.click()
    assert len(cards.cards) == 5 and cards.page_label.text() == "41–45 of 45"
    assert not cards.next_btn.isEnabled()
    cards.set_rows(rows[:3])  # new results start again on page 1, without a pager
    assert len(cards.cards) == 3 and cards.pager.isHidden()


def test_search_covers_preferred_states_and_says_what_was_not_searched(qtbot, window):
    window.student.states.setText("TN")
    run_and_wait(qtbot, window, 2)
    assert window.search_calls == [["TN"]]
    window.student.states.setText("TN, AL")
    assert "Only TN searched: press Run Match to include AL" in window.count_label.text()
    window.student.only_states.setChecked(False)
    assert "include other states" in window.count_label.text()


def test_curated_scope_uses_the_list(qtbot, window):
    from cfa.ui.student_panel import SCOPE_CURATED

    window.student.scope.setCurrentText(SCOPE_CURATED)
    run_and_wait(qtbot, window, 2)
    assert window.search_calls == []
    assert "searched" not in window.count_label.text()


def test_federal_only_badge_and_filter(qtbot, window):
    from cfa.ui.results_cards import badges

    run_and_wait(qtbot, window, 2)
    rows = window.table.visible_rows()
    texts = [b.text() for b in badges(rows[0])]
    assert "Federal data only" in texts
    rows[0].record.links["cds"] = "https://example.edu/cds.pdf"
    assert "Full data" in [b.text() for b in badges(rows[0])]
    window.filters.check("data_level", "Full")
    assert window.table.proxy.rowCount() == 1
