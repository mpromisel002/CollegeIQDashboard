"""Student profile entry. Profiles are saved as JSON wherever the advisor chooses."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from cfa.models.student import Athletics, GreekDirection, Setting, SizePref, StudentProfile
from cfa.states import parse_states
from cfa.ui.theme import named

SCOPE_ALL = "All four-year colleges"
SCOPE_CURATED = "Curated list only (full data)"
SCOPES = [SCOPE_ALL, SCOPE_CURATED]

IMPORTANCE = ["0 - Don't care", "1 - Low", "2 - Medium", "3 - High"]


def _importance() -> QComboBox:
    c = QComboBox()
    c.addItems(IMPORTANCE)
    return c


def _enum_combo(values: list[str]) -> QComboBox:
    c = QComboBox()
    c.addItems(values)
    return c


def _optional_double(lo: float, hi: float, step: float) -> QDoubleSpinBox:
    s = QDoubleSpinBox()
    s.setRange(lo - step, hi)  # the value below `lo` means "not set"
    s.setDecimals(2)
    s.setSingleStep(step)
    s.setSpecialValueText("Not set")
    s.setValue(lo - step)
    s.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons)  # typed, not clicked
    return s


def _optional_int(lo: int, hi: int, step: int) -> QSpinBox:
    s = QSpinBox()
    s.setRange(lo - step, hi)
    s.setSingleStep(step)
    s.setSpecialValueText("Not set")
    s.setValue(lo - step)
    s.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
    return s


class StudentPanel(QWidget):
    run_requested = Signal()
    save_requested = Signal()
    load_requested = Signal()
    states_changed = Signal()  # preferred states or the "only these states" switch changed

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.name = QLineEdit()
        self.gpa = _optional_double(0.0, 4.0, 0.01)
        self.gpa_w = _optional_double(0.0, 6.0, 0.01)
        self.sat_ebrw = _optional_int(200, 800, 10)
        self.sat_math = _optional_int(200, 800, 10)
        self.act = _optional_int(1, 36, 1)
        self.submits = QCheckBox("Will submit test scores")
        self.submits.setChecked(True)
        self.major = QLineEdit()
        self.states = QLineEdit()
        self.states.setPlaceholderText("e.g. PA, NY, MA or Pennsylvania")
        self.only_states = QCheckBox("Only show schools in these states")
        self.only_states.setChecked(True)
        self.states_warning = named(QLabel(), "Warning")
        self.states_warning.setWordWrap(True)
        self.states_warning.hide()
        self.states.textChanged.connect(self._states_edited)
        self.only_states.toggled.connect(self.states_changed)
        self.size_combo = _enum_combo([s.value for s in SizePref])
        self.size_imp = _importance()
        self.setting = _enum_combo([s.value for s in Setting])
        self.setting_imp = _importance()
        self.greek_dir = _enum_combo([g.value for g in GreekDirection])
        self.greek_dir.setCurrentText(GreekDirection.NEUTRAL.value)
        self.greek_imp = _importance()
        self.housing_imp = _importance()
        self.athletics = _enum_combo([a.value for a in Athletics])
        self.athletics_imp = _importance()
        self.region_imp = _importance()
        self.abroad_imp = _importance()
        self.ed = QCheckBox("Willing to apply Early Decision")
        self.ea = QCheckBox("Willing to apply Early Action")
        self.notes = QPlainTextEdit()
        self.notes.setFixedHeight(60)

        acad = QGroupBox("Academics")
        acad.setObjectName("Section")
        f1 = QFormLayout(acad)
        f1.addRow("Student name", self.name)
        f1.addRow("Unweighted GPA (4.0)", self.gpa)
        f1.addRow("Weighted GPA", self.gpa_w)
        f1.addRow("SAT EBRW", self.sat_ebrw)
        f1.addRow("SAT Math", self.sat_math)
        f1.addRow("ACT Composite", self.act)
        f1.addRow("", self.submits)
        f1.addRow("Intended major", self.major)

        where = QGroupBox("Location")
        where.setObjectName("Section")
        f0 = QFormLayout(where)
        f0.addRow("Preferred states", self.states)
        f0.addRow("", self.states_warning)
        f0.addRow("", self.only_states)
        f0.addRow("Region importance", self.region_imp)

        prefs = QGroupBox("Campus preferences (importance 0-3)")
        prefs.setObjectName("Section")
        f2 = QFormLayout(prefs)
        f2.addRow("Size", self._pair(self.size_combo, self.size_imp))
        f2.addRow("Setting", self._pair(self.setting, self.setting_imp))
        f2.addRow("Greek life", self._pair(self.greek_dir, self.greek_imp))
        f2.addRow("On-campus housing", self.housing_imp)
        f2.addRow("Athletics", self._pair(self.athletics, self.athletics_imp))
        f2.addRow("Study abroad", self.abroad_imp)
        f2.addRow("", self.ed)
        f2.addRow("", self.ea)
        f2.addRow("Notes", self.notes)

        self.scope = QComboBox()
        self.scope.addItems(list(SCOPES))
        self.scope.setToolTip(
            "All four-year colleges: every public and private nonprofit bachelor's college in the "
            "preferred states (or the whole country), using federal data. Schools on the curated list "
            "also get their Common Data Set. Curated list: only those schools, all with full data."
        )
        self.run_btn = named(QPushButton("Run Match"), "Run")
        self.run_btn.setDefault(True)
        self.run_btn.clicked.connect(self.run_requested)
        save = QPushButton("Save profile…")
        save.clicked.connect(self.save_requested)
        load = QPushButton("Load profile…")
        load.clicked.connect(self.load_requested)

        inner = QWidget()
        v = QVBoxLayout(inner)
        v.setContentsMargins(4, 4, 8, 4)
        v.addWidget(acad)
        v.addWidget(where)
        v.addWidget(prefs)
        v.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(inner)
        buttons = QHBoxLayout()
        buttons.addWidget(load)
        buttons.addWidget(save)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(8)
        outer.addWidget(scroll, 1)
        outer.addLayout(buttons)
        scope_row = QHBoxLayout()
        scope_row.addWidget(QLabel("Search"))
        scope_row.addWidget(self.scope, 1)
        outer.addLayout(scope_row)
        outer.addWidget(self.run_btn)

    def search_all(self) -> bool:
        return self.scope.currentText() == SCOPE_ALL

    def preferred_states(self) -> tuple[list[str], bool]:
        codes, _unknown = parse_states(self.states.text())
        return codes, self.only_states.isChecked()

    def _states_edited(self) -> None:
        _codes, unknown = parse_states(self.states.text())
        if unknown:
            self.states_warning.setText(
                "Not a U.S. state, ignored: " + ", ".join(unknown) + ". Use codes like PA or full names."
            )
        self.states_warning.setVisible(bool(unknown))
        self.states_changed.emit()

    @staticmethod
    def _pair(a: QWidget, b: QWidget) -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(a, 1)
        h.addWidget(b, 1)
        return w

    @staticmethod
    def _opt(spin: QSpinBox | QDoubleSpinBox) -> float | None:
        return None if spin.value() == spin.minimum() else spin.value()

    def profile(self) -> StudentProfile:
        def i(v: float | None) -> int | None:
            return None if v is None else int(v)

        return StudentProfile(
            name=self.name.text().strip(),
            gpa_unweighted=self._opt(self.gpa),
            gpa_weighted=self._opt(self.gpa_w),
            sat_ebrw=i(self._opt(self.sat_ebrw)),
            sat_math=i(self._opt(self.sat_math)),
            act=i(self._opt(self.act)),
            submits_tests=self.submits.isChecked(),
            intended_major=self.major.text().strip(),
            preferred_states=self.states.text(),  # type: ignore[arg-type]
            only_preferred_states=self.only_states.isChecked(),
            size_pref=SizePref(self.size_combo.currentText()),
            size_importance=self.size_imp.currentIndex(),
            setting_pref=Setting(self.setting.currentText()),
            setting_importance=self.setting_imp.currentIndex(),
            greek_direction=GreekDirection(self.greek_dir.currentText()),
            greek_importance=self.greek_imp.currentIndex(),
            housing_importance=self.housing_imp.currentIndex(),
            athletics_pref=Athletics(self.athletics.currentText()),
            athletics_importance=self.athletics_imp.currentIndex(),
            region_importance=self.region_imp.currentIndex(),
            study_abroad_importance=self.abroad_imp.currentIndex(),
            ed_willing=self.ed.isChecked(),
            ea_willing=self.ea.isChecked(),
            notes=self.notes.toPlainText(),
        )

    def set_profile(self, p: StudentProfile) -> None:
        def setopt(spin, v) -> None:
            spin.setValue(spin.minimum() if v is None else v)

        self.name.setText(p.name)
        setopt(self.gpa, p.gpa_unweighted)
        setopt(self.gpa_w, p.gpa_weighted)
        setopt(self.sat_ebrw, p.sat_ebrw)
        setopt(self.sat_math, p.sat_math)
        setopt(self.act, p.act)
        self.submits.setChecked(p.submits_tests)
        self.major.setText(p.intended_major)
        self.states.setText(", ".join(p.preferred_states))
        self.only_states.setChecked(p.only_preferred_states)
        self.size_combo.setCurrentText(p.size_pref.value)
        self.size_imp.setCurrentIndex(p.size_importance)
        self.setting.setCurrentText(p.setting_pref.value)
        self.setting_imp.setCurrentIndex(p.setting_importance)
        self.greek_dir.setCurrentText(p.greek_direction.value)
        self.greek_imp.setCurrentIndex(p.greek_importance)
        self.housing_imp.setCurrentIndex(p.housing_importance)
        self.athletics.setCurrentText(p.athletics_pref.value)
        self.athletics_imp.setCurrentIndex(p.athletics_importance)
        self.region_imp.setCurrentIndex(p.region_importance)
        self.abroad_imp.setCurrentIndex(p.study_abroad_importance)
        self.ed.setChecked(p.ed_willing)
        self.ea.setChecked(p.ea_willing)
        self.notes.setPlainText(p.notes)
