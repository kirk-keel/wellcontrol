"""Kill plots: the diagnostic set for a kill in progress.

Four stacked panels sharing one x-axis:

1. **Circulating pressures** -- drill pipe and casing against progress. The
   classic kill sheet graph.
2. **Pressure at the casing shoe** -- against the fracture pressure. This is the
   panel that says whether the kill is survivable, and it is the one a paper
   kill sheet does not give you.
3. **Influx volume** -- gas expanding as it rises.
4. **Influx position** -- depth of the top and bottom of the influx, with the
   shoe marked, so you can see exactly when the gas passes the weak point.

## Why four panels and not two axes

Influx volume (bbl) and influx depth (ft) are different quantities on different
scales. Putting them on twin y-axes would invent a visual correlation that is
not in the data -- the alignment of the two scales would be arbitrary. Each
quantity gets its own panel and its own single axis. The shared x-axis is what
ties them together, and it is the honest way to do it.

## Colors

Categorical slots 1-3 of the reference palette (blue, orange, aqua), which are
documented as validated all-pairs in both light and dark modes. Thresholds use
the reserved status colors and are always directly labeled, so a limit is never
carried by color alone.
"""

from __future__ import annotations

from dataclasses import dataclass

from .methods.base import KillPlan


@dataclass(frozen=True)
class Theme:
    """Colors for one rendering mode."""

    surface: str
    primary_ink: str
    secondary_ink: str
    muted: str
    gridline: str
    baseline: str
    series_1: str
    series_2: str
    series_3: str
    critical: str
    warning: str


LIGHT = Theme(
    surface="#fcfcfb",
    primary_ink="#0b0b0b",
    secondary_ink="#52514e",
    muted="#898781",
    gridline="#e1e0d9",
    baseline="#c3c2b7",
    series_1="#2a78d6",
    series_2="#eb6834",
    series_3="#1baf7a",
    critical="#d03b3b",
    warning="#fab219",
)

DARK = Theme(
    surface="#1a1a19",
    primary_ink="#ffffff",
    secondary_ink="#c3c2b7",
    muted="#898781",
    gridline="#2c2c2a",
    baseline="#383835",
    series_1="#3987e5",
    series_2="#d95926",
    series_3="#199e70",
    critical="#d03b3b",
    warning="#fab219",
)

THEMES = {"light": LIGHT, "dark": DARK}

_LINE_WIDTH = 2.0
_HAIRLINE = 0.8


def _style_axis(ax, theme: Theme, ylabel: str) -> None:
    """Recessive chrome: hairline solid grid, no top/right spines."""
    ax.set_facecolor(theme.surface)
    ax.grid(True, which="major", color=theme.gridline, linewidth=_HAIRLINE,
            linestyle="-")
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(theme.baseline)
        ax.spines[side].set_linewidth(_HAIRLINE)
    ax.tick_params(colors=theme.muted, labelsize=9, length=0)
    ax.set_ylabel(ylabel, color=theme.secondary_ink, fontsize=10)


def _threshold(ax, value: float, label: str, color: str, theme: Theme) -> None:
    """A limit line. Dashed to separate it from data, and always labeled."""
    ax.axhline(value, color=color, linewidth=1.6, linestyle="--", zorder=1)
    ax.annotate(
        f"{label}  {value:,.0f} psi",
        xy=(0.995, value),
        xycoords=("axes fraction", "data"),
        ha="right",
        va="bottom",
        fontsize=9,
        color=color,
        annotation_clip=False,
    )


def _endpoint_label(ax, xs, ys, text: str, color: str) -> None:
    """Direct-label the last point of a series, rather than every point."""
    if not xs or not ys:
        return
    ax.annotate(
        text,
        xy=(xs[-1], ys[-1]),
        xytext=(6, 0),
        textcoords="offset points",
        ha="left",
        va="center",
        fontsize=9,
        color=color,
        annotation_clip=False,
    )


