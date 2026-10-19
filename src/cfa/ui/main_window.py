"""Main window: student panel, filters, results table, progress, status bar."""

from __future__ import annotations

import asyncio
import csv
import html
import logging
from collections import Counter
from pathlib import Path

from PySide6.QtCore import QSettings, Qt, QThreadPool, QTimer
from PySide6.QtGui import QAction, QTextDocument
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from cfa import __version__, config
from cfa.models.college import FIELDS, CollegeRecord
from cfa.models.field_value import Status
from cfa.models.student import StudentProfile
from cfa.pipeline import RunResult, parse_pool, run_all, run_search
from cfa.scoring import academic, culture
from cfa.sources.http import HttpClient
from cfa.sources.registry import Registry, RegistryLoad, load_bundled, load_registry
from cfa.ui.college_detail import CollegeDetail
from cfa.ui.filter_panel import FilterPanel
from cfa.ui.format import fmt_value
from cfa.ui.results_cards import ResultCards
from cfa.ui.results_table import COL_CULTURE, COL_NAME, COL_RATE, COL_SIZE, COL_TIER, ResultRow, ResultsTable
from cfa.ui.student_panel import StudentPanel
from cfa.ui.theme import named
from cfa.ui.workers import Worker

log = logging.getLogger(__name__)

# Sort menu: label -> (table column, order). "Best match" = Safety→Target→Reach, best culture fit first.
SORTS: dict[str, tuple[int, Qt.SortOrder]] = {
    "Best match": (COL_TIER, Qt.SortOrder.AscendingOrder),
    "Culture fit": (COL_CULTURE, Qt.SortOrder.DescendingOrder),
    "Acceptance rate (lowest first)": (COL_RATE, Qt.SortOrder.AscendingOrder),
    "Acceptance rate (highest first)": (COL_RATE, Qt.SortOrder.DescendingOrder),
    "Enrollment (largest first)": (COL_SIZE, Qt.SortOrder.DescendingOrder),
    "Name (A–Z)": (COL_NAME, Qt.SortOrder.AscendingOrder),
}


