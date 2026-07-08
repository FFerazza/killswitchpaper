"""Shared figure style: the validated default palette from the dataviz
skill (references/palette.md), light mode only (print/PDF paper figures).
Categorical hues are assigned in FIXED order, never cycled arbitrarily -
CATEGORICAL is the ordering that maximizes minimum adjacent CVD separation.
"""

from pathlib import Path

import matplotlib.pyplot as plt

CATEGORICAL = [
    "#2a78d6",  # 1 blue
    "#1baf7a",  # 2 aqua
    "#eda100",  # 3 yellow
    "#008300",  # 4 green
    "#4a3aa7",  # 5 violet
    "#e34948",  # 6 red
    "#e87ba4",  # 7 magenta
    "#eb6834",  # 8 orange
]

SEQUENTIAL_BLUE = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#1c5cab", "#0d366b"]

INK_PRIMARY = "#0b0b0b"
INK_SECONDARY = "#52514e"
INK_MUTED = "#898781"
GRIDLINE = "#e1e0d9"
AXIS = "#c3c2b7"
SURFACE = "#ffffff"  # print figures: plain white, not the app chart surface

STATUS = {"good": "#0ca30c", "warning": "#fab219", "serious": "#ec835a", "critical": "#d03b3b"}

PAPER_FIGURES_DIR = Path(__file__).resolve().parents[2] / "paper" / "figures"


def apply_style() -> None:
    plt.rcParams.update({
        # matplotlib defaults to Type 3 (bitmap) font embedding in PDFs,
        # which some PDF viewers render as garbled/placeholder glyphs even
        # though the file is well-formed. Type 42 (TrueType) is the
        # standard fix - real outline fonts, renders correctly everywhere.
        "pdf.fonttype": 42,
        "ps.fonttype": 42,
        "figure.facecolor": SURFACE,
        "axes.facecolor": SURFACE,
        "axes.edgecolor": AXIS,
        "axes.labelcolor": INK_SECONDARY,
        "axes.grid": True,
        "grid.color": GRIDLINE,
        "grid.linewidth": 0.6,
        "text.color": INK_PRIMARY,
        "xtick.color": INK_MUTED,
        "ytick.color": INK_MUTED,
        "font.family": "sans-serif",
        "font.size": 9,
        "axes.titlesize": 10,
        "axes.titleweight": "bold",
        "legend.frameon": False,
        "savefig.facecolor": SURFACE,
        "savefig.bbox": "tight",
    })


def clean_axes(ax) -> None:
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color(AXIS)
    ax.spines["bottom"].set_color(AXIS)
    ax.grid(axis="y", alpha=0.7)
    ax.grid(axis="x", visible=False)


def savefig(fig, name: str) -> Path:
    PAPER_FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    out = PAPER_FIGURES_DIR / f"{name}.pdf"
    fig.savefig(out)
    return out