def _peak_label(ax, xs, peak_x: float, peak_y: float, text: str, color: str) -> None:
    """Label a peak, nudged inward when it sits against an edge."""
    span = max(xs) - min(xs) if len(xs) > 1 else 1.0
    position = (peak_x - min(xs)) / span if span else 0.0
    if position < 0.15:
        align, offset = "left", (4, 10)
    elif position > 0.85:
        align, offset = "right", (-4, 10)
    else:
        align, offset = "center", (0, 10)
    ax.annotate(
        text,
        xy=(peak_x, peak_y),
        xytext=offset,
        textcoords="offset points",
        ha=align,
        fontsize=9,
        color=color,
    )


def plot_kill(plan: KillPlan, theme: str = "light", figsize=(10.0, 11.0)):
    """The full diagnostic set for a kill plan.

    Args:
        plan: A :class:`~wellcontrol.methods.base.KillPlan`.
        theme: ``"light"`` or ``"dark"``.
        figsize: Figure size in inches.

    Returns:
        A matplotlib ``Figure``. Panels with no data are omitted, so a method
        that produces no drill pipe pressure gets three panels rather than an
        empty one.
    """
    from matplotlib.figure import Figure

    palette = THEMES[theme]
    trace = plan.trace
    if not trace:
        raise ValueError(f"{plan.method_name} produced no trace to plot")

    xs = [p.x for p in trace]
    has_dp = any(p.drill_pipe_psi is not None for p in trace)
    has_casing = any(p.casing_psi is not None for p in trace)
    has_shoe = any(p.shoe_psi is not None for p in trace)
    has_volume = any(p.influx_volume_bbl for p in trace)
    has_depth = any(p.influx_top_md_ft is not None for p in trace)
    has_pipe = any(p.pipe_depth_md_ft is not None for p in trace)

    panels = [
        ("pressures", has_dp or has_casing),
        ("shoe", has_shoe),
        ("volume", has_volume),
        ("depth", has_depth),
        ("pipe", has_pipe),
    ]
    active = [name for name, present in panels if present]
    if not active:
        raise ValueError(f"{plan.method_name} produced nothing plottable")

    figure = Figure(figsize=(figsize[0], figsize[1] * len(active) / 4.0), dpi=110)
    figure.patch.set_facecolor(palette.surface)
    axes = figure.subplots(len(active), 1, sharex=True, squeeze=False)
    axes = [row[0] for row in axes]
    lookup = dict(zip(active, axes))

    figure.suptitle(
        f"{plan.method_name}  —  {plan.configuration.label}",
        color=palette.primary_ink,
        fontsize=13,
        fontweight="bold",
        x=0.02,
        ha="left",
        y=0.995,
    )

    # -- 1. circulating pressures ----------------------------------------
    if "pressures" in lookup:
        ax = lookup["pressures"]
        _style_axis(ax, palette, "Pressure (psi)")
        labelled = 0
        if has_dp:
            ys = [p.drill_pipe_psi for p in trace]
            pairs = [(x, y) for x, y in zip(xs, ys) if y is not None]
            ax.plot([p[0] for p in pairs], [p[1] for p in pairs],
                    color=palette.series_1, linewidth=_LINE_WIDTH,
                    label="Drill pipe")
            _endpoint_label(ax, [p[0] for p in pairs], [p[1] for p in pairs],
                            f"{pairs[-1][1]:,.0f}", palette.series_1)
            labelled += 1
        if has_casing:
            ys = [p.casing_psi for p in trace]
            pairs = [(x, y) for x, y in zip(xs, ys) if y is not None]
            ax.plot([p[0] for p in pairs], [p[1] for p in pairs],
                    color=palette.series_2, linewidth=_LINE_WIDTH,
                    label="Casing / choke")
            _endpoint_label(ax, [p[0] for p in pairs], [p[1] for p in pairs],
                            f"{pairs[-1][1]:,.0f}", palette.series_2)
            labelled += 1
        if plan.maasp_psi is not None and plan.maasp_psi > 0:
            _threshold(ax, plan.maasp_psi, "MAASP", palette.warning, palette)
        if labelled >= 2:
            # Outside the axes, so it can never collide with the data or with
            # the threshold labels that sit at the right-hand edge.
            ax.legend(
                loc="lower right",
                bbox_to_anchor=(1.0, 1.02),
                ncol=2,
                frameon=False,
                fontsize=9,
                labelcolor=palette.secondary_ink,
                handlelength=1.6,
                columnspacing=1.4,
            )
        # Methods that do not circulate have no drill pipe reading, so calling
        # the panel "circulating pressures" would be wrong.
        title = "Circulating pressures" if has_dp else "Surface pressure"
        ax.set_title(title, color=palette.secondary_ink,
                     fontsize=10, loc="left", pad=6)

    # -- 2. shoe pressure -------------------------------------------------
    if "shoe" in lookup:
        ax = lookup["shoe"]
        _style_axis(ax, palette, "Pressure (psi)")
        pairs = [(p.x, p.shoe_psi) for p in trace if p.shoe_psi is not None]
        ax.plot([p[0] for p in pairs], [p[1] for p in pairs],
                color=palette.series_3, linewidth=_LINE_WIDTH)
        peak = max(p[1] for p in pairs)
        peak_x = next(p[0] for p in pairs if p[1] == peak)
        ax.plot([peak_x], [peak], marker="o", markersize=8,
                color=palette.series_3, markeredgecolor=palette.surface,
                markeredgewidth=2, zorder=4)
        _peak_label(ax, [p[0] for p in pairs], peak_x, peak,
                    f"peak {peak:,.0f} psi", palette.series_3)
        if plan.shoe_frac_pressure_psi is not None:
            _threshold(ax, plan.shoe_frac_pressure_psi, "Fracture",
                       palette.critical, palette)
        ax.set_title("Pressure at the casing shoe", color=palette.secondary_ink,
                     fontsize=10, loc="left", pad=6)

    # -- 3. influx volume -------------------------------------------------
    if "volume" in lookup:
        ax = lookup["volume"]
        _style_axis(ax, palette, "Volume (bbl)")
        pairs = [(p.x, p.influx_volume_bbl or 0.0) for p in trace]
        ax.plot([p[0] for p in pairs], [p[1] for p in pairs],
                color=palette.series_1, linewidth=_LINE_WIDTH)
        ax.fill_between([p[0] for p in pairs], 0, [p[1] for p in pairs],
                        color=palette.series_1, alpha=0.12, linewidth=0)
        peak = max(p[1] for p in pairs)
        peak_x = next(p[0] for p in pairs if p[1] == peak)
        _peak_label(ax, [p[0] for p in pairs], peak_x, peak,
                    f"peak {peak:,.1f} bbl", palette.series_1)
        ax.set_title("Influx volume downhole", color=palette.secondary_ink,
                     fontsize=10, loc="left", pad=6)

    # -- 4. influx position ------------------------------------------------
    if "depth" in lookup:
        ax = lookup["depth"]
        _style_axis(ax, palette, "Depth (ft MD)")
        tops = [(p.x, p.influx_top_md_ft) for p in trace
                if p.influx_top_md_ft is not None]
        bottoms = [(p.x, p.influx_bottom_md_ft) for p in trace
                   if p.influx_bottom_md_ft is not None]
        if tops and bottoms and len(tops) == len(bottoms):
            ax.fill_between(
                [p[0] for p in tops],
                [p[1] for p in tops],
                [p[1] for p in bottoms],
                color=palette.series_1, alpha=0.25, linewidth=0,
                label="Influx extent",
            )
        if tops:
            ax.plot([p[0] for p in tops], [p[1] for p in tops],
                    color=palette.series_1, linewidth=_LINE_WIDTH)
            _endpoint_label(ax, [p[0] for p in tops], [p[1] for p in tops],
                            "top", palette.series_1)
        shoe_md = plan.shoe_md_ft
        if shoe_md is not None:
            ax.axhline(shoe_md, color=palette.critical, linewidth=1.6,
                       linestyle="--", zorder=1)
            ax.annotate(
                f"Casing shoe  {shoe_md:,.0f} ft",
                xy=(0.995, shoe_md), xycoords=("axes fraction", "data"),
                ha="right", va="bottom", fontsize=9, color=palette.critical,
                annotation_clip=False,
            )
        ax.invert_yaxis()
        ax.set_title("Influx position (surface at top)",
                     color=palette.secondary_ink, fontsize=10, loc="left", pad=6)

    # -- 5. pipe position (stripping) --------------------------------------
    if "pipe" in lookup:
        ax = lookup["pipe"]
        _style_axis(ax, palette, "Bit depth (ft MD)")
        pairs = [(p.x, p.pipe_depth_md_ft) for p in trace
                 if p.pipe_depth_md_ft is not None]
        ax.plot([p[0] for p in pairs], [p[1] for p in pairs],
                color=palette.series_2, linewidth=_LINE_WIDTH)
        _endpoint_label(ax, [p[0] for p in pairs], [p[1] for p in pairs],
                        f"{pairs[-1][1]:,.0f} ft", palette.series_2)
        shoe_md = plan.shoe_md_ft
        if shoe_md is not None:
            ax.axhline(shoe_md, color=palette.critical, linewidth=1.6,
                       linestyle="--", zorder=1)
            ax.annotate(
                f"Casing shoe  {shoe_md:,.0f} ft",
                xy=(0.995, shoe_md), xycoords=("axes fraction", "data"),
                ha="right", va="bottom", fontsize=9, color=palette.critical,
                annotation_clip=False,
            )
        ax.invert_yaxis()
        ax.set_title("Bit depth while stripping (surface at top)",
                     color=palette.secondary_ink, fontsize=10, loc="left", pad=6)

    axes[-1].set_xlabel(plan.x_label, color=palette.secondary_ink, fontsize=10)
    figure.tight_layout(rect=(0, 0, 1, 0.985))
    return figure


