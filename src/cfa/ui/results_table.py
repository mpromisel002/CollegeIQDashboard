"""Ranked results list with sorting and filters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QPersistentModelIndex, QSortFilterProxyModel, Qt
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QTableView, QWidget

from cfa.models.college import CollegeRecord
from cfa.scoring.academic import REACH, SAFETY, TARGET, AcademicFit
from cfa.scoring.culture import CultureFit, greek_pct, size_band
from cfa.ui.format import fmt_value

COLUMNS = ["Name", "State", "Academic tier", "Culture score", "Admit rate", "Greek %", "Setting", "Size"]
TIER_ORDER = {SAFETY: 0, TARGET: 1, REACH: 2}
SORT_ROLE = Qt.ItemDataRole.UserRole + 1


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
        if col == 0:
            return r.name, r.name.lower(), ""
        if col == 1:
            st = r.value("state")
            return str(st or "—"), str(st or "~"), ""
        if col == 2:
            return row.academic.tier, TIER_ORDER.get(row.academic.tier, 3), row.academic.reason
        if col == 3:
            s = row.culture.score
            return ("—" if s is None else f"{s:.0f}"), (-1 if s is None else s), row.culture.explain()
        if col == 4:
            fv = r.get("acceptance_rate")
            return (
                fmt_value("acceptance_rate", fv),
                (fv.value if fv.ok else 999),
                f"Source: {fv.source} {fv.year or ''}",
            )
        if col == 5:
            g = greek_pct(r)
            tip = (
                f"Men {fmt_value('greek_men_pct', r.get('greek_men_pct'))}; "
                f"women {fmt_value('greek_women_pct', r.get('greek_women_pct'))}"
            )
            return ("—" if g is None else f"{g:.0f}%"), (-1 if g is None else g), tip
        if col == 6:
            setting = r.value("setting")
            return str(setting or "—"), str(setting or "~"), str(r.value("locale") or "")
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
    def __init__(self) -> None:
        super().__init__()
        self.setSortRole(SORT_ROLE)
        self.tier = "Any"
        self.state = ""
        self.greek = "Any"
        self.setting = "Any"
        self.size = "Any"

    def set_filters(self, **kw: str) -> None:
        if hasattr(self, "beginFilterChange"):  # Qt >= 6.9
            self.beginFilterChange()
            for k, v in kw.items():
                setattr(self, k, v)
            self.endFilterChange(QSortFilterProxyModel.Direction.Rows)
        else:
            for k, v in kw.items():
                setattr(self, k, v)
            self.invalidateFilter()

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex | QPersistentModelIndex) -> bool:
        model = self.sourceModel()
        assert isinstance(model, ResultsModel)
        row = model.rows[source_row]
        r = row.record
        if self.tier != "Any" and not row.academic.tier.startswith(self.tier):
            return False
        if self.state:
            wanted = {s.strip().upper() for s in self.state.split(",") if s.strip()}
            if wanted and str(r.value("state") or "").upper() not in wanted:
                return False
        if self.greek != "Any":
            g = greek_pct(r)
            if g is None:
                return False
            if self.greek == "Has Greek life" and g <= 0:
                return False
            if self.greek == "No Greek life" and g > 0:
                return False
        if self.setting != "Any" and r.value("setting") != self.setting:
            return False
        if self.size != "Any":
            n = r.num("undergrad_size")
            if n is None or size_band(n).value != self.size:
                return False
        return True


class ResultsTable(QTableView):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.results_model = ResultsModel()
        self.proxy = ResultsFilter()
        self.proxy.setSourceModel(self.results_model)
        self.setModel(self.proxy)
        self.setSortingEnabled(True)
        self.sortByColumn(2, Qt.SortOrder.AscendingOrder)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setAlternatingRowColors(True)
        self.verticalHeader().setVisible(False)
        self.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for c in range(1, len(COLUMNS)):
            self.horizontalHeader().setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)

    def row_at(self, index: QModelIndex) -> ResultRow | None:
        if not index.isValid():
            return None
        return self.proxy.data(index, Qt.ItemDataRole.UserRole)

    def visible_rows(self) -> list[ResultRow]:
        return [
            self.proxy.data(self.proxy.index(i, 0), Qt.ItemDataRole.UserRole)
            for i in range(self.proxy.rowCount())
        ]
