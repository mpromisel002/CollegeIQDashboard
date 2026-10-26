"""Card view of the results: one card per school with badges, key stats and the reasoning."""

from __future__ import annotations

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from cfa.models.college import CollegeRecord
from cfa.models.field_value import FieldValue
from cfa.pipeline import CDS_LOADING
from cfa.scoring.academic import REACH, SAFETY, TARGET
from cfa.scoring.culture import greek_pct
from cfa.sources.cds.sections import SOURCE as CDS_SOURCE
from cfa.ui.format import fmt_value
from cfa.ui.results_table import ResultRow, location, selectivity
from cfa.ui.theme import named, pill

TIER_TONE = {SAFETY: "safety", TARGET: "target", REACH: "reach"}


def tier_pill(row: ResultRow) -> QLabel:
    tier = row.academic.tier
    text = tier if tier in TIER_TONE else "Unclassified"
    return pill(text, TIER_TONE.get(tier, "unclassified"), row.academic.reason)


def badges(row: ResultRow) -> list[QLabel]:
    """Tier, public/private, selectivity, setting and Greek life, as coloured pills."""
    r = row.record
    out = [tier_pill(row)]
    ctl = str(r.value("control") or "")
    if ctl:
        public = ctl == "Public"
        out.append(pill("Public" if public else "Private", "public" if public else "private", ctl))
    rate = r.num("acceptance_rate")
    sel = selectivity(rate)
    if sel:
        out.append(pill(sel, "selectivity", f"Admit rate {rate:g}%"))
    setting = r.value("setting")
    if setting:
        out.append(pill(str(setting), "neutral", str(r.value("locale") or "")))
    g = greek_pct(r)
    if g is not None:
        out.append(
            pill("Greek life" if g > 0 else "No Greek life", "neutral", f"About {g:.0f}% in Greek life")
        )
    if cds_loading(r):
        out.append(pill("Reading full data…", "federal", "The school's Common Data Set is still being read"))
    elif has_cds(r):
        out.append(pill("Full data", "cds", "Includes the school's Common Data Set: GPA, Greek life, ED/EA"))
    else:
        out.append(
            pill(
                "Federal data only",
                "federal",
                "Not on the curated list: GPA spread, Greek life and ED/EA numbers come only from a "
                "school's Common Data Set, so they aren't shown here.",
            )
        )
    return out


def cds_loading(r: CollegeRecord) -> bool:
    status = r.source_status.get(CDS_SOURCE)
    return status is not None and status.note == CDS_LOADING


def has_cds(r: CollegeRecord) -> bool:
    return bool(r.links.get("cds"))


def _range(lo: FieldValue, hi: FieldValue) -> str | None:
    if lo.ok and hi.ok:
        return f"{int(lo.value)}–{int(hi.value)}"
    return None


def stats(row: ResultRow) -> list[tuple[str, str, str]]:
    """(label, value, tooltip) for the card's stat grid; "—" when not available."""
    r = row.record

    def field(key: str) -> tuple[str, str]:
        fv = r.get(key)
        return (fmt_value(key, fv), "") if fv.ok else ("—", fmt_value(key, fv))

    e25, e75, m25, m75 = (r.get(k) for k in ("sat_ebrw_25", "sat_ebrw_75", "sat_math_25", "sat_math_75"))
    sat = None
    if all(f.ok for f in (e25, e75, m25, m75)):
        sat = f"{int(e25.value + m25.value)}–{int(e75.value + m75.value)}"
    act = _range(r.get("act_25"), r.get("act_75"))
    pct = row.academic.gpa_percentile
    rows = [
        ("Undergraduate enrollment", *field("undergrad_size")),
        ("Acceptance rate", *field("acceptance_rate")),
        ("Average GPA", *field("gpa_avg")),
        ("SAT middle 50%", sat or "—", "Combined EBRW + Math, 25th–75th percentile"),
        ("ACT middle 50%", act or "—", "Composite, 25th–75th percentile"),
        ("First-year retention", *field("retention_rate")),
        ("6-year graduation", *field("grad_rate_6yr")),
        (
            "Student's GPA rank",
            "—" if pct is None else f"~{pct:.0f}th pct",
            "Share of enrolled first-years with a lower GPA (from CDS C11)",
        ),
    ]
    return rows