def plot_pressures(plan: KillPlan, theme: str = "light", figsize=(10.0, 4.0)):
    """Just the circulating pressure panel -- the classic kill sheet graph."""
    from matplotlib.figure import Figure

    palette = THEMES[theme]
    figure = Figure(figsize=figsize, dpi=110)
    figure.patch.set_facecolor(palette.surface)
    ax = figure.subplots()
    _style_axis(ax, palette, "Pressure (psi)")

    xs = [p.x for p in plan.trace]
    series = 0
    for attribute, color, label in (
        ("drill_pipe_psi", palette.series_1, "Drill pipe"),
        ("casing_psi", palette.series_2, "Casing / choke"),
    ):
        pairs = [
            (x, getattr(p, attribute))
            for x, p in zip(xs, plan.trace)
            if getattr(p, attribute) is not None
        ]
        if not pairs:
            continue
        ax.plot([p[0] for p in pairs], [p[1] for p in pairs],
                color=color, linewidth=_LINE_WIDTH, label=label)
        series += 1

    if plan.maasp_psi is not None and plan.maasp_psi > 0:
        _threshold(ax, plan.maasp_psi, "MAASP", palette.warning, palette)
    if series >= 2:
        ax.legend(loc="upper right", frameon=False, fontsize=9,
                  labelcolor=palette.secondary_ink)

    ax.set_xlabel(plan.x_label, color=palette.secondary_ink, fontsize=10)
    ax.set_title(f"{plan.method_name} — circulating pressures",
                 color=palette.primary_ink, fontsize=12, loc="left",
                 fontweight="bold", pad=10)
    figure.tight_layout()
    return figure


def trace_table(plan: KillPlan, every: int = 5) -> list[dict[str, object]]:
    """The trace as a table -- the accessible twin of the plots.

    Every value on the charts is reachable here without relying on color.
    """
    rows: list[dict[str, object]] = []
    for index, point in enumerate(plan.trace):
        if index % every and index != len(plan.trace) - 1:
            continue
        row: dict[str, object] = {plan.x_label: round(point.x, 1)}
        if point.drill_pipe_psi is not None:
            row["Drill pipe (psi)"] = round(point.drill_pipe_psi)
        if point.casing_psi is not None:
            row["Casing (psi)"] = round(point.casing_psi)
        if point.shoe_psi is not None:
            row["Shoe (psi)"] = round(point.shoe_psi)
        if point.influx_volume_bbl is not None:
            row["Influx (bbl)"] = round(point.influx_volume_bbl, 1)
        if point.influx_top_md_ft is not None:
            row["Influx top (ft MD)"] = round(point.influx_top_md_ft)
        rows.append(row)
    return rows