class MainWindow(QMainWindow):
    def __init__(self, *, load_remote_registry: bool = True) -> None:
        super().__init__()
        self.setWindowTitle(f"College Fit Advisor {__version__}")
        self.resize(1360, 860)
        self.pool = QThreadPool.globalInstance()
        self.registry: Registry = Registry(schema_version=1, schools=[])
        self.records: list[CollegeRecord] = []
        self.worker: Worker | None = None
        # States the last all-colleges search covered ([] = every state); None = curated list run.
        self.searched_states: list[str] | None = None
        self.settings = QSettings("CollegeFitAdvisor", "CollegeFitAdvisor")

        # Left sidebar: the student's profile and the results filters.
        self.student = StudentPanel()
        self.student.run_requested.connect(self.run_match)
        self.student.save_requested.connect(self.save_profile)
        self.student.load_requested.connect(self.load_profile)
        self.student.states_changed.connect(self.apply_filters)
        self.filters = FilterPanel()
        self.filters.changed.connect(self.apply_filters)
        self.tabs = QTabWidget()
        self.tabs.addTab(self.student, "Student")
        self.tabs.addTab(self.filters, "Filters")
        sidebar = named(QFrame(), "Panel")
        sv = QVBoxLayout(sidebar)
        sv.setContentsMargins(12, 8, 12, 12)
        sv.addWidget(self.tabs)
        sidebar.setMinimumWidth(380)
        sidebar.setMaximumWidth(480)

        # Results: title, count, view toggle and sort; then cards or table.
        self.banner = named(QLabel(), "Banner")
        self.banner.setWordWrap(True)
        self.banner.hide()
        self.toast = named(QLabel(), "Toast")
        self.toast.setWordWrap(True)
        self.toast.hide()

        self.table = ResultsTable()
        self.table.doubleClicked.connect(self.open_detail)
        self.cards = ResultCards()
        self.cards.details_requested.connect(self.show_detail)
        self.views = QStackedWidget()
        self.views.addWidget(self.cards)
        self.views.addWidget(self.table)
        self.table.proxy.layoutChanged.connect(self._refresh_views)

        self.count_label = named(QLabel("No results yet"), "Muted")
        self.count_label.setWordWrap(True)
        self.card_btn = named(QPushButton("Cards"), "Segment")
        self.table_btn = named(QPushButton("Table"), "Segment")
        toggle = QButtonGroup(self)
        for i, b in enumerate((self.card_btn, self.table_btn)):
            b.setCheckable(True)
            toggle.addButton(b, i)
        self.card_btn.setChecked(True)
        toggle.idClicked.connect(self.views.setCurrentIndex)
        self.sort = QComboBox()
        self.sort.addItems(list(SORTS))
        self.sort.currentTextChanged.connect(self.apply_sort)

        head = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(2)
        titles.addWidget(named(QLabel("Search Results"), "PageTitle"))
        titles.addWidget(self.count_label)
        head.addLayout(titles, 1)
        seg = QHBoxLayout()
        seg.setSpacing(0)
        seg.addWidget(self.card_btn)
        seg.addWidget(self.table_btn)
        head.addLayout(seg)
        head.addSpacing(8)
        head.addWidget(QLabel("Sort by"))
        head.addWidget(self.sort)

        self.progress = QProgressBar()
        self.progress.hide()
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.hide()
        self.cancel_btn.clicked.connect(self.cancel_run)
        prog = QHBoxLayout()
        prog.addWidget(self.progress, 1)
        prog.addWidget(self.cancel_btn)

        results = named(QFrame(), "Panel")
        rv = QVBoxLayout(results)
        rv.setContentsMargins(18, 14, 18, 14)
        rv.setSpacing(10)
        rv.addLayout(head)
        rv.addWidget(named(QFrame(), "Divider"))
        rv.addWidget(self.banner)
        rv.addLayout(prog)
        rv.addWidget(self.views, 1)
        rv.addWidget(self.toast)

        split = QSplitter(Qt.Orientation.Horizontal)
        split.addWidget(sidebar)
        split.addWidget(results)
        split.setStretchFactor(1, 1)
        split.setChildrenCollapsible(False)
        split.setHandleWidth(14)

        page = named(QWidget(), "Page")
        pv = QVBoxLayout(page)
        pv.setContentsMargins(0, 0, 0, 0)
        pv.setSpacing(0)
        pv.addWidget(self._header())
        body = QVBoxLayout()
        body.setContentsMargins(16, 16, 16, 12)
        body.addWidget(split)
        pv.addLayout(body, 1)
        self.setCentralWidget(page)

        self.health_label = QLabel("Sources: not run yet")
        self.statusBar().addPermanentWidget(self.health_label)
        self.apply_filters()
        self._load_registry(remote=load_remote_registry)

    # ----------------------------------------------------------------- header bar (replaces the menu bar)
    def _header(self) -> QFrame:
        bar = named(QFrame(), "HeaderBar")
        h = QHBoxLayout(bar)
        h.setContentsMargins(18, 8, 12, 8)
        h.addWidget(named(QLabel("College Fit Advisor"), "AppTitle"))
        self.registry_label = named(QLabel("Loading school list…"), "HeaderInfo")
        h.addSpacing(16)
        h.addWidget(self.registry_label)
        h.addStretch(1)

        def menu_button(text: str, items: list[tuple[str, object]]) -> QToolButton:
            b = QToolButton()
            b.setText(text + "  ▾")
            b.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
            m = QMenu(b)
            for label, slot in items:
                a = QAction(label, b)
                a.triggered.connect(slot)
                m.addAction(a)
            b.setMenu(m)
            return b

        h.addWidget(
            menu_button(
                "Profile", [("Load profile…", self.load_profile), ("Save profile…", self.save_profile)]
            )
        )
        h.addWidget(
            menu_button(
                "Export",
                [("Export results to CSV…", self.export_csv), ("Export results to PDF…", self.export_pdf)],
            )
        )
        for text, slot in (("Settings", self.open_settings), ("About", self.about)):
            b = QToolButton()
            b.setText(text)
            b.clicked.connect(slot)
            h.addWidget(b)
        return bar

    def about(self) -> None:
        QMessageBox.about(
            self,
            "About College Fit Advisor",
            f"College Fit Advisor {__version__}<br><br>College data is fetched live from IPEDS "
            "(Urban Institute Education Data Portal), the U.S. Dept. of Education College "
            "Scorecard, and each school's own Common Data Set. Nothing is stored on disk.<br><br>"
            f"<a href='{config.REPO_URL}'>{config.REPO_URL}</a>",
        )

    # ----------------------------------------------------------------- feedback
    def show_toast(self, text: str, ms: int = 6000) -> None:
        self.toast.setText(text)
        self.toast.show()
        QTimer.singleShot(ms, self.toast.hide)

    def show_banner(self, text: str | None) -> None:
        self.banner.setText(text or "")
        self.banner.setVisible(bool(text))

    # ----------------------------------------------------------------- registry
    def _load_registry(self, remote: bool = True) -> None:
        if not remote:
            try:
                self.set_registry(RegistryLoad(load_bundled(), "bundled"))
            except Exception as exc:
                self.show_banner(f"No usable school list: {type(exc).__name__}")
            return

        async def go() -> RegistryLoad:
            async with HttpClient(max_retries=1) as http:
                return await load_registry(http)

        w = Worker(lambda p, c: asyncio.run(go()))
        w.signals.finished.connect(self.set_registry)
        w.signals.failed.connect(lambda m: self.show_banner(f"Could not load the school list: {m}"))
        self.pool.start(w)

    def set_registry(self, load: RegistryLoad) -> None:
        self.registry = load.registry
        self.show_banner(load.warning)
        origin = {"remote": "online", "bundled": "built-in copy", "empty": "unavailable"}[load.origin]
        self.registry_label.setText(
            f"Curated list: {len(self.registry.schools)} schools with full data ({origin})"
        )

    # ----------------------------------------------------------------- profiles
    def save_profile(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Save student profile", "", "Student profile (*.json)")
        if path:
            try:
                self.student.profile().save(Path(path))
            except Exception as exc:
                QMessageBox.warning(self, "Save failed", str(exc))

    def load_profile(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Load student profile", "", "Student profile (*.json)")
        if path:
            try:
                self.student.set_profile(StudentProfile.load(Path(path)))
            except Exception as exc:
                QMessageBox.warning(self, "Could not load profile", str(exc))

    # ----------------------------------------------------------------- run
    def run_match(self, unitids: list[int] | None = None) -> None:
        if self.worker is not None:
            return
        try:
            self.student.profile()
        except Exception as exc:
            QMessageBox.warning(self, "Check the profile", str(exc))
            return
        if not self.registry.schools:
            self.show_toast("The school list has not loaded yet.")
            return
        registry, key = self.registry, config.scorecard_api_key()
        states, only = self.student.preferred_states()
        search_all = unitids is None and self.student.search_all()

        def job(progress, cancel) -> RunResult:
            if search_all:
                return asyncio.run(
                    run_search(
                        registry,
                        states=states if only else [],
                        api_key=key,
                        progress=progress,
                        cancel=cancel,
                        executor=parse_pool(),
                    )
                )
            return asyncio.run(
                run_all(
                    registry,
                    api_key=key,
                    progress=progress,
                    cancel=cancel,
                    executor=parse_pool(),
                    unitids=unitids,
                )
            )

        self.worker = Worker(job)
        self.worker.signals.progress.connect(self._on_progress)
        self.worker.signals.finished.connect(lambda res: self._on_finished(res, partial=unitids is not None))
        self.worker.signals.failed.connect(self._on_failed)
        self.progress.setValue(0)
        self.progress.show()
        self.cancel_btn.show()
        self.student.run_btn.setEnabled(False)
        self.pool.start(self.worker)

    def cancel_run(self) -> None:
        if self.worker is not None:
            self.worker.cancel()
            self.statusBar().showMessage("Cancelling…")

    def _on_progress(self, done: int, total: int, label: str) -> None:
        self.progress.setMaximum(max(1, total))
        self.progress.setValue(done)
        self.progress.setFormat(f"{done}/{total} — {label}")

    def _end_run(self) -> None:
        self.worker = None
        self.progress.hide()
        self.cancel_btn.hide()
        self.student.run_btn.setEnabled(True)

    def _on_failed(self, msg: str) -> None:
        self._end_run()
        self.show_toast(f"Something went wrong while fetching data: {msg}")

    def _on_finished(self, result: RunResult, partial: bool = False) -> None:
        self._end_run()
        if partial:
            by_id = {r.unitid: r for r in result.records}
            self.records = [by_id.get(r.unitid, r) for r in self.records]
        else:
            self.records = result.records
            self.searched_states = result.searched_states
            self.show_banner(result.note or None)
        self.rescore()
        self._update_health()
        if result.cancelled:
            self.show_toast(f"Cancelled — showing {len(result.records)} schools fetched so far.")

    def rescore(self) -> None:
        try:
            profile = self.student.profile()
        except Exception:
            return
        rows = [ResultRow(r, academic.classify(profile, r), culture.score(profile, r)) for r in self.records]
        self.table.results_model.set_rows(rows)
        self.apply_filters()
        self.apply_sort()

    def _update_health(self) -> None:
        counts: dict[str, Counter] = {}
        for rec in self.records:
            for src, fv in rec.source_status.items():
                counts.setdefault(src, Counter())[fv.status] += 1
        parts = []
        for src, c in counts.items():
            bad = sum(
                n
                for s, n in c.items()
                if s in (Status.SOURCE_UNAVAILABLE, Status.RATE_LIMITED, Status.PARSE_FAILED)
            )
            if c.get(Status.AUTH_MISSING):
                parts.append(f"{src}: no API key")
            elif bad:
                parts.append(f"{src}: {bad} problem(s)")
            else:
                parts.append(f"{src}: OK")
        self.health_label.setText(" | ".join(parts) or "Sources: no data")

    def apply_filters(self) -> None:
        states, only = self.student.preferred_states()
        self.filters.set_states(states, only)
        self.table.proxy.set_filters(states=set(states) if only else set(), **self.filters.values())
        self._refresh_views()

    def apply_sort(self) -> None:
        col, order = SORTS.get(self.sort.currentText(), SORTS["Best match"])
        self.table.sortByColumn(col, order)

    def _refresh_views(self) -> None:
        rows = self.table.visible_rows()
        total = len(self.table.results_model.rows)
        proxy = self.table.proxy
        if not total:
            self.count_label.setText("No results yet. Fill in the student profile and press Run Match.")
            self.cards.set_rows([], "Run a match to see schools here.")
            return
        text = f"Showing {len(rows)} of {total} colleges"
        if proxy.states:
            text += f" in {', '.join(sorted(proxy.states))}"
            hidden = proxy.hidden_by_state()
            if hidden:
                text += f" · {hidden} in other states hidden"
        searched = set(self.searched_states or [])
        if searched:
            unsearched = sorted(proxy.states - searched) if proxy.states else ["other states"]
            if unsearched:
                text += (
                    f" · Only {', '.join(sorted(searched))} searched: press Run Match to include "
                    + ", ".join(unsearched)
                )
        self.count_label.setText(text)
        empty = "No schools match these filters."
        if not rows and proxy.states:
            empty = (
                f"None of the {total} schools are in {', '.join(sorted(proxy.states))}. Untick "
                '"Only show schools in these states" on the Student tab to see the rest.'
            )
        self.cards.set_rows(rows, empty)

    # ----------------------------------------------------------------- detail
    def open_detail(self, index) -> None:
        row = self.table.row_at(index)
        if row is not None:
            self.show_detail(row)

    def show_detail(self, row: ResultRow) -> None:
        dlg = CollegeDetail(row, self)

        def retry(uid: int) -> None:
            dlg.accept()
            self.run_match([uid])

        dlg.retry_requested.connect(retry)
        dlg.exec()

    def open_settings(self) -> None:
        from cfa.ui.settings_dialog import SettingsDialog

        dlg = SettingsDialog(self.registry, self)
        dlg.reload_registry.connect(lambda: self._load_registry(remote=True))
        dlg.exec()

    # ----------------------------------------------------------------- exports (on demand, user-chosen path)
    EXPORT_FIELDS = [
        "state",
        "acceptance_rate",
        "gpa_avg",
        "sat_ebrw_25",
        "sat_ebrw_75",
        "sat_math_25",
        "sat_math_75",
        "act_25",
        "act_75",
        "test_policy",
        "greek_men_pct",
        "greek_women_pct",
        "housing_pct",
        "setting",
        "undergrad_size",
    ]

    def export_csv(self) -> None:
        rows = self.table.visible_rows()
        if not rows:
            self.show_toast("Nothing to export yet — run a match first.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export results", "college-fit.csv", "CSV (*.csv)")
        if not path:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8") as fh:
                w = csv.writer(fh)
                w.writerow(
                    ["Name", "Academic tier", "Reason", "Culture score"]
                    + [FIELDS[k].label for k in self.EXPORT_FIELDS]
                )
                for row in rows:
                    rec = row.record
                    w.writerow(
                        [
                            rec.name,
                            row.academic.tier,
                            row.academic.reason,
                            "" if row.culture.score is None else row.culture.score,
                        ]
                        + [fmt_value(k, rec.get(k)) for k in self.EXPORT_FIELDS]
                    )
        except OSError as exc:
            QMessageBox.warning(self, "Export failed", str(exc))

    def export_pdf(self) -> None:
        rows = self.table.visible_rows()
        if not rows:
            self.show_toast("Nothing to export yet — run a match first.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export results", "college-fit.pdf", "PDF (*.pdf)")
        if not path:
            return
        from PySide6.QtGui import QPageLayout, QPageSize
        from PySide6.QtPrintSupport import QPrinter

        profile = self.student.profile()
        head = "".join(
            f"<th>{h}</th>" for h in ["School", "Tier", "Culture", "Admit rate", "Avg GPA", "Greek (M/W)"]
        )
        body = ""
        for row in rows:
            r = row.record
            body += (
                "<tr>"
                + "".join(
                    f"<td>{html.escape(c)}</td>"
                    for c in [
                        r.name,
                        row.academic.tier,
                        "—" if row.culture.score is None else f"{row.culture.score:.0f}",
                        fmt_value("acceptance_rate", r.get("acceptance_rate")),
                        fmt_value("gpa_avg", r.get("gpa_avg")),
                        f"{fmt_value('greek_men_pct', r.get('greek_men_pct'))} / "
                        f"{fmt_value('greek_women_pct', r.get('greek_women_pct'))}",
                    ]
                )
                + "</tr>"
            )
        doc = QTextDocument()
        doc.setHtml(
            f"<h2>College Fit Advisor — {html.escape(profile.name or 'Student')}</h2>"
            f"<table border='1' cellspacing='0' cellpadding='3'><tr>{head}</tr>{body}</table>"
            "<p><small>Sources: IPEDS via Urban Institute, College Scorecard, schools' Common Data "
            "Sets.</small></p>"
        )
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
        printer.setOutputFileName(path)
        printer.setPageLayout(
            QPageLayout(
                QPageSize(QPageSize.PageSizeId.Letter),
                QPageLayout.Orientation.Landscape,
                printer.pageLayout().margins(),
            )
        )
        doc.print_(printer)

    def closeEvent(self, event) -> None:
        if self.worker is not None:
            self.worker.cancel()
        super().closeEvent(event)
