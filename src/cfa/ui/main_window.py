"""Main window: student panel, filters, results table, progress, status bar."""

from __future__ import annotations

import asyncio
import csv
import html
import logging
from collections import Counter
from pathlib import Path

from PySide6.QtCore import QSettings, QThreadPool, QTimer
from PySide6.QtGui import QAction, QTextDocument
from PySide6.QtWidgets import (
    QComboBox,
    QDockWidget,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from cfa import __version__, config
from cfa.models.college import FIELDS, CollegeRecord
from cfa.models.field_value import Status
from cfa.models.student import SizePref, StudentProfile
from cfa.pipeline import RunResult, parse_pool, run_all
from cfa.scoring import academic, culture
from cfa.sources.http import HttpClient
from cfa.sources.registry import Registry, RegistryLoad, load_bundled, load_registry
from cfa.ui.college_detail import CollegeDetail
from cfa.ui.format import fmt_value
from cfa.ui.results_table import ResultRow, ResultsTable
from cfa.ui.student_panel import StudentPanel
from cfa.ui.workers import Worker

log = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(self, *, load_remote_registry: bool = True) -> None:
        super().__init__()
        self.setWindowTitle(f"College Fit Advisor {__version__}")
        self.resize(1300, 820)
        self.pool = QThreadPool.globalInstance()
        self.registry: Registry = Registry(schema_version=1, schools=[])
        self.records: list[CollegeRecord] = []
        self.worker: Worker | None = None
        self.settings = QSettings("CollegeFitAdvisor", "CollegeFitAdvisor")

        self.student = StudentPanel()
        self.student.run_requested.connect(self.run_match)
        self.student.save_requested.connect(self.save_profile)
        self.student.load_requested.connect(self.load_profile)
        dock = QDockWidget("Student profile")
        dock.setWidget(self.student)
        dock.setFeatures(QDockWidget.DockWidgetFeature.NoDockWidgetFeatures)
        from PySide6.QtCore import Qt

        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, dock)

        self.banner = QLabel()
        self.banner.setWordWrap(True)
        self.banner.setStyleSheet("background: #fff4d6; color: #5a4300; padding: 6px; border-radius: 4px;")
        self.banner.hide()
        self.toast = QLabel()
        self.toast.setStyleSheet("background: #333; color: white; padding: 6px 10px; border-radius: 4px;")
        self.toast.hide()

        self.table = ResultsTable()
        self.table.doubleClicked.connect(self.open_detail)

        self.f_tier = QComboBox()
        self.f_tier.addItems(["Any", "Safety", "Target", "Reach", "Unclassified"])
        self.f_state = QLineEdit()
        self.f_state.setPlaceholderText("States, e.g. AL, TN")
        self.f_greek = QComboBox()
        self.f_greek.addItems(["Any", "Has Greek life", "No Greek life"])
        self.f_setting = QComboBox()
        self.f_setting.addItems(["Any", "City", "Suburb", "Town", "Rural"])
        self.f_size = QComboBox()
        self.f_size.addItems(["Any"] + [s.value for s in SizePref if s is not SizePref.ANY])
        for combo in (self.f_tier, self.f_greek, self.f_setting, self.f_size):
            combo.currentTextChanged.connect(self.apply_filters)
        self.f_state.textChanged.connect(self.apply_filters)
        filters = QHBoxLayout()
        for label, w in (
            ("Tier", self.f_tier),
            ("State", self.f_state),
            ("Greek", self.f_greek),
            ("Setting", self.f_setting),
            ("Size", self.f_size),
        ):
            filters.addWidget(QLabel(label))
            filters.addWidget(w)
        filters.addStretch(1)

        self.progress = QProgressBar()
        self.progress.hide()
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.hide()
        self.cancel_btn.clicked.connect(self.cancel_run)
        prog = QHBoxLayout()
        prog.addWidget(self.progress, 1)
        prog.addWidget(self.cancel_btn)

        central = QWidget()
        v = QVBoxLayout(central)
        v.addWidget(self.banner)
        v.addLayout(filters)
        v.addWidget(self.table, 1)
        v.addLayout(prog)
        v.addWidget(self.toast)
        self.setCentralWidget(central)

        self.health_label = QLabel("Sources: not run yet")
        self.statusBar().addPermanentWidget(self.health_label)
        self._menus()
        self._load_registry(remote=load_remote_registry)

    # ----------------------------------------------------------------- menus
    def _menus(self) -> None:
        m = self.menuBar().addMenu("&File")
        for text, slot in (
            ("Load profile…", self.load_profile),
            ("Save profile…", self.save_profile),
            ("Export results to CSV…", self.export_csv),
            ("Export results to PDF…", self.export_pdf),
        ):
            a = QAction(text, self)
            a.triggered.connect(slot)
            m.addAction(a)
        m.addSeparator()
        q = QAction("Quit", self)
        q.triggered.connect(self.close)
        m.addAction(q)
        t = self.menuBar().addMenu("&Tools")
        s = QAction("Settings…", self)
        s.triggered.connect(self.open_settings)
        t.addAction(s)
        h = self.menuBar().addMenu("&Help")
        a = QAction("About", self)
        a.triggered.connect(self.about)
        h.addAction(a)

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
        self.statusBar().showMessage(
            f"School list: {len(self.registry.schools)} schools ({load.origin})", 8000
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

        def job(progress, cancel) -> RunResult:
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
        self.table.proxy.set_filters(
            tier=self.f_tier.currentText(),
            state=self.f_state.text(),
            greek=self.f_greek.currentText(),
            setting=self.f_setting.currentText(),
            size=self.f_size.currentText(),
        )

    # ----------------------------------------------------------------- detail
    def open_detail(self, index) -> None:
        row = self.table.row_at(index)
        if row is None:
            return
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
