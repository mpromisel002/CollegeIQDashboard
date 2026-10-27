"""Ranked results: the shared model, its filters and sorting, and the table view."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QPersistentModelIndex, QSortFilterProxyModel, Qt
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QTableView, QWidget

from cfa.models.college import CollegeRecord
from cfa.scoring.academic import REACH, SAFETY, TARGET, AcademicFit
from cfa.scoring.culture import CultureFit, greek_pct, size_band
from cfa.ui.format import fmt_value

COLUMNS = [
    "Name",
    "Location",
    "Type",
    "Academic tier",
    "Culture fit",
    "Admit rate",
    "Avg GPA",
    "Greek %",
    "Setting",
    "Undergrads",
    "Net price",
]
COL_NAME, COL_TIER, COL_CULTURE, COL_RATE, COL_SIZE, COL_NET = 0, 3, 4, 5, 9, 10
TIER_ORDER = {SAFETY: 0, TARGET: 1, REACH: 2}
SORT_ROLE = Qt.ItemDataRole.UserRole + 1

# Admit-rate bands shown as a badge and offered as a filter.
SELECTIVITY = [
    ("Most selective", 0.0, 20.0),
    ("Highly selective", 20.0, 40.0),
    ("Moderately selective", 40.0, 70.0),
    ("Less selective", 70.0, 100.01),
]


# Average net price bands offered as a filter.
NET_PRICE_BANDS = [
    ("Under $15,000", 0, 15_000),
    ("$15,000–$25,000", 15_000, 25_000),
    ("$25,000–$40,000", 25_000, 40_000),
    ("$40,000 or more", 40_000, 10**9),
]


def net_price_band(v: float | None) -> str | None:
    if v is None:
        return None
    return next((label for label, lo, hi in NET_PRICE_BANDS if lo <= v < hi), None)


def selectivity(rate: float | None) -> str | None:
    if rate is None:
        return None
    for label, lo, hi in SELECTIVITY:
        if lo <= rate < hi:
            return label
    return None


def location(r: CollegeRecord) -> str:
    return ", ".join(str(v) for v in (r.value("city"), r.value("state")) if v)


def best_match_key(row: ResultRow) -> float:
    """Safety, then Target, then Reach, then unclassified; within a tier, best culture fit first."""
    s = row.culture.score
    return TIER_ORDER.get(row.academic.tier, 3) * 1000 + (101 if s is None else 100 - s)


@dataclass
class ResultRow:
    record: CollegeRecord
    academic: AcademicFit
    culture: CultureFit


class ResultsModel(QAbstractTableModel):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[ResultRow] = []

    def set_rows(self, rows: list[ResultRow]) -> None:
        self.beginResetModel()
        self.rows = rows
        self.endResetModel()

    def rowCount(self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()) -> int:  # noqa: B008
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()) -> int:  # noqa: B008
        return len(COLUMNS)

    def headerData(
        self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole
    ) -> Any:
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return COLUMNS[section]
        return None

    def _cell(self, row: ResultRow, col: int) -> tuple[str, Any, str]:
        """(display text, sort key, tooltip)."""
        r = row.record
        if col == COL_NAME:
            return r.name, r.name.lower(), r.name
        if col == 1:
            loc = location(r)
            return loc or "—", str(r.value("state") or "~") + loc, ""
        if col == 2:
            ctl = r.value("control")
            return str(ctl or "—"), str(ctl or "~"), ""
        if col == COL_TIER:
            return row.academic.tier, best_match_key(row), row.academic.reason
        if col == COL_CULTURE:
            s = row.culture.score
            return ("—" if s is None else f"{s:.0f}"), (-1 if s is None else s), row.culture.explain()
        if col == COL_RATE:
            fv = r.get("acceptance_rate")
            return (
                fmt_value("acceptance_rate", fv) if fv.ok else "—",
                (fv.value if fv.ok else 999),
                f"Source: {fv.source} {fv.year or ''}" if fv.ok else fmt_value("acceptance_rate", fv),
            )
        if col == 6:
            fv = r.get("gpa_avg")
            return (fmt_value("gpa_avg", fv) if fv.ok else "—"), (fv.value if fv.ok else -1), ""
        if col == 7:
            g = greek_pct(r)
            tip = (
                f"Men {fmt_value('greek_men_pct', r.get('greek_men_pct'))}; "
                f"women {fmt_value('greek_women_pct', r.get('greek_women_pct'))}"
            )
            return ("—" if g is None else f"{g:.0f}%"), (-1 if g is None else g), tip
        if col == 8:
            setting = r.value("setting")
            return str(setting or "—"), str(setting or "~"), str(r.value("locale") or "")
        if col == COL_NET:
            fv = r.get("net_price_avg")
            return (
                fmt_value("net_price_avg", fv) if fv.ok else "—",
                (fv.value if fv.ok else 10**9),
                "Average yearly cost after grants (College Scorecard)"
                if fv.ok
                else fmt_value("net_price_avg", fv),
            )
        n = r.num("undergrad_size")
        return (
            ("—" if n is None else f"{int(n):,}"),
            (-1 if n is None else n),
            ("" if n is None else f"Band {size_band(n).value}"),
        )

    def data(
        self, index: QModelIndex | QPersistentModelIndex, role: int = Qt.ItemDataRole.DisplayRole
    ) -> Any:
        if not index.isValid():
            return None
        row = self.rows[index.row()]
        text, key, tip = self._cell(row, index.column())
        if role == Qt.ItemDataRole.DisplayRole:
            return text
        if role == SORT_ROLE:
            return key
        if role == Qt.ItemDataRole.ToolTipRole:
            return tip or None
        if role == Qt.ItemDataRole.UserRole:
            return row
        return None


class ResultsFilter(QSortFilterProxyModel):
    """Every filter is a set of allowed values; an empty set means "any"."""

    def __init__(self) -> None:
        super().__init__()
        self.setSortRole(SORT_ROLE)
        self.states: set[str] = set()
        self.tiers: set[str] = set()
        self.sizes: set[str] = set()
        self.settings: set[str] = set()
        self.selectivity: set[str] = set()
        self.control: set[str] = set()
        self.greek: set[str] = set()  # "Has Greek life" / "No Greek life"
        self.data_level: set[str] = set()  # "Full" (has a Common Data Set) / "Federal"
        self.net_price: set[str] = set()  # NET_PRICE_BANDS labels

    def set_filters(self, **kw: set[str]) -> None:
        if hasattr(self, "beginFilterChange"):  # Qt >= 6.9
            self.beginFilterChange()
            for k, v in kw.items():
                setattr(self, k, set(v))
            self.endFilterChange(QSortFilterProxyModel.Direction.Rows)
        else:
            for k, v in kw.items():
                setattr(self, k, set(v))
            self.invalidateFilter()

    def in_states(self, r: CollegeRecord) -> bool:
        # A school whose state could not be confirmed is hidden too: the filter is strict.
        return not self.states or str(r.value("state") or "").upper() in self.states

    def accepts(self, row: ResultRow, *, check_states: bool = True) -> bool:
        r = row.record
        if check_states and not self.in_states(r):
            return False
        if self.tiers:
            tier = row.academic.tier if row.academic.tier in TIER_ORDER else "Unclassified"
            if tier not in self.tiers:
                return False
        if self.sizes:
            n = r.num("undergrad_size")
            if n is None or size_band(n).value not in self.sizes:
                return False
        if self.settings and r.value("setting") not in self.settings:
            return False
        if self.selectivity and selectivity(r.num("acceptance_rate")) not in self.selectivity:
            return False
        if self.control:
            ctl = str(r.value("control") or "")
            kind = "Public" if ctl == "Public" else "Private" if ctl.startswith("Private") else ""
            if kind not in self.control:
                return False
        if self.net_price and net_price_band(r.num("net_price_avg")) not in self.net_price:
            return False
        if self.data_level and ("Full" if r.links.get("cds") else "Federal") not in self.data_level:
            return False
        if self.greek:
            g = greek_pct(r)
            if g is None:
                return False
            if (g > 0 and "Has Greek life" not in self.greek) or (
                g <= 0 and "No Greek life" not in self.greek
            ):
                return False
        return True

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex | QPersistentModelIndex) -> bool:
        model = self.sourceModel()
        assert isinstance(model, ResultsModel)
        return self.accepts(model.rows[source_row])

    def hidden_by_state(self) -> int:
        """Schools that pass every other filter but are outside the preferred states."""
        model = self.sourceModel()
        assert isinstance(model, ResultsModel)
        return sum(
            1
            for row in model.rows
            if not self.in_states(row.record) and self.accepts(row, check_states=False)
        )


class ResultsTable(QTableView):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.results_model = ResultsModel()
        self.proxy = ResultsFilter()
        self.proxy.setSourceModel(self.results_model)
        self.setModel(self.proxy)
        self.setSortingEnabled(True)
        self.sortByColumn(COL_TIER, Qt.SortOrder.AscendingOrder)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setAlternatingRowColors(True)
        self.setShowGrid(False)
        self.setWordWrap(False)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(38)
        self.horizontalHeader().setHighlightSections(False)
        self.horizontalHeader().setDefaultAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        header = self.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        # Long names would push every other column off screen; they are elided, full name on hover.
        header.setSectionResizeMode(COL_NAME, QHeaderView.ResizeMode.Interactive)
        header.resizeSection(COL_NAME, 300)
        header.setStretchLastSection(True)
        self.setTextElideMode(Qt.TextElideMode.ElideRight)

    def row_at(self, index: QModelIndex) -> ResultRow | None:
        if not index.isValid():
            return None
        return self.proxy.data(index, Qt.ItemDataRole.UserRole)

    def visible_rows(self) -> list[ResultRow]:
        return [
            self.proxy.data(self.proxy.index(i, 0), Qt.ItemDataRole.UserRole)
            for i in range(self.proxy.rowCount())
        ]
