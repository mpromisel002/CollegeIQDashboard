"""App-wide look: a fixed light palette and one stylesheet, so the app looks the same on every PC."""

from __future__ import annotations

from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication, QLabel, QWidget

NAVY = "#14425e"  # header bar
INK = "#1d2833"  # main text
MUTED = "#5d6b78"  # labels, secondary text
BORDER = "#dce2e8"
PAGE = "#f3f5f8"  # window background
SURFACE = "#ffffff"  # cards, panels
SLATE = "#3b4a5e"  # primary buttons
ACCENT = "#2a6fdb"  # focus, progress, links
TINT = "#eef4f7"  # "why this tier" box
TINT_BORDER = "#c9dbe3"

# Pill colours: (background, text). Text colours meet 4.5:1 contrast on their background.
TONES: dict[str, tuple[str, str]] = {
    "safety": ("#d7f0dd", "#1b6331"),
    "target": ("#d9e5fb", "#1f4c9c"),
    "reach": ("#fde2c8", "#8f4307"),
    "unclassified": ("#e6e9ed", "#46505b"),
    "public": ("#dde1fb", "#33409a"),
    "private": ("#d5efe2", "#1d6343"),
    "selectivity": ("#fbe8cc", "#80500a"),
    "neutral": ("#edf0f3", "#3f4a55"),
}

STYLESHEET = f"""
QWidget {{
    color: {INK};
    font-size: 10pt;
}}
QMainWindow, QDialog, QWidget#Page {{
    background: {PAGE};
}}
QToolTip {{
    color: {INK};
    background: {SURFACE};
    border: 1px solid {BORDER};
    padding: 4px 6px;
}}

/* Header bar */
QFrame#HeaderBar {{
    background: {NAVY};
}}
QFrame#HeaderBar QLabel {{
    color: #ffffff;
}}
QLabel#AppTitle {{
    font-size: 14pt;
    font-weight: 600;
}}
QLabel#HeaderInfo {{
    color: #cfdde7;
}}
QFrame#HeaderBar QToolButton {{
    color: #ffffff;
    background: transparent;
    border: none;
    padding: 6px 10px;
    border-radius: 6px;
}}
QFrame#HeaderBar QToolButton:hover {{
    background: rgba(255, 255, 255, 0.14);
}}
QFrame#HeaderBar QToolButton::menu-indicator {{
    image: none;
}}

/* Panels and cards */
QFrame#Panel, QFrame#Card {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 10px;
}}
QFrame#Card:hover {{
    border-color: #b9c4cf;
}}
QFrame#Divider {{
    background: {BORDER};
    border: none;
    max-height: 1px;
    min-height: 1px;
}}
QFrame#WhyBox {{
    background: {TINT};
    border: 1px solid {TINT_BORDER};
    border-radius: 8px;
}}
QLabel#PageTitle {{
    font-size: 17pt;
    font-weight: 600;
}}
QLabel#CardTitle {{
    font-size: 13pt;
    font-weight: 600;
}}
QLabel#Muted, QLabel#StatLabel {{
    color: {MUTED};
}}
QLabel#StatValue {{
    font-size: 11pt;
    font-weight: 600;
}}
QLabel#Score {{
    font-size: 20pt;
    font-weight: 600;
}}
QLabel#Warning {{
    color: #8f4307;
}}
QLabel#Empty {{
    color: {MUTED};
    font-size: 11pt;
    padding: 40px;
}}
QLabel[tone] {{
    border-radius: 10px;
    padding: 2px 12px;
    font-weight: 500;
}}
{"".join(f'QLabel[tone="{k}"] {{ background: {bg}; color: {fg}; }}' for k, (bg, fg) in TONES.items())}

/* Sidebar sections */
QGroupBox {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 10px;
    margin-top: 22px;
    padding: 12px 10px 10px 10px;
    font-weight: 600;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 4px;
    padding: 0 2px;
    font-size: 11pt;
}}
QGroupBox#Section {{
    border: none;
    border-top: 1px solid {BORDER};
    border-radius: 0;
    background: transparent;
    padding: 10px 0 0 0;
}}
QGroupBox QLabel, QGroupBox QCheckBox {{
    font-weight: 400;
}}
QScrollArea, QScrollArea > QWidget > QWidget {{
    background: transparent;
    border: none;
}}

/* Inputs */
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QPlainTextEdit {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 4px 8px;
    min-height: 22px;
    selection-background-color: {ACCENT};
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QPlainTextEdit:focus {{
    border-color: {ACCENT};
}}
QComboBox QAbstractItemView {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    selection-background-color: #e3ecf7;
    selection-color: {INK};
}}
QComboBox::drop-down {{
    border: none;
    width: 22px;
}}
QComboBox::down-arrow {{
    image: url(@CHEVRON@);
    width: 10px;
    height: 6px;
}}
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 2px;
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 10px;
    margin: 2px;
}}
QScrollBar::handle {{
    background: #c3ccd5;
    border-radius: 3px;
    min-height: 32px;
    min-width: 32px;
}}
QScrollBar::handle:hover {{
    background: #a6b2be;
}}
QScrollBar::add-line, QScrollBar::sub-line {{
    width: 0;
    height: 0;
}}
QScrollBar::add-page, QScrollBar::sub-page {{
    background: none;
}}
QCheckBox {{
    spacing: 8px;
    padding: 2px 0;
}}
QCheckBox::indicator {{
    width: 15px;
    height: 15px;
    border: 1px solid #8c99a6;
    border-radius: 3px;
    background: {SURFACE};
}}
QCheckBox::indicator:hover {{
    border-color: {SLATE};
}}
QCheckBox::indicator:checked {{
    background: {SLATE};
    border-color: {SLATE};
    image: url(@CHECK@);
}}

/* Buttons */
QPushButton {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 6px 14px;
}}
QPushButton:hover {{
    background: #eef2f6;
}}
QPushButton:disabled {{
    color: #9aa5b0;
}}
QPushButton#Primary {{
    background: {SLATE};
    color: #ffffff;
    border: none;
    font-weight: 600;
}}
QPushButton#Primary:hover {{
    background: #2c394a;
}}
QPushButton#Primary:disabled {{
    background: #9aa5b0;
}}
QPushButton#Run {{
    background: {NAVY};
    color: #ffffff;
    border: none;
    font-size: 11pt;
    font-weight: 600;
    padding: 10px;
}}
QPushButton#Run:hover {{
    background: #0e3249;
}}
QPushButton#Run:disabled {{
    background: #9aa5b0;
}}
QPushButton#Link {{
    background: transparent;
    border: none;
    color: {ACCENT};
    padding: 2px 4px;
}}
QPushButton#Link:hover {{
    text-decoration: underline;
}}
QPushButton#Segment {{
    border-radius: 0;
    padding: 6px 14px;
}}
QPushButton#Segment:checked {{
    background: {SLATE};
    color: #ffffff;
    border-color: {SLATE};
}}

/* Tabs */
QTabWidget::pane {{
    border: none;
}}
QTabBar::tab {{
    background: transparent;
    color: {MUTED};
    padding: 8px 18px;
    border: none;
    border-bottom: 2px solid transparent;
    font-weight: 600;
}}
QTabBar::tab:selected {{
    color: {INK};
    border-bottom-color: {NAVY};
}}

/* Table */
QTableView {{
    background: {SURFACE};
    alternate-background-color: #f8fafb;
    border: 1px solid {BORDER};
    border-radius: 10px;
    gridline-color: transparent;
    selection-background-color: #e3ecf7;
    selection-color: {INK};
}}
QTableView::item {{
    padding: 6px 8px;
    border-bottom: 1px solid #edf0f3;
}}
QHeaderView::section {{
    background: {SURFACE};
    color: {MUTED};
    border: none;
    border-bottom: 1px solid {BORDER};
    padding: 8px;
    font-weight: 600;
}}

/* Progress, status bar, banners */
QProgressBar {{
    background: #e2e7ec;
    border: none;
    border-radius: 5px;
    min-height: 18px;
    text-align: center;
    color: {INK};
}}
QProgressBar::chunk {{
    background: #8fb4ee;
    border-radius: 5px;
}}
QStatusBar {{
    background: {SURFACE};
    border-top: 1px solid {BORDER};
    color: {MUTED};
}}
QLabel#Banner {{
    background: #fff4d6;
    color: #5a4300;
    border: 1px solid #f0dc9f;
    border-radius: 8px;
    padding: 8px 12px;
}}
QLabel#Toast {{
    background: {INK};
    color: #ffffff;
    border-radius: 8px;
    padding: 8px 12px;
}}
"""


