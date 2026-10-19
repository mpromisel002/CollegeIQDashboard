"""Results filters as checkbox groups. Nothing ticked in a group means "any"."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QCheckBox, QGroupBox, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget

from cfa.models.student import SizePref
from cfa.ui.results_table import SELECTIVITY
from cfa.ui.theme import named

SIZE_LABELS = {
    SizePref.SMALL.value: "Small (under 5,000)",
    SizePref.MEDIUM.value: "Medium (5,000–15,000)",
    SizePref.LARGE.value: "Large (15,000–30,000)",
    SizePref.HUGE.value: "Very large (30,000+)",
}

# (filter key, section title, [(value, label)])
GROUPS: list[tuple[str, str, list[tuple[str, str]]]] = [
    (
        "tiers",
        "Academic fit",
        [("Safety", "Safety"), ("Target", "Target"), ("Reach", "Reach"), ("Unclassified", "Not enough data")],
    ),
    ("sizes", "Student body size", list(SIZE_LABELS.items())),
    ("settings", "Campus setting", [(s, s) for s in ("City", "Suburb", "Town", "Rural")]),
    (
        "selectivity",
        "Admissions selectivity",
        [
            (label, f"{label} ({lo:g}–{min(hi, 100):g}%)" if lo else f"{label} (under {hi:g}%)")
            for label, lo, hi in SELECTIVITY
        ],
    ),
    ("control", "College type", [("Public", "Public"), ("Private", "Private")]),
    ("greek", "Greek life", [("Has Greek life", "Has fraternities/sororities"), ("No Greek life", "None")]),
    (
        "data_level",
        "Data available",
        [("Full", "Full data (Common Data Set)"), ("Federal", "Federal data only")],
    ),
]


class FilterPanel(QScrollArea):
    changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        body = QWidget()
        v = QVBoxLayout(body)
        v.setContentsMargins(4, 4, 8, 4)
        self.state_note = named(QLabel(), "Muted")
        self.state_note.setWordWrap(True)
        loc = QGroupBox("Location")
        loc.setObjectName("Section")
        lv = QVBoxLayout(loc)
        lv.addWidget(self.state_note)
        v.addWidget(loc)
        self.boxes: dict[str, dict[str, QCheckBox]] = {}
        for key, title, options in GROUPS:
            box = QGroupBox(title)
            box.setObjectName("Section")
            bv = QVBoxLayout(box)
            bv.setSpacing(2)
            self.boxes[key] = {}
            for value, label in options:
                cb = QCheckBox(label)
                cb.toggled.connect(self.changed)
                bv.addWidget(cb)
                self.boxes[key][value] = cb
            v.addWidget(box)
        reset = QPushButton("Clear all filters")
        reset.clicked.connect(self.clear)
        v.addWidget(reset)
        v.addStretch(1)
        self.setWidget(body)
        self.set_states([], True)

    def values(self) -> dict[str, set[str]]:
        return {key: {v for v, cb in boxes.items() if cb.isChecked()} for key, boxes in self.boxes.items()}

    def check(self, key: str, value: str, on: bool = True) -> None:
        self.boxes[key][value].setChecked(on)

    def clear(self) -> None:
        for boxes in self.boxes.values():
            for cb in boxes.values():
                cb.blockSignals(True)
                cb.setChecked(False)
                cb.blockSignals(False)
        self.changed.emit()

    def set_states(self, states: list[str], only: bool) -> None:
        if not states:
            self.state_note.setText("All states. Add preferred states on the Student tab to narrow the list.")
        elif only:
            self.state_note.setText(
                f"Only schools in <b>{', '.join(states)}</b> (from the student's preferred states)."
            )
        else:
            self.state_note.setText(
                f"All states. Preferred states ({', '.join(states)}) only count toward culture fit."
            )
