"""Detail view: every field with its source badge, charts, selectivity profile and link-outs."""

from __future__ import annotations

import html
from urllib.parse import quote_plus

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from cfa.models.college import ADMISSION_FACTORS, FIELDS, IMPORTANCE_LEVELS, CollegeRecord
from cfa.models.field_value import Status
from cfa.ui.charts import ChartCanvas, admit_round_chart, gpa_chart
from cfa.ui.format import badge, fmt_value
from cfa.ui.results_table import ResultRow

SKIP = {"gpa_dist", "admission_factors", "name"}

# Opened in the system browser only; these sites are never fetched (PLAN §1).
LINKOUT_SITES = {
    "niche": ("Niche", "niche.com"),
    "petersons": ("Peterson's", "petersons.com"),
    "bigfuture": ("BigFuture", "bigfuture.collegeboard.org"),
    "collegetransitions_greek": ("College Transitions (Greek life)", "collegetransitions.com"),
}
CT_GREEK_URL = "https://www.collegetransitions.com/dataverse/greek-life"


def linkout_url(key: str, college: CollegeRecord) -> str:
    if college.links.get(key):
        return college.links[key]
    if key == "collegetransitions_greek":
        return CT_GREEK_URL
    domain = LINKOUT_SITES[key][1]
    return "https://www.google.com/search?q=" + quote_plus(f"{college.name} site:{domain}")


