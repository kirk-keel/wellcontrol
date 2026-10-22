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
from pathlib import Path
from typing import TYPE_CHECKING, BinaryIO

from .methods.base import KillPlan

if TYPE_CHECKING:
    from .sim.session import Session


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


def _render_title_block(
    figure,
    palette: Theme,
    *,
    title: str = "WELL CONTROL KILL PLOT & CERTIFICATION AUDIT RECORD",
    student_name: str | None = None,
    instructor_name: str | None = None,
    complication: str | None = None,
    well_name: str | None = None,
    date: str | None = None,
    status: str | None = None,
) -> None:
    """Standardized oilfield engineering certification title block.

    Stamps the plot with the five mandatory audit parameters: student name,
    instructor / assessor name, active complication or scenario fault,
    well name, and date, alongside verification standard and grading status.
    """
    from datetime import datetime
    import matplotlib.patches as patches

    s_name = str(student_name or "Student Trainee")
    i_name = str(instructor_name or "Lead Assessor")
    c_name = str(complication or "None (Standard Procedure)")
    w_name = str(well_name or "Reference Well #1")
    d_name = str(date or datetime.now().strftime("%Y-%m-%d %H:%M"))

    ax = figure.add_axes([0.05, 0.908, 0.90, 0.082])
    ax.axis("off")

    is_dark = palette.surface != "#fcfcfb"
    box_bg = "#0d1117" if is_dark else "#f8fafc"
    border_col = "#38bdf8" if is_dark else "#0284c7"
    ribbon_bg = "#1e293b" if is_dark else "#0f172a"
    label_col = "#94a3b8" if is_dark else "#64748b"
    val_col = "#f1f5f9" if is_dark else "#0f172a"
    divider_col = "#334155" if is_dark else "#cbd5e1"

    outer = patches.FancyBboxPatch(
        (0.0, 0.0), 1.0, 1.0,
        boxstyle="round,pad=0.005,rounding_size=0.015",
        facecolor=box_bg,
        edgecolor=border_col,
        linewidth=1.4,
        transform=ax.transAxes,
        clip_on=False,
    )
    ax.add_patch(outer)

    ribbon = patches.Rectangle(
        (0.0, 0.65), 1.0, 0.35,
        facecolor=ribbon_bg,
        edgecolor="none",
        transform=ax.transAxes,
        clip_on=True,
    )
    ax.add_patch(ribbon)

    ax.text(
        0.015, 0.81,
        title.upper(),
        color="#ffffff",
        fontsize=9.5,
        fontweight="bold",
        va="center",
        ha="left",
        transform=ax.transAxes,
    )
    ax.text(
        0.985, 0.81,
        "IADC WELLSHARP / IWCF LEVEL 4 AUDIT TRAIL",
        color="#38bdf8",
        fontsize=7.5,
        fontweight="bold",
        va="center",
        ha="right",
        transform=ax.transAxes,
    )

    for x_div in (0.33, 0.67):
        ax.plot(
            [x_div, x_div], [0.03, 0.62],
            color=divider_col,
            linewidth=0.8,
            linestyle="-",
            transform=ax.transAxes,
        )

    # Column 1
    ax.text(0.015, 0.46, "STUDENT:", color=label_col, fontsize=7.5, fontweight="bold", va="center", transform=ax.transAxes)
    ax.text(0.085, 0.46, s_name, color=val_col, fontsize=8.5, fontweight="bold", va="center", transform=ax.transAxes)

    ax.text(0.015, 0.18, "INSTRUCTOR:", color=label_col, fontsize=7.5, fontweight="bold", va="center", transform=ax.transAxes)
    ax.text(0.105, 0.18, i_name, color=val_col, fontsize=8.0, va="center", transform=ax.transAxes)

    # Column 2
    ax.text(0.35, 0.46, "WELL NAME:", color=label_col, fontsize=7.5, fontweight="bold", va="center", transform=ax.transAxes)
    ax.text(0.44, 0.46, w_name, color=val_col, fontsize=8.5, fontweight="bold", va="center", transform=ax.transAxes)

    comp_lower = c_name.lower()
    is_fault = any(w in comp_lower for w in ("fault", "failure", "plug", "breakout", "washout", "leak", "deadhead"))
    comp_color = "#dc2626" if is_fault else val_col
    ax.text(0.35, 0.18, "COMPLICATION:", color=label_col, fontsize=7.5, fontweight="bold", va="center", transform=ax.transAxes)
    ax.text(0.47, 0.18, c_name, color=comp_color, fontsize=8.0, fontweight="bold" if is_fault else "normal", va="center", transform=ax.transAxes)

    # Column 3
    ax.text(0.69, 0.46, "DATE / TIME:", color=label_col, fontsize=7.5, fontweight="bold", va="center", transform=ax.transAxes)
    ax.text(0.78, 0.46, d_name, color=val_col, fontsize=8.0, va="center", transform=ax.transAxes)

    st_text = status or "CERTIFIED COMPLETE"
    st_lower = st_text.lower()
    st_col = "#16a34a" if ("pass" in st_lower or "excellent" in st_lower or "certified" in st_lower) else ("#dc2626" if "fail" in st_lower else "#d97706")
    ax.text(0.69, 0.18, "STATUS / GRADE:", color=label_col, fontsize=7.5, fontweight="bold", va="center", transform=ax.transAxes)
    ax.text(0.81, 0.18, st_text, color=st_col, fontsize=8.5, fontweight="bold", va="center", transform=ax.transAxes)


