"""Circulating kill methods: Driller's and Wait and Weight.

Both hold bottomhole pressure constant at the formation pressure and differ only
in when the mud is weighted up. They share the simulator in this module.

## What the simulator does

At every step it reconstructs the whole well:

* **String side** -- where the kill mud front has reached, and therefore what
  the drill pipe gauge should read to keep bottomhole pressure on target.
* **Annulus side** -- a four-zone fluid column, from the bottom up: kill mud
  that has come round the bit, original mud pumped behind it, the influx, and
  the original mud that was always above it.
* **The influx** -- its volume solved by Boyle's law against the pressure at its
  own depth, so it grows as it rises. Its position follows from the volume
  pumped beneath it.

Casing pressure then falls out of the column rather than being interpolated:
whatever hydrostatic the column does not supply must appear at surface. Shoe
pressure is read off the same column at the shoe depth.

## Approximations

**Annular friction while circulating is neglected.** At kill rates it is tens of
psi and the whole system friction is carried on the drill pipe side as the slow
circulating rate. This is the standard kill sheet convention.

**The influx is one continuous bubble.** Real influxes disperse, channel through
mud, and in oil-based mud dissolve entirely.

**Gas is ideal and isothermal.** Real gas cools as it expands. Ignoring that
slightly over-estimates expansion, which errs toward caution.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..units import PSI_PER_PPG_FT, psi_to_psia
from .base import (
    Applicability,
    FluidColumn,
    KillMethod,
    KillPlan,
    KillStage,
    TracePoint,
    WellState,
    Zone,
)


# --------------------------------------------------------------------------
# Simulator
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Snapshot:
    """The state of the well after a given volume has been pumped."""

    volume_pumped_bbl: float
    strokes: float
    drill_pipe_psi: float
    casing_psi: float
    shoe_psi: float | None
    influx_volume_bbl: float
    influx_top_md_ft: float | None
    influx_bottom_md_ft: float | None
    kill_mud_string_md_ft: float
    kill_mud_annulus_bbl: float
    column: FluidColumn


def _solve_influx_volume(
    well: WellState,
    initial_volume_bbl: float,
    reference_pressure_psia: float,
    influx_bottom_md: float,
    pressure_at_influx_bottom: float,
) -> tuple[float, float]:
    """Influx volume at its current depth, and the MD of its top.

    Boyle's law against the pressure the influx actually sits at, iterated
    because the volume sets the height, the height sets the average pressure,
    and the average pressure sets the volume.
    """
    gradient = well.influx_gradient_psi_per_ft
    annulus_volume = well.annulus.volume_bbl
    volume_below = well.annulus.volume_between(influx_bottom_md, well.hole_md_ft)

    volume = initial_volume_bbl
    top_md = influx_bottom_md
    for _ in range(6):
        # Cap so the influx cannot extend past surface; beyond that it is
        # venting and only what remains in the hole counts.
        capacity_above = annulus_volume - volume_below
        volume = min(volume, capacity_above)

        top_md = well.annulus_md_at_volume_from_bottom(volume_below + volume)
        vertical = well.survey.tvd_at(influx_bottom_md) - well.survey.tvd_at(top_md)
        average_pressure = pressure_at_influx_bottom - gradient * vertical / 2.0
        if average_pressure <= 1.0:
            break
        volume = initial_volume_bbl * reference_pressure_psia / psi_to_psia(
            average_pressure
        )

    capacity_above = annulus_volume - volume_below
    volume = max(0.0, min(volume, capacity_above))
    top_md = well.annulus_md_at_volume_from_bottom(volume_below + volume)
    return volume, top_md


def simulate_circulation(
    well: WellState,
    *,
    use_kill_mud: bool,
    influx_volume_bbl: float,
    total_volume_bbl: float,
    steps: int = 60,
) -> list[Snapshot]:
    """Simulate one circulation at constant bottomhole pressure.

    Args:
        well: The well and the kick.
        use_kill_mud: True when kill mud is being pumped (Wait and Weight, or
            the second circulation of Driller's). False when circulating with
            the original mud still in the pits.
        influx_volume_bbl: Influx in the annulus at the start. Zero for the
            second circulation of Driller's, where the influx is already out.
        total_volume_bbl: How much to pump.
        steps: Number of samples.

    Returns:
        One :class:`Snapshot` per step, from zero pumped to ``total_volume_bbl``.
    """
    formation_pressure = well.formation_pressure_psi
    original_mw = well.mud_weight_ppg
    kill_mw = well.kill_mud_weight_ppg if use_kill_mud else well.mud_weight_ppg
    string_volume = well.annulus.string.internal_volume_bbl
    annulus_volume = well.annulus.volume_bbl
    hole_md = well.hole_md_ft
    bit_tvd = well.bit_tvd_ft
    shoe_md = well.shoe_md
    scr = well.slow_circulating_rate.pressure_psi
    clf = well.effective_choke_line_friction
    gradient = well.influx_gradient_psi_per_ft

    # Reference gas pressure: the average through the influx while on bottom.
    initial_vertical = well.survey.vertical_height_of(
        well.annulus_md_at_volume_from_bottom(influx_volume_bbl), hole_md
    ) if influx_volume_bbl > 0 else 0.0
    reference_psia = psi_to_psia(
        formation_pressure - gradient * initial_vertical / 2.0
    )

    snapshots: list[Snapshot] = []

    for i in range(steps + 1):
        pumped = total_volume_bbl * i / steps

        # ---- string side ------------------------------------------------
        if use_kill_mud:
            string_fill = min(pumped, string_volume)
            kill_front_md = well.kill_sheet.kill_mud_depth_at_volume(string_fill)
            fraction = string_fill / string_volume if string_volume > 0 else 1.0
        else:
            kill_front_md = 0.0
            fraction = 0.0

        kill_front_tvd = well.survey.tvd_at(kill_front_md)
        string_hydrostatic = (
            PSI_PER_PPG_FT * kill_mw * kill_front_tvd
            + PSI_PER_PPG_FT * original_mw * (bit_tvd - kill_front_tvd)
        )
        friction = scr + (scr * kill_mw / original_mw - scr) * fraction
        drill_pipe = formation_pressure - string_hydrostatic + friction - clf

        # ---- annulus side -----------------------------------------------
        kill_in_annulus = max(0.0, pumped - string_volume) if use_kill_mud else 0.0
        kill_in_annulus = min(kill_in_annulus, annulus_volume)

        md_kill_top = well.annulus_md_at_volume_from_bottom(kill_in_annulus)
        md_influx_bottom = well.annulus_md_at_volume_from_bottom(min(pumped, annulus_volume))

        # Hydrostatic of everything below the influx, to find its pressure.
        hydrostatic_below = (
            PSI_PER_PPG_FT * kill_mw
            * (well.survey.tvd_at(hole_md) - well.survey.tvd_at(md_kill_top))
            + PSI_PER_PPG_FT * original_mw
            * (well.survey.tvd_at(md_kill_top) - well.survey.tvd_at(md_influx_bottom))
        )
        pressure_at_influx = formation_pressure - hydrostatic_below

        if influx_volume_bbl > 0 and pumped < annulus_volume:
            influx_volume, md_influx_top = _solve_influx_volume(
                well,
                influx_volume_bbl,
                reference_psia,
                md_influx_bottom,
                pressure_at_influx,
            )
        else:
            influx_volume = 0.0
            md_influx_top = md_influx_bottom

        zones: list[Zone] = []
        if kill_in_annulus > 0:
            zones.append(Zone(md_kill_top, hole_md, kill_mw, "kill mud"))
        if md_influx_bottom < md_kill_top:
            zones.append(
                Zone(md_influx_bottom, md_kill_top, original_mw, "mud behind influx")
            )
        if influx_volume > 0 and md_influx_top < md_influx_bottom:
            zones.append(
                Zone(md_influx_top, md_influx_bottom, well.influx_density_ppg, "influx")
            )
        if md_influx_top > 0:
            zones.append(Zone(0.0, md_influx_top, original_mw, "original mud"))

        column = FluidColumn(zones, well.survey)
        casing = column.surface_pressure_for_bottomhole(formation_pressure)
        shoe = column.pressure_at(shoe_md, casing) if shoe_md is not None else None

        snapshots.append(
            Snapshot(
                volume_pumped_bbl=pumped,
                strokes=well.pump.strokes_for(pumped),
                drill_pipe_psi=drill_pipe,
                casing_psi=max(0.0, casing),
                shoe_psi=shoe,
                influx_volume_bbl=influx_volume,
                influx_top_md_ft=md_influx_top if influx_volume > 0 else None,
                influx_bottom_md_ft=md_influx_bottom if influx_volume > 0 else None,
                kill_mud_string_md_ft=kill_front_md,
                kill_mud_annulus_bbl=kill_in_annulus,
                column=column,
            )
        )

    return snapshots


def _trace_from(snapshots: list[Snapshot], stage: str, x_offset: float = 0.0
                ) -> list[TracePoint]:
    return [
        TracePoint(
            x=s.strokes + x_offset,
            stage=stage,
            drill_pipe_psi=s.drill_pipe_psi,
            casing_psi=s.casing_psi,
            shoe_psi=s.shoe_psi,
            influx_volume_bbl=s.influx_volume_bbl,
            influx_top_md_ft=s.influx_top_md_ft,
            influx_bottom_md_ft=s.influx_bottom_md_ft,
        )
        for s in snapshots
    ]


def _common_summary(well: WellState) -> dict[str, object]:
    sheet = well.kill_sheet
    summary: dict[str, object] = {
        "Original mud weight (ppg)": round(well.mud_weight_ppg, 2),
        "Kill mud weight (ppg)": round(well.kill_mud_weight_ppg, 2),
        "Formation pressure (psi)": round(well.formation_pressure_psi),
        "Bit MD / TVD (ft)": f"{well.bit_md_ft:.0f} / {well.bit_tvd_ft:.0f}",
        "Influx density (ppg)": round(well.influx_density_ppg, 2),
        "SCR at kill rate (psi)": round(well.slow_circulating_rate.pressure_psi),
        "ICP (psi)": round(sheet.initial_circulating_pressure_psi),
        "FCP (psi)": round(sheet.final_circulating_pressure_psi),
        "String volume (bbl)": round(sheet.string_volume_bbl, 1),
        "Annulus volume (bbl)": round(sheet.annulus_volume_bbl, 1),
        "Strokes to bit": round(sheet.strokes_to_bit),
        "Strokes bit to surface": round(sheet.strokes_bit_to_surface),
    }
    if well.effective_choke_line_friction:
        summary["Choke line friction (psi)"] = round(
            well.effective_choke_line_friction
        )
    maasp = well.maasp_psi(well.kill_mud_weight_ppg)
    if maasp is not None:
        summary["MAASP at kill mud weight (psi)"] = round(maasp)
    return summary


def _shoe_verdict(well: WellState, plan: KillPlan) -> None:
    """Compare peak shoe pressure with the fracture limit and record it."""
    peak = plan.peak_shoe_pressure_psi
    limit = well.frac_pressure_psi
    if peak is None:
        return
    plan.summary["Peak shoe pressure (psi)"] = round(peak)
    if limit is None:
        return
    plan.summary["Shoe fracture pressure (psi)"] = round(limit)
    margin = limit - peak
    plan.summary["Margin at shoe (psi)"] = round(margin)
    if margin < 0:
        plan.applicability.block(
            f"Peak shoe pressure ({peak:.0f} psi) exceeds the fracture pressure "
            f"({limit:.0f} psi) by {-margin:.0f} psi. This kill as planned would "
            "break down the shoe and risk an underground blowout."
        )
    elif margin < 0.1 * limit:
        plan.applicability.warn(
            f"Peak shoe pressure ({peak:.0f} psi) comes within {margin:.0f} psi "
            f"of the fracture pressure ({limit:.0f} psi). Very little margin."
        )


# --------------------------------------------------------------------------
# Driller's Method
# --------------------------------------------------------------------------

class DrillersMethod(KillMethod):
    """Two circulations: remove the influx, then displace to kill mud."""

    key = "drillers"
    name = "Driller's Method"
    summary = (
        "Circulate the influx out with the mud already in the hole, then weight "
        "up and circulate again to displace to kill mud."
    )
    circulates = True

    def plan(self, well: WellState) -> KillPlan:
        sheet = well.kill_sheet
        icp = sheet.initial_circulating_pressure_psi
        fcp = sheet.final_circulating_pressure_psi
        annulus_volume = well.annulus.volume_bbl
        string_volume = well.annulus.string.internal_volume_bbl

        first = simulate_circulation(
            well,
            use_kill_mud=False,
            influx_volume_bbl=well.pit_gain_bbl,
            total_volume_bbl=annulus_volume,
        )
        second = simulate_circulation(
            well,
            use_kill_mud=True,
            influx_volume_bbl=0.0,
            total_volume_bbl=string_volume + annulus_volume,
        )

        offset = first[-1].strokes
        trace = _trace_from(first, "First circulation") + _trace_from(
            second, "Second circulation", x_offset=offset
        )

        summary = _common_summary(well)
        summary["Total strokes (both circulations)"] = round(trace[-1].x)

        stages = [
            KillStage(
                name="1. Bring the pump to kill rate",
                description=(
                    "Hold casing pressure constant with the choke while bringing "
                    f"the pump to {well.slow_circulating_rate.spm:.0f} spm."
                ),
                actions=[
                    "Open the choke and start the pump slowly.",
                    "Hold CASING pressure constant at "
                    f"{well.sicp_psi:.0f} psi throughout the ramp.",
                    f"Once at kill rate the drill pipe gauge should read "
                    f"{icp:.0f} psi (ICP).",
                    "If it does not, the slow circulating rate was wrong. Adjust "
                    "the whole schedule by the difference.",
                ],
            ),
            KillStage(
                name="2. First circulation - remove the influx",
                description=(
                    f"Circulate at kill rate with the original "
                    f"{well.mud_weight_ppg:.1f} ppg mud, holding drill pipe "
                    f"pressure constant at {icp:.0f} psi."
                ),
                strokes=sheet.strokes_bit_to_surface,
                actions=[
                    f"Hold DRILL PIPE pressure constant at {icp:.0f} psi.",
                    "Use the choke to keep it there. Ignore casing pressure.",
                    f"The influx reaches surface after "
                    f"{sheet.strokes_bit_to_surface:.0f} strokes.",
                    "Casing pressure will rise sharply as gas expands near "
                    "surface. That is expected -- keep the drill pipe gauge on "
                    "its number.",
                ],
                table=[
                    {
                        "Strokes": round(s.strokes),
                        "DP psi": round(s.drill_pipe_psi),
                        "Casing psi": round(s.casing_psi),
                        "Influx bbl": round(s.influx_volume_bbl, 1),
                        "Influx top MD": (
                            round(s.influx_top_md_ft)
                            if s.influx_top_md_ft is not None else "-"
                        ),
                    }
                    for s in first[::6]
                ],
            ),
            KillStage(
                name="3. Shut in and weight up",
                description=(
                    f"Raise the mud weight from {well.mud_weight_ppg:.1f} to "
                    f"{well.kill_mud_weight_ppg:.1f} ppg."
                ),
                actions=[
                    "Shut down and shut in.",
                    "SIDPP and SICP should now be equal -- the influx is gone, "
                    "so both sides read through the same mud.",
                    f"Weight the system up to {well.kill_mud_weight_ppg:.2f} ppg.",
                    "Watch for pressure rise while waiting.",
                ],
            ),
            KillStage(
                name="4. Second circulation - displace to kill mud",
                description=(
                    f"Follow the drill pipe schedule from {icp:.0f} psi down to "
                    f"{fcp:.0f} psi as kill mud goes to the bit, then hold FCP."
                ),
                strokes=sheet.strokes_to_bit + sheet.strokes_bit_to_surface,
                actions=[
                    f"Take drill pipe pressure down the schedule to {fcp:.0f} psi "
                    f"over {sheet.strokes_to_bit:.0f} strokes.",
                    f"Then hold {fcp:.0f} psi until kill mud returns at surface.",
                    "Casing pressure should fall to zero.",
                    "Shut down, shut in, and check for flow.",
                ],
                table=[
                    {
                        "Strokes": round(s.strokes),
                        "DP psi": round(s.drill_pipe_psi),
                        "Casing psi": round(s.casing_psi),
                        "Kill mud MD": round(s.kill_mud_string_md_ft),
                    }
                    for s in second[::6]
                ],
            ),
        ]

        plan = self._new_plan(
            well,
            summary=summary,
            stages=stages,
            trace=trace,
            x_label="Pump strokes (both circulations)",
            notes=[
                "Starts immediately -- no waiting for the mud system.",
                "The first circulation is a single instruction: hold one number "
                "on the drill pipe gauge. Least to get wrong under pressure.",
                "Costs roughly twice the pumping of Wait and Weight, and the "
                "annulus holds light mud for longer, so the shoe sees higher "
                "pressure for longer.",
            ]
            + well.configuration.considerations(),
        )
        _shoe_verdict(well, plan)
        return plan


# --------------------------------------------------------------------------
# Wait and Weight
# --------------------------------------------------------------------------

class WaitAndWeight(KillMethod):
    """One circulation: weight up first, then kill in a single pass."""

    key = "wait_and_weight"
    name = "Wait and Weight"
    summary = (
        "Weight the mud up with the well shut in, then kill it in one "
        "circulation. Also called the Engineer's Method."
    )
    circulates = True

    def applicability(self, well: WellState) -> Applicability:
        result = super().applicability(well)
        if well.configuration.trajectory.migration_reliable:
            result.warn(
                "The well sits shut in while the mud is weighted up. If gas is "
                "migrating, surface pressure will climb throughout that wait. "
                "Check the time to weight up against the migration rate."
            )
        return result

    def plan(self, well: WellState) -> KillPlan:
        sheet = well.kill_sheet
        icp = sheet.initial_circulating_pressure_psi
        fcp = sheet.final_circulating_pressure_psi
        string_volume = well.annulus.string.internal_volume_bbl
        annulus_volume = well.annulus.volume_bbl

        snapshots = simulate_circulation(
            well,
            use_kill_mud=True,
            influx_volume_bbl=well.pit_gain_bbl,
            total_volume_bbl=string_volume + annulus_volume,
        )
        trace = _trace_from(snapshots, "Single circulation")

        summary = _common_summary(well)
        summary["Total strokes"] = round(sheet.total_strokes)
        summary["Time at kill rate (min)"] = round(sheet.total_minutes())

        schedule = sheet.schedule_by_depth(steps=10)

        stages = [
            KillStage(
                name="1. Weight up",
                description=(
                    f"With the well shut in, raise the mud weight from "
                    f"{well.mud_weight_ppg:.1f} to {well.kill_mud_weight_ppg:.1f} ppg."
                ),
                actions=[
                    f"Mix to {well.kill_mud_weight_ppg:.2f} ppg.",
                    "Monitor SIDPP and SICP while waiting. A steady rise means "
                    "gas is migrating and the wait is costing margin.",
                    "Have the drill pipe pressure schedule written out before "
                    "starting the pump.",
                ],
            ),
            KillStage(
                name="2. Bring the pump to kill rate",
                description=(
                    "Hold casing pressure constant with the choke while bringing "
                    f"the pump to {well.slow_circulating_rate.spm:.0f} spm."
                ),
                actions=[
                    "Hold CASING pressure constant during the ramp.",
                    f"At kill rate the drill pipe gauge should read {icp:.0f} psi.",
                ],
            ),
            KillStage(
                name="3. Circulate kill mud to the bit",
                description=(
                    f"Follow the schedule down from {icp:.0f} psi to {fcp:.0f} psi "
                    f"over {sheet.strokes_to_bit:.0f} strokes."
                ),
                strokes=sheet.strokes_to_bit,
                actions=[
                    "Follow the DRILL PIPE schedule below. Use the choke to make "
                    "the gauge match.",
                    "Casing pressure will rise as gas expands. Ignore it.",
                ],
                table=[
                    {
                        "Strokes": round(step.strokes),
                        "Volume bbl": round(step.volume_bbl, 1),
                        "Kill mud MD": round(step.kill_mud_md_ft),
                        "DP psi": round(step.drill_pipe_pressure_psi),
                    }
                    for step in schedule
                ],
            ),
            KillStage(
                name="4. Circulate to surface",
                description=(
                    f"Hold drill pipe pressure at {fcp:.0f} psi until kill mud "
                    "returns at surface."
                ),
                strokes=sheet.strokes_bit_to_surface,
                actions=[
                    f"Hold {fcp:.0f} psi constant.",
                    f"The influx reaches surface at "
                    f"{sheet.strokes_bit_to_surface:.0f} strokes from the start "
                    "of pumping -- before the kill mud does.",
                    "Casing pressure should fall to zero as kill mud fills the "
                    "annulus.",
                    "Shut down, shut in, and check for flow.",
                ],
            ),
        ]

        notes = [
            "One circulation instead of two.",
            "The wait to weight up is the cost, and it is only free if gas is "
            "not migrating.",
        ]
        notes.append(self._shoe_advantage_note(well))

        plan = self._new_plan(
            well,
            summary=summary,
            stages=stages,
            trace=trace,
            x_label="Pump strokes",
            notes=notes + well.configuration.considerations(),
        )
        _shoe_verdict(well, plan)
        return plan

    @staticmethod
    def _shoe_advantage_note(well: WellState) -> str:
        """Whether this well actually gets the textbook shoe-pressure benefit.

        Wait and Weight is usually said to put less pressure on the shoe,
        because kill mud reaches the annulus and adds hydrostatic before the
        influx gets there. That is only true if the kill mud arrives first, and
        it does not always.

        Kill mud enters the annulus after one string volume has been pumped.
        The influx reaches the shoe after roughly the annular volume between
        the shoe and total depth has been pumped. Compare the two.
        """
        shoe = well.shoe_md
        if shoe is None:
            return (
                "No casing shoe defined, so the shoe-pressure comparison against "
                "the Driller's Method cannot be made."
            )

        string_volume = well.annulus.string.internal_volume_bbl
        shoe_to_td = well.annulus.volume_between(shoe, well.hole_md_ft)
        influx_at_shoe = max(0.0, shoe_to_td - well.pit_gain_bbl)

        if string_volume < influx_at_shoe:
            return (
                f"Kill mud reaches the annulus after {string_volume:.0f} bbl, and "
                f"the influx reaches the shoe after about {influx_at_shoe:.0f} bbl. "
                "The heavier mud gets there first, so this method does lower the "
                "peak pressure at the shoe compared with the Driller's Method."
            )
        return (
            f"On this well the influx reaches the shoe after about "
            f"{influx_at_shoe:.0f} bbl, but kill mud does not enter the annulus "
            f"until {string_volume:.0f} bbl have been pumped. The influx passes "
            "the shoe before any heavy mud gets there, so Wait and Weight gives "
            "NO shoe-pressure advantage here -- the peak at the shoe matches the "
            "Driller's Method. It still lowers peak CASING pressure, and it is "
            "still one circulation instead of two."
        )