def stylesheet() -> str:
    from cfa import config

    def asset(name: str) -> str:
        path = config.bundled_path(f"cfa/ui/{name}")
        if not path.exists():
            path = config.bundled_path(f"src/cfa/ui/{name}")
        return path.as_posix()

    return STYLESHEET.replace("@CHEVRON@", asset("chevron.png")).replace("@CHECK@", asset("check.png"))


def apply_theme(app: QApplication) -> None:
    """Fusion style + a light palette, so Windows dark mode or old themes don't fight the stylesheet."""
    app.setStyle("Fusion")
    pal = QPalette()
    for role, color in (
        (QPalette.ColorRole.Window, PAGE),
        (QPalette.ColorRole.WindowText, INK),
        (QPalette.ColorRole.Base, SURFACE),
        (QPalette.ColorRole.AlternateBase, "#f8fafb"),
        (QPalette.ColorRole.Text, INK),
        (QPalette.ColorRole.Button, SURFACE),
        (QPalette.ColorRole.ButtonText, INK),
        (QPalette.ColorRole.Highlight, ACCENT),
        (QPalette.ColorRole.HighlightedText, "#ffffff"),
        (QPalette.ColorRole.ToolTipBase, SURFACE),
        (QPalette.ColorRole.ToolTipText, INK),
        (QPalette.ColorRole.PlaceholderText, "#8a96a3"),
        (QPalette.ColorRole.Link, ACCENT),
    ):
        pal.setColor(role, QColor(color))
    app.setPalette(pal)
    font = QFont()
    font.setFamilies(["Segoe UI", "Inter", "Helvetica Neue", "Arial"])
    font.setPointSize(10)
    app.setFont(font)
    app.setStyleSheet(stylesheet())


def pill(text: str, tone: str, tip: str = "") -> QLabel:
    lbl = QLabel(text)
    lbl.setProperty("tone", tone if tone in TONES else "neutral")
    if tip:
        lbl.setToolTip(tip)
    return lbl


def named[W: QWidget](widget: W, name: str) -> W:
    widget.setObjectName(name)
    return widget
