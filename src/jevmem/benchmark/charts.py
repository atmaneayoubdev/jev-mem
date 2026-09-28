"""Static benchmark charts (PNG) for reports and the README.

Palette: the validated reference categorical slots (light surface). Every chart has a table
twin in report.md. Colour follows the entity, never its rank:
hybrid-jev = blue, hybrid-qwen = orange, embedding = aqua, rerank = yellow, the rest gray.
Validated with the dataviz validator (--pairs all for the 3-group scatter). Aqua and yellow
sit below 3:1 on the surface, so those series always carry direct labels.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Literal

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.axes import Axes
from matplotlib.patches import FancyBboxPatch, Rectangle

SURFACE = "#fcfcfb"
GRID = "#e8e7e3"
TEXT = "#0b0b0b"
TEXT_2 = "#52514e"
MUTED = "#8a8984"
GRAY_MARK = "#b9b8b2"

BLUE, ORANGE, AQUA, YELLOW = "#2a78d6", "#eb6834", "#1baf7a", "#eda100"
ENTITY_COLORS = {"hybrid-jev": BLUE, "hybrid-qwen": ORANGE, "embedding": AQUA, "rerank": YELLOW}

plt.rcParams.update(
    {
        "font.family": "DejaVu Sans",
        "font.size": 10,
        "text.color": TEXT,
        "axes.labelcolor": TEXT_2,
        "xtick.color": TEXT_2,
        "ytick.color": TEXT_2,
        "axes.edgecolor": GRID,
        "axes.facecolor": SURFACE,
        "figure.facecolor": SURFACE,
        "savefig.facecolor": SURFACE,
    }
)


def _style(ax: Axes, *, grid_axis: Literal["both", "x", "y"] = "x") -> None:
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.spines["bottom"].set_linewidth(1)
    ax.grid(axis=grid_axis, color=GRID, linewidth=1, linestyle="-")
    ax.set_axisbelow(True)
    ax.tick_params(length=0)


def _rounded_hbar(
    ax: Axes, y: float, width: float, height: float, color: str, x0: float = 0.0
) -> None:
    """Horizontal bar: square at the baseline, rounded data end."""
    if width <= 0:
        return
    radius = min(height / 2, width) * 0.45
    ax.add_patch(
        FancyBboxPatch(
            (x0, y - height / 2),
            width,
            height,
            boxstyle=f"round,pad=0,rounding_size={radius}",
            linewidth=0,
            facecolor=color,
            mutation_aspect=1,
        )
    )
    ax.add_patch(
        Rectangle(
            (x0, y - height / 2), max(0.0, width - radius), height, linewidth=0, facecolor=color
        )
    )


def _entity_color(system: str, emphasis: Sequence[str]) -> str:
    base = system.split("@")[0].split("~")[0].split("#")[0]
    return ENTITY_COLORS.get(base, BLUE) if system in emphasis else GRAY_MARK


def bar_chart(
    rows: Sequence[tuple[str, float, float | None, float | None]],
    *,
    title: str,
    subtitle: str,
    out: Path,
    percent: bool = True,
    emphasis: Sequence[str] = ("hybrid-jev", "embedding"),
    xmax: float | None = None,
) -> Path:
    """rows: (label, value, ci_lo, ci_hi), drawn top to bottom in the given order."""
    fig_h = 1.2 + 0.34 * len(rows)
    fig, ax = plt.subplots(figsize=(7.6, fig_h), dpi=160)
    _style(ax)
    scale = 100.0 if percent else 1.0
    top = (
        xmax
        if xmax is not None
        else max((hi if hi is not None else v) for _, v, _, hi in rows) * scale * 1.12 or 1.0
    )
    for i, (label, value, lo, hi) in enumerate(rows):
        y = len(rows) - 1 - i
        _rounded_hbar(ax, y, value * scale, 0.4, _entity_color(label, emphasis))
        if lo is not None and hi is not None and hi > lo:
            ax.plot(
                [lo * scale, hi * scale],
                [y, y],
                color=TEXT_2,
                linewidth=1.2,
                solid_capstyle="round",
                zorder=3,
            )
        text = f"{value * scale:.1f}{'%' if percent else ''}" if percent else f"{value:,.0f}"
        ax.text(
            max(value, hi or 0) * scale + top * 0.012,
            y,
            text,
            va="center",
            ha="left",
            fontsize=9,
            color=TEXT,
        )
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels([r[0] for r in reversed(rows)])
    ax.set_ylim(-0.7, len(rows) - 0.3)
    ax.set_xlim(0, top)
    fig.suptitle(title, x=0.02, ha="left", fontsize=12, fontweight="bold", color=TEXT)
    ax.set_title(subtitle, loc="left", fontsize=9, color=TEXT_2, pad=8)
    fig.tight_layout()
    fig.savefig(out)
    plt.close(fig)
    return out


def line_chart(
    series: Mapping[str, Sequence[tuple[float, float]]],
    *,
    title: str,
    subtitle: str,
    xlabel: str,
    ylabel: str,
    out: Path,
    xscale: str = "linear",
    xticks: Sequence[float] | None = None,
    percent: bool = True,
) -> Path:
    fig, ax = plt.subplots(figsize=(7.6, 4.4), dpi=160)
    _style(ax, grid_axis="y")
    scale = 100.0 if percent else 1.0
    for name, points in series.items():
        color = ENTITY_COLORS.get(name, GRAY_MARK)
        xs = [p[0] for p in points]
        ys = [p[1] * scale for p in points]
        ax.plot(
            xs,
            ys,
            color=color,
            linewidth=2,
            solid_joinstyle="round",
            solid_capstyle="round",
            label=name,
            zorder=2,
        )
        ax.plot(
            xs,
            ys,
            "o",
            color=color,
            markersize=8,
            markeredgecolor=SURFACE,
            markeredgewidth=2,
            zorder=3,
        )
        ax.annotate(
            f"{name}  {ys[-1]:.0f}{'%' if percent else ''}",
            (xs[-1], ys[-1]),
            xytext=(8, 0),
            textcoords="offset points",
            va="center",
            fontsize=9,
            color=TEXT,
        )
    if xscale == "symlog":
        ax.set_xscale("symlog", linthresh=10)
    elif xscale == "log2":
        ax.set_xscale("log", base=2)
    if xticks is not None:
        ax.set_xticks(list(xticks))
        ax.set_xticklabels([f"{t:,.0f}" for t in xticks])
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    if percent:
        ax.set_ylim(0, 105)
    ax.legend(loc="lower left", frameon=False, fontsize=9, ncol=2)
    fig.suptitle(title, x=0.02, ha="left", fontsize=12, fontweight="bold", color=TEXT)
    ax.set_title(subtitle, loc="left", fontsize=9, color=TEXT_2, pad=8)
    fig.tight_layout()
    fig.subplots_adjust(right=0.8)
    fig.savefig(out)
    plt.close(fig)
    return out


def scatter_quality_latency(
    points: Sequence[tuple[str, float, float, str]], *, title: str, subtitle: str, out: Path
) -> Path:
    """points: (label, latency_ms, accuracy, group) with group in {jev, qwen, baseline}."""
    colors = {"jev": BLUE, "qwen": ORANGE, "baseline": AQUA}
    names = {"jev": "Jev-judged", "qwen": "Qwen-judged", "baseline": "similarity baselines"}
    fig, ax = plt.subplots(figsize=(7.6, 4.6), dpi=160)
    _style(ax, grid_axis="both")
    seen: set[str] = set()
    for _label, latency, acc, group in points:
        ax.plot(
            latency,
            acc * 100,
            "o",
            color=colors[group],
            markersize=9,
            markeredgecolor=SURFACE,
            markeredgewidth=2,
            label=names[group] if group not in seen else None,
            zorder=3,
        )
        seen.add(group)
    fig.canvas.draw()
    _place_labels(ax, [(label, latency, acc * 100) for label, latency, acc, _ in points])
    ax.set_xlabel("End-to-end latency per query (ms, modelled from recorded calls)")
    ax.set_ylabel("Answer accuracy (%)")
    ax.legend(loc="lower right", frameon=False, fontsize=9)
    fig.suptitle(title, x=0.02, ha="left", fontsize=12, fontweight="bold", color=TEXT)
    ax.set_title(subtitle, loc="left", fontsize=9, color=TEXT_2, pad=8)
    fig.tight_layout()
    fig.savefig(out)
    plt.close(fig)
    return out


def _place_labels(ax: Axes, labels: Sequence[tuple[str, float, float]]) -> None:
    """Greedy non-overlapping point labels: try a few offsets, fall back to a leader line."""
    placed: list[tuple[float, float, float, float]] = []
    offsets = [
        (7, 4, "left"),
        (7, -12, "left"),
        (-7, 4, "right"),
        (-7, -12, "right"),
        (7, 16, "left"),
        (7, -24, "left"),
    ]
    for text, x, y in sorted(labels, key=lambda item: -item[2]):
        px, py = ax.transData.transform((x, y))
        width, height = 6.2 * len(text) * 160 / 100, 11 * 160 / 72
        chosen = None
        for dx, dy, ha in offsets:
            ox, oy = px + dx * 160 / 72, py + dy * 160 / 72
            x0 = ox if ha == "left" else ox - width
            box = (x0, oy - 2, x0 + width, oy + height)
            if not any(
                b[0] < box[2] and box[0] < b[2] and b[1] < box[3] and box[1] < b[3] for b in placed
            ):
                chosen = (dx, dy, ha, box)
                break
        if chosen is None:
            dx, dy, ha = 10, -30 - 12 * len(placed) % 36, "left"
            chosen = (dx, dy, ha, (px, py, px, py))
            ax.annotate(
                text,
                (x, y),
                xytext=(dx, dy),
                textcoords="offset points",
                fontsize=8,
                color=TEXT_2,
                ha=ha,
                arrowprops={"arrowstyle": "-", "color": MUTED, "linewidth": 0.8},
            )
        else:
            ax.annotate(
                text,
                (x, y),
                xytext=(chosen[0], chosen[1]),
                textcoords="offset points",
                fontsize=8,
                color=TEXT_2,
                ha=chosen[2],
            )
        placed.append(chosen[3])


def reliability_chart(
    curves: Mapping[str, tuple[Sequence[float], Sequence[float], float | None]],
    *,
    title: str,
    subtitle: str,
    out: Path,
) -> Path:
    """curves: name -> (mean confidence per bin, accuracy per bin, ECE)."""
    fig, ax = plt.subplots(figsize=(5.6, 5.0), dpi=160)
    _style(ax, grid_axis="both")
    ax.plot([0, 1], [0, 1], color=MUTED, linewidth=1, zorder=1)
    ax.annotate("perfect calibration", (0.72, 0.68), fontsize=8, color=MUTED, rotation=38)
    palette = [BLUE, ORANGE]
    for (name, (conf, acc, ece)), color in zip(curves.items(), palette, strict=False):
        ax.plot(
            conf,
            acc,
            color=color,
            linewidth=2,
            zorder=2,
            label=f"{name} (ECE {ece:.3f})" if ece is not None else name,
        )
        ax.plot(
            conf,
            acc,
            "o",
            color=color,
            markersize=8,
            markeredgecolor=SURFACE,
            markeredgewidth=2,
            zorder=3,
        )
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_xlabel("Judged probability (bin mean)")
    ax.set_ylabel("Observed frequency (gold)")
    ax.legend(loc="upper left", frameon=False, fontsize=9)
    fig.suptitle(title, x=0.02, ha="left", fontsize=12, fontweight="bold", color=TEXT)
    ax.set_title(subtitle, loc="left", fontsize=9, color=TEXT_2, pad=8)
    fig.tight_layout()
    fig.savefig(out)
    plt.close(fig)
    return out
