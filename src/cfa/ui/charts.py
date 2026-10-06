"""Small matplotlib charts embedded in the detail view (single series: no legend, direct labels)."""

from __future__ import annotations

import matplotlib

matplotlib.use("QtAgg")

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure

from cfa.models.college import GPA_BINS, CollegeRecord

SERIES = "#2a78d6"  # categorical slot 1 (validated reference palette)
TEXT = "#0b0b0b"
MUTED = "#52514e"
GRID = "#e4e3df"
SURFACE = "#fcfcfb"


def _style(ax) -> None:
    ax.set_facecolor(SURFACE)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.tick_params(colors=MUTED, labelsize=8, length=0)
    ax.yaxis.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


class ChartCanvas(FigureCanvasQTAgg):
    def __init__(self, width: float = 4.6, height: float = 2.4) -> None:
        self.figure = Figure(figsize=(width, height), dpi=100, facecolor=SURFACE, layout="constrained")
        super().__init__(self.figure)
        self.setMinimumHeight(int(height * 80))

    def show_message(self, title: str, message: str) -> None:
        self.figure.clear()
        ax = self.figure.add_subplot(111)
        ax.axis("off")
        ax.set_title(title, fontsize=9, color=TEXT, loc="left")
        ax.text(0.5, 0.5, message, ha="center", va="center", fontsize=9, color=MUTED, transform=ax.transAxes)
        self.draw_idle()


def gpa_chart(canvas: ChartCanvas, college: CollegeRecord) -> None:
    dist = college.value("gpa_dist")
    fv = college.get("gpa_dist")
    title = "GPA distribution of enrolled first-years"
    if not isinstance(dist, dict):
        canvas.show_message(title, "Not reported in this school's Common Data Set")
        return
    canvas.figure.clear()
    ax = canvas.figure.add_subplot(111)
    _style(ax)
    labels = list(GPA_BINS)
    vals = [dist.get(b, 0.0) for b in labels]
    bars = ax.bar(range(len(labels)), vals, width=0.6, color=SERIES, edgecolor=SURFACE, linewidth=2)
    ax.set_xticks(range(len(labels)), labels, rotation=35, ha="right")
    ax.set_ylabel("% of students", fontsize=8, color=MUTED)
    ax.set_title(f"{title} (CDS {fv.year})", fontsize=9, color=TEXT, loc="left")
    top = max(vals) if vals else 0
    for b, v in zip(bars, vals, strict=True):
        if v >= max(5.0, top * 0.25):  # selective direct labels
            ax.text(
                b.get_x() + b.get_width() / 2,
                v + top * 0.02,
                f"{v:.0f}%",
                ha="center",
                va="bottom",
                fontsize=7,
                color=TEXT,
            )
    ax.set_ylim(0, top * 1.18 if top else 1)
    canvas.draw_idle()


def admit_round_chart(canvas: ChartCanvas, college: CollegeRecord) -> None:
    title = "Admit rate by round"
    items: list[tuple[str, float, bool]] = []
    no_early = college.value("ed_offered") is False and college.value("ea_offered") is False
    for key, label in (
        ("ed_rate", "Early Decision"),
        ("ea_rate", "Early Action"),
        ("rd_rate", "Regular (est.)"),
        ("acceptance_rate", "Overall"),
    ):
        fv = college.get(key)
        if key == "rd_rate" and no_early:
            continue  # with no early rounds, "regular" is just the overall rate
        if fv.ok:
            items.append((label, float(fv.value), fv.estimated))
    if not items:
        canvas.show_message(title, "No admit-rate data reported")
        return
    canvas.figure.clear()
    ax = canvas.figure.add_subplot(111)
    _style(ax)
    xs = range(len(items))
    vals = [v for _, v, _ in items]
    bars = ax.bar(xs, vals, width=0.55, color=SERIES, edgecolor=SURFACE, linewidth=2)
    for b, (_, _, est) in zip(bars, items, strict=True):
        if est:  # texture marks an estimate, so it is not color-alone
            b.set_hatch("///")
            b.set_facecolor("#86b6ef")
    ax.set_xticks(list(xs), [lbl for lbl, _, _ in items])
    ax.set_ylabel("% admitted", fontsize=8, color=MUTED)
    ax.set_title(title, fontsize=9, color=TEXT, loc="left")
    top = max(vals)
    for b, v in zip(bars, vals, strict=True):
        ax.text(
            b.get_x() + b.get_width() / 2,
            v + top * 0.02,
            f"{v:.0f}%",
            ha="center",
            va="bottom",
            fontsize=8,
            color=TEXT,
        )
    ax.set_ylim(0, top * 1.2)
    pad = max(0.0, (3 - len(items)) / 2)  # keep bars slim when there are only one or two
    ax.set_xlim(-0.6 - pad, len(items) - 0.4 + pad)
    canvas.draw_idle()