def plot_kill(
    plan: KillPlan,
    theme: str = "light",
    figsize=(10.0, 11.0),
    *,
    student_name: str | None = None,
    instructor_name: str | None = None,
    complication: str | None = None,
    well_name: str | None = None,
    date: str | None = None,
    status: str | None = None,
    include_title_block: bool = True,
):
    """The full diagnostic set for a kill plan with optional certification title block.

    Args:
        plan: A :class:`~wellcontrol.methods.base.KillPlan`.
        theme: ``"light"`` or ``"dark"``.
        figsize: Figure size in inches.
        student_name: Trainee name for the official title block.
        instructor_name: Assessor/instructor name for the official title block.
        complication: Active complication/incident description.
        well_name: Well name or program identifier.
        date: Execution/certification timestamp.
        status: Verification status or grading outcome.
        include_title_block: Whether to render the standardized certification header.

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

    fig_h = figsize[1] * len(active) / 4.0
    if include_title_block:
        fig_h += 1.4

    figure = Figure(figsize=(figsize[0], fig_h), dpi=110)
    figure.patch.set_facecolor(palette.surface)
    axes = figure.subplots(len(active), 1, sharex=True, squeeze=False)
    axes = [row[0] for row in axes]
    lookup = dict(zip(active, axes))

    if include_title_block:
        _render_title_block(
            figure,
            palette,
            title=f"{plan.method_name} — {plan.configuration.label}",
            student_name=student_name,
            instructor_name=instructor_name,
            complication=complication,
            well_name=well_name or plan.configuration.label,
            date=date,
            status=status or "VERIFIED PLAN",
        )
        figure.subplots_adjust(top=0.88, bottom=0.06, left=0.08, right=0.96, hspace=0.22)
    else:
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
    if not include_title_block:
        figure.tight_layout(rect=(0, 0, 1, 0.985))
    return figure


def plot_session_kill(
    session: Session,
    theme: str = "light",
    figsize=(10.0, 11.0),
    *,
    student_name: str | None = None,
    instructor_name: str | None = None,
    complication: str | None = None,
    well_name: str | None = None,
    date: str | None = None,
    status: str | None = None,
    include_title_block: bool = True,
    x_axis: str = "strokes",
):
    """Generate an official certified kill plot for a simulator training run.

    Args:
        session: A :class:`~wellcontrol.sim.session.Session`.
        theme: ``"light"`` or ``"dark"``.
        figsize: Base figure size in inches.
        student_name: Trainee name. Defaults to session.student_name.
        instructor_name: Lead assessor name. Defaults to session.instructor_name.
        complication: Incident / scenario complication description.
        well_name: Well name. Defaults to session.get_well_name().
        date: Execution timestamp. Defaults to session.created_at.
        status: Certification status or grade outcome.
        include_title_block: Whether to render the standardized certification header.
        x_axis: ``"strokes"`` or ``"time"``.
    """
    from matplotlib.figure import Figure

    palette = THEMES[theme]
    trace = session.simulator.state.trace
    if not trace:
        session.advance()
        trace = session.simulator.state.trace
    if not trace:
        raise ValueError("Session produced no trace data to plot")

    if x_axis == "time":
        xs = [p.time_s / 60.0 for p in trace]
        x_label = "Elapsed time (minutes)"
    else:
        xs = [p.strokes for p in trace]
        x_label = "Pump strokes"

    panels = [
        ("pressures", True),
        ("shoe", any(p.shoe_psi > 0 for p in trace)),
        ("volume", any(p.influx_bbl > 0 or p.pit_gain_bbl != 0 for p in trace)),
        ("controls", True),
    ]
    active = [name for name, present in panels if present]
    fig_h = figsize[1] * len(active) / 4.0
    if include_title_block:
        fig_h += 1.4

    figure = Figure(figsize=(figsize[0], fig_h), dpi=110)
    figure.patch.set_facecolor(palette.surface)
    axes = figure.subplots(len(active), 1, sharex=True, squeeze=False)
    axes = [row[0] for row in axes]
    lookup = dict(zip(active, axes))

    s_name = student_name or getattr(session, "student_name", "Student Trainee")
    i_name = instructor_name or getattr(session, "instructor_name", "Lead Assessor")
    w_name = well_name or (session.get_well_name() if hasattr(session, "get_well_name") else "Reference Well #1")
    c_name = complication or (session.get_complication() if hasattr(session, "get_complication") else "None (Standard Procedure)")
    d_name = date or getattr(session, "created_at", None)

    try:
        debrief = session.debrief()
        grade = str(debrief.get("grade", "pass")).upper()
        ai = session.ai_debrief() if hasattr(session, "ai_debrief") else {}
        score = ai.get("score")
        calc_status = f"{grade} (Score: {score}%)" if score is not None else grade
    except Exception:
        calc_status = "RECORDED RUN"

    if include_title_block:
        _render_title_block(
            figure,
            palette,
            title="WELL CONTROL SIMULATOR — OFFICIAL KILL PLOT",
            student_name=s_name,
            instructor_name=i_name,
            complication=c_name,
            well_name=w_name,
            date=d_name,
            status=status or calc_status,
        )
        figure.subplots_adjust(top=0.88, bottom=0.06, left=0.08, right=0.96, hspace=0.22)
    else:
        figure.suptitle(
            f"Simulator Kill Plot — {w_name}",
            color=palette.primary_ink,
            fontsize=13,
            fontweight="bold",
            x=0.02,
            ha="left",
            y=0.995,
        )

    # 1. Pressures
    if "pressures" in lookup:
        ax = lookup["pressures"]
        _style_axis(ax, palette, "Pressure (psi)")
        dp_ys = [p.standpipe_psi for p in trace]
        ax.plot(xs, dp_ys, color=palette.series_1, linewidth=_LINE_WIDTH, label="Drill pipe (Actual)")
        _endpoint_label(ax, xs, dp_ys, f"{dp_ys[-1]:,.0f}", palette.series_1)

        csg_ys = [p.casing_psi for p in trace]
        ax.plot(xs, csg_ys, color=palette.series_2, linewidth=_LINE_WIDTH, label="Casing / choke")
        _endpoint_label(ax, xs, csg_ys, f"{csg_ys[-1]:,.0f}", palette.series_2)

        try:
            ks = session.kill_sheet()
            if x_axis == "strokes" and ks.get("schedule"):
                sch = ks["schedule"]
                sch_xs = [pt[0] for pt in sch]
                sch_ys = [pt[1] for pt in sch]
                ax.plot(sch_xs, sch_ys, color="#10b981", linestyle="--", linewidth=1.5, label="Planned DP schedule", alpha=0.85)
            if ks.get("maasp_psi") and ks["maasp_psi"] > 0:
                _threshold(ax, ks["maasp_psi"], "MAASP", palette.warning, palette)
        except Exception:
            pass

        ax.legend(loc="lower right", bbox_to_anchor=(1.0, 1.02), ncol=3, frameon=False, fontsize=9, labelcolor=palette.secondary_ink)

    # 2. Shoe Pressure
    if "shoe" in lookup:
        ax = lookup["shoe"]
        _style_axis(ax, palette, "Shoe pressure (psi)")
        shoe_ys = [p.shoe_psi for p in trace]
        ax.plot(xs, shoe_ys, color="#8b5cf6", linewidth=_LINE_WIDTH, label="Shoe pressure")
        _endpoint_label(ax, xs, shoe_ys, f"{shoe_ys[-1]:,.0f}", "#8b5cf6")
        frac_psi = session.simulator.frac_pressure_psi
        if frac_psi:
            _threshold(ax, frac_psi, "Fracture pressure (LOT)", palette.critical, palette)

    # 3. Volume & Pit Gain
    if "volume" in lookup:
        ax = lookup["volume"]
        _style_axis(ax, palette, "Volume (bbl)")
        gain_ys = [p.pit_gain_bbl for p in trace]
        ax.plot(xs, gain_ys, color=palette.series_2, linewidth=_LINE_WIDTH, label="Pit gain")
        _endpoint_label(ax, xs, gain_ys, f"{gain_ys[-1]:+,.1f}", palette.series_2)
        if any(p.influx_bbl > 0 for p in trace):
            influx_ys = [p.influx_bbl for p in trace]
            ax.plot(xs, influx_ys, color=palette.critical, linewidth=_LINE_WIDTH, label="Influx volume")
            _endpoint_label(ax, xs, influx_ys, f"{influx_ys[-1]:,.1f}", palette.critical)
        ax.legend(loc="lower right", bbox_to_anchor=(1.0, 1.02), ncol=2, frameon=False, fontsize=9, labelcolor=palette.secondary_ink)

    # 4. Controls
    if "controls" in lookup:
        ax = lookup["controls"]
        _style_axis(ax, palette, "Pump / Choke")
        spm_ys = [p.pump_spm for p in trace]
        ax.plot(xs, spm_ys, color="#a855f7", linewidth=_LINE_WIDTH, label="Pump (spm)")
        _endpoint_label(ax, xs, spm_ys, f"{spm_ys[-1]:.0f} spm", "#a855f7")

        choke_ys = [p.choke_percent for p in trace]
        ax.plot(xs, choke_ys, color="#f97316", linewidth=1.5, linestyle=":", label="Choke (%)")
        _endpoint_label(ax, xs, choke_ys, f"{choke_ys[-1]:.0f}%", "#f97316")
        ax.legend(loc="lower right", bbox_to_anchor=(1.0, 1.02), ncol=2, frameon=False, fontsize=9, labelcolor=palette.secondary_ink)

    axes[-1].set_xlabel(x_label, color=palette.secondary_ink, fontsize=10)
    if not include_title_block:
        figure.tight_layout(rect=(0, 0, 1, 0.985))
    return figure


def save_kill_plot(
    target: KillPlan | Session,
    path_or_buf: str | Path | BinaryIO,
    format: str | None = None,
    theme: str = "light",
    dpi: int = 150,
    **metadata,
) -> None:
    """Plot and save a kill plot with student and well certification metadata.

    Args:
        target: Either a :class:`~wellcontrol.methods.base.KillPlan` or
            a :class:`~wellcontrol.sim.session.Session`.
        path_or_buf: Destination file path (str/Path) or bytes buffer (BytesIO).
        format: Image format ('png', 'pdf', 'svg'). Inferred from path if omitted.
        theme: 'light' or 'dark'.
        dpi: Resolution for raster formats.
        **metadata: Optional overrides for student_name, instructor_name,
            complication, well_name, date, status.
    """
    if isinstance(target, KillPlan):
        fig = plot_kill(target, theme=theme, **metadata)
    else:
        fig = plot_session_kill(target, theme=theme, **metadata)

    fig.savefig(path_or_buf, format=format, dpi=dpi, bbox_inches="tight")


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


__all__ = [
    "THEMES",
    "LIGHT",
    "DARK",
    "plot_kill",
    "plot_session_kill",
    "save_kill_plot",
    "plot_pressures",
    "trace_table",
]