class CollegeDetail(QDialog):
    retry_requested = Signal(int)

    def __init__(self, row: ResultRow, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.row = row
        r = row.record
        self.setWindowTitle(r.name)
        self.resize(980, 760)

        from cfa.ui.results_cards import badges, culture_summary
        from cfa.ui.results_table import location
        from cfa.ui.theme import named

        header = named(QFrame(), "Card")
        hv = QVBoxLayout(header)
        hv.setContentsMargins(18, 14, 18, 14)
        hv.addWidget(named(QLabel(r.name), "CardTitle"))
        hv.addWidget(named(QLabel(location(r) or "Location not available"), "Muted"))
        pills = QHBoxLayout()
        pills.setSpacing(8)
        for b in badges(row):
            pills.addWidget(b)
        pills.addStretch(1)
        hv.addLayout(pills)
        why = named(QFrame(), "WhyBox")
        wv = QVBoxLayout(why)
        wv.setContentsMargins(12, 8, 12, 8)
        for title, text in (("Academic fit.", row.academic.reason), ("Culture fit.", culture_summary(row))):
            lbl = QLabel(f"<b>{title}</b> {html.escape(text)}")
            lbl.setWordWrap(True)
            wv.addWidget(lbl)
        hv.addWidget(why)

        body = QWidget()
        grid = QGridLayout(body)
        left, right = QVBoxLayout(), QVBoxLayout()
        for group in ("General", "GPA", "Campus culture"):
            left.addWidget(self._group(group))
        for group in ("Admissions", "Test scores", "Cost and aid"):
            right.addWidget(self._group(group))
        left.addStretch(1)
        right.addStretch(1)
        grid.addLayout(left, 0, 0)
        grid.addLayout(right, 0, 1)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        charts = QGroupBox("Charts")
        ch = QHBoxLayout(charts)
        self.gpa_canvas = ChartCanvas()
        self.round_canvas = ChartCanvas()
        gpa_chart(self.gpa_canvas, r)
        admit_round_chart(self.round_canvas, r)
        ch.addWidget(self.gpa_canvas)
        ch.addWidget(self.round_canvas)
        grid.addWidget(charts, 1, 0, 1, 2)
        grid.addWidget(self._selectivity(), 2, 0, 1, 2)
        grid.addWidget(self._sources(), 3, 0, 1, 2)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(body)
        outer = QVBoxLayout(self)
        outer.addWidget(header)
        outer.addWidget(scroll, 1)
        outer.addLayout(self._linkouts())

    def _value_widget(self, key: str) -> QWidget:
        fv = self.row.record.get(key)
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        text = fmt_value(key, fv)
        if key == "net_price_by_income" and fv.ok:
            text = text.replace(": ", ":\u00a0").replace(" · ", "\n")  # one income bracket per line
        val = QLabel(text)
        val.setWordWrap(True)
        val.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        h.addWidget(val)
        b = QLabel(badge(fv))
        b.setStyleSheet(
            "color: #52514e; font-size: 10px; border: 1px solid #d9d8d4; border-radius: 6px; padding: 0 4px;"
            if b.text()
            else ""
        )
        tip = fv.note or ""
        if fv.ok and fv.estimated:
            tip = tip or "Estimated"
        b.setToolTip(tip)
        val.setToolTip(tip)
        h.addWidget(b)
        if fv.status in (Status.SOURCE_UNAVAILABLE, Status.RATE_LIMITED):
            retry = QPushButton("Retry")
            retry.setFlat(True)
            retry.clicked.connect(lambda: self.retry_requested.emit(self.row.record.unitid))
            h.addWidget(retry)
        h.addStretch(1)
        return w

    def _group(self, group: str) -> QGroupBox:
        box = QGroupBox(group)
        form = QFormLayout(box)
        for key, spec in FIELDS.items():
            if spec.group == group and key not in SKIP:
                form.addRow(spec.label, self._value_widget(key))
        return box

    def _selectivity(self) -> QGroupBox:
        r = self.row.record
        box = QGroupBox("What this school weighs (CDS C7)")
        v = QVBoxLayout(box)
        fv = r.get("admission_factors")
        if not fv.ok:
            v.addWidget(QLabel("Not reported"))
        else:
            factors: dict[str, str] = fv.value
            grid = QGridLayout()
            for c, level in enumerate(IMPORTANCE_LEVELS):
                lbl = QLabel(f"<b>{level}</b>")
                grid.addWidget(lbl, 0, c)
                names = [f for f in ADMISSION_FACTORS if factors.get(f) == level]
                grid.addWidget(QLabel("\n".join(names) or "—"), 1, c, Qt.AlignmentFlag.AlignTop)
            v.addLayout(grid)
            v.addWidget(QLabel(f"<small>{badge(fv)}</small>"))
        policy = r.get("test_policy")
        v.addWidget(
            QLabel(f"Test policy: <b>{fmt_value('test_policy', policy)}</b> <small>{badge(policy)}</small>")
        )
        ed, overall = r.get("ed_rate"), r.get("acceptance_rate")
        if ed.ok and overall.ok and overall.value:
            ratio = ed.value / overall.value
            v.addWidget(
                QLabel(
                    f"Early Decision advantage: ED admit rate {ed.value:g}% vs overall "
                    f"{overall.value:g}% ({ratio:.1f}×)"
                )
            )
        else:
            v.addWidget(QLabel("Early Decision advantage: Not reported"))
        return box

    def _sources(self) -> QGroupBox:
        box = QGroupBox("Source status")
        form = QFormLayout(box)
        for src, fv in self.row.record.source_status.items():
            text = fv.status.value + (f" — {fv.note}" if fv.note else "")
            form.addRow(src, QLabel(text))
        return box

    def _linkouts(self) -> QHBoxLayout:
        h = QHBoxLayout()
        r = self.row.record
        for key, (label, _domain) in LINKOUT_SITES.items():
            b = QPushButton(f"View on {label}")
            b.clicked.connect(lambda _=False, k=key: QDesktopServices.openUrl(QUrl(linkout_url(k, r))))
            h.addWidget(b)
        if r.links.get("cds"):
            b = QPushButton("CDS document")
            b.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(r.links["cds"])))
            h.addWidget(b)
        site = r.value("website")
        if site:
            url = str(site) if str(site).startswith("http") else f"https://{site}"
            b = QPushButton("School website")
            b.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(url)))
            h.addWidget(b)
        h.addStretch(1)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        h.addWidget(close)
        return h