class ResultCard(QFrame):
    details_requested = Signal(object)  # ResultRow

    def __init__(self, row: ResultRow, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.row = row
        r = row.record
        self.setObjectName("Card")
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        v = QVBoxLayout(self)
        v.setContentsMargins(18, 14, 18, 14)
        v.setSpacing(10)

        top = QHBoxLayout()
        names = QVBoxLayout()
        names.setSpacing(2)
        title = named(QLabel(r.name), "CardTitle")
        title.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        names.addWidget(title)
        names.addWidget(named(QLabel(location(r) or "Location not available"), "Muted"))
        top.addLayout(names, 1)
        score = row.culture.score
        fit = QVBoxLayout()
        fit.setSpacing(0)
        num = named(QLabel("—" if score is None else f"{score:.0f}"), "Score")
        num.setAlignment(Qt.AlignmentFlag.AlignRight)
        num.setToolTip(row.culture.explain())
        cap = named(QLabel("Culture fit" if score is not None else "Culture fit: no preferences"), "Muted")
        cap.setAlignment(Qt.AlignmentFlag.AlignRight)
        fit.addWidget(num)
        fit.addWidget(cap)
        top.addLayout(fit)
        v.addLayout(top)

        pills = QHBoxLayout()
        pills.setSpacing(8)
        for b in badges(row):
            pills.addWidget(b)
        pills.addStretch(1)
        v.addLayout(pills)

        v.addWidget(named(QFrame(), "Divider"))
        grid = QGridLayout()
        grid.setHorizontalSpacing(24)
        grid.setVerticalSpacing(8)
        for i, (label, value, tip) in enumerate(stats(row)):
            cell = QVBoxLayout()
            cell.setSpacing(1)
            cell.addWidget(named(QLabel(label), "StatLabel"))
            val = named(QLabel(value), "StatValue")
            if tip:
                val.setToolTip(tip)
            cell.addWidget(val)
            grid.addLayout(cell, i // 4, i % 4)
        for c in range(4):
            grid.setColumnStretch(c, 1)
        v.addLayout(grid)

        why = named(QFrame(), "WhyBox")
        wv = QVBoxLayout(why)
        wv.setContentsMargins(12, 8, 12, 8)
        wv.setSpacing(4)
        reason = QLabel(f"<b>Academic fit.</b> {_esc(row.academic.reason)}")
        reason.setWordWrap(True)
        wv.addWidget(reason)
        culture = QLabel(f"<b>Culture fit.</b> {_esc(culture_summary(row))}")
        culture.setWordWrap(True)
        wv.addWidget(culture)
        v.addWidget(why)

        buttons = QHBoxLayout()
        details = named(QPushButton("View details"), "Primary")
        details.clicked.connect(lambda: self.details_requested.emit(self.row))
        buttons.addWidget(details)
        site = r.value("website")
        if site:
            url = str(site) if str(site).startswith("http") else f"https://{site}"
            web = QPushButton("School website")
            web.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(url)))
            buttons.addWidget(web)
        if r.links.get("cds"):
            cds = QPushButton("Common Data Set")
            cds.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(r.links["cds"])))
            buttons.addWidget(cds)
        buttons.addStretch(1)
        v.addLayout(buttons)

    def mouseDoubleClickEvent(self, event) -> None:
        self.details_requested.emit(self.row)
        super().mouseDoubleClickEvent(event)


def culture_summary(row: ResultRow) -> str:
    """Plain-language version of the culture score's parts, for advisors."""
    fit = row.culture
    if fit.score is None:
        return fit.explain()
    parts = " · ".join(
        f"{k} {v:.0f}" for k, v in sorted(fit.parts.items(), key=lambda kv: -fit.weights[kv[0]])
    )
    text = f"{parts} (each out of 100, weighted by how much the student cares)"
    if fit.not_scored:
        text += ". No data for: " + ", ".join(fit.not_scored)
    return text


def _esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class ResultCards(QWidget):
    """Cards for the visible results, a page at a time (building thousands of cards would be slow)."""

    details_requested = Signal(object)  # ResultRow
    PAGE_SIZE = 20

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.page = 0
        self.area = QScrollArea()
        self.area.setWidgetResizable(True)
        self.area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.body = QWidget()
        self.body.setObjectName("Page")
        self.list = QVBoxLayout(self.body)
        self.list.setContentsMargins(0, 0, 8, 0)
        self.list.setSpacing(12)
        self.area.setWidget(self.body)
        self.page_label = named(QLabel(), "Muted")
        self.prev_btn = QPushButton("Previous")
        self.next_btn = QPushButton("Next")
        self.prev_btn.clicked.connect(lambda: self.show_page(self.page - 1))
        self.next_btn.clicked.connect(lambda: self.show_page(self.page + 1))
        pager = QHBoxLayout()
        pager.addWidget(self.page_label)
        pager.addStretch(1)
        pager.addWidget(self.prev_btn)
        pager.addWidget(self.next_btn)
        self.pager = QWidget()
        self.pager.setLayout(pager)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.addWidget(self.area, 1)
        v.addWidget(self.pager)
        self.cards: list[ResultCard] = []
        self.rows: list[ResultRow] = []
        self.empty_text = ""
        self.set_rows([], "Run a match to see schools here.")

    def set_rows(
        self,
        rows: list[ResultRow],
        empty_text: str = "No schools match these filters.",
        keep_page: bool = False,
    ) -> None:
        self.rows = rows
        self.empty_text = empty_text
        if keep_page:
            scroll = self.area.verticalScrollBar().value()
            self.show_page(self.page)
            self.area.verticalScrollBar().setValue(scroll)
        else:
            self.show_page(0)

    def show_page(self, page: int) -> None:
        pages = max(1, -(-len(self.rows) // self.PAGE_SIZE))
        self.page = max(0, min(page, pages - 1))
        while self.list.count():
            item = self.list.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.deleteLater()
        self.cards = []
        if not self.rows:
            msg = named(QLabel(self.empty_text), "Empty")
            msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
            msg.setWordWrap(True)
            self.list.addWidget(msg)
        start = self.page * self.PAGE_SIZE
        for row in self.rows[start : start + self.PAGE_SIZE]:
            card = ResultCard(row)
            card.details_requested.connect(self.details_requested)
            self.cards.append(card)
            self.list.addWidget(card)
        self.list.addStretch(1)
        self.area.verticalScrollBar().setValue(0)
        end = min(start + self.PAGE_SIZE, len(self.rows))
        self.page_label.setText(f"{start + 1}–{end} of {len(self.rows)}" if self.rows else "")
        self.prev_btn.setEnabled(self.page > 0)
        self.next_btn.setEnabled(self.page < pages - 1)
        self.pager.setVisible(len(self.rows) > self.PAGE_SIZE)
