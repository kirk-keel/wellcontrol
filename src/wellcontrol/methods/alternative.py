"""Reverse circulation and bullheading.

Two methods that take the influx somewhere other than up the annulus.

**Reverse circulation** pumps down the annulus and takes returns up the drill
string. The influx goes into the bit and up the inside of the pipe. Because the
string holds far less volume than the annulus, the influx reaches surface much
sooner -- and, more importantly, it never passes the casing shoe.

**Bullheading** pumps the influx back into the formation it came from. Nothing
returns to surface at all. It is used when circulating is impossible or
unacceptable: a parted string, H2S at surface, or a well that simply cannot be
allowed to bring the influx up.

Neither is a first-choice method. Both are on the list because the situations
that call for them are exactly the situations where the standard methods have
already been ruled out.
"""

from __future__ import annotations

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
# Reverse circulation
# --------------------------------------------------------------------------

class ReverseCirculation(KillMethod):
    """Pump down the annulus, take returns up the drill string."""

    key = "reverse"
    name = "Reverse Circulation"
    summary = (
        "Pump down the annulus and return up the drill string. The influx comes "
        "up the inside of the pipe instead of past the casing shoe, and reaches "
        "surface far sooner because the string holds much less volume."
    )
    circulates = True

    def applicability(self, well: WellState) -> Applicability:
        result = super().applicability(well)

        result.warn(
            "A float valve in the string makes reverse circulation impossible -- "
            "it will not let fluid pass upward. Confirm the string is open, or "
            "that a ported/circulating sub is fitted, before planning on this."
        )
        result.warn(
            "The measured slow circulating rate was taken circulating forward. "
            "Friction in reverse is different -- the flow areas are swapped -- "
            "so the pressures here are estimates. Establish a reverse rate "
            "before relying on them."
        )
        result.warn(
            "Cuttings and solids flowing backward can plug the bit nozzles. If "
            "the bit plugs mid-kill there is no circulation path at all."
        )
        result.warn(
            "Gas expanding inside the small bore of the drill pipe reaches high "
            "velocities and pressures. Check the drill pipe pressure rating and "
            "the surface returns equipment."
        )

        string_volume = well.annulus.string.internal_volume_bbl
        if well.pit_gain_bbl > string_volume * 0.5:
            result.warn(
                f"The influx ({well.pit_gain_bbl:.0f} bbl) is large relative to "
                f"the string volume ({string_volume:.0f} bbl). It will occupy "
                "much of the string and expand violently near surface."
            )

        return result

    def plan(self, well: WellState) -> KillPlan:
        mud = well.mud_weight_ppg
        kill_mud = well.kill_mud_weight_ppg
        formation_pressure = well.formation_pressure_psi
        gradient = well.influx_gradient_psi_per_ft
        influx_density = well.influx_density_ppg
        string_volume = well.annulus.string.internal_volume_bbl
        annulus_volume = well.annulus.volume_bbl
        bit_md = well.bit_md_ft
        hole_md = well.hole_md_ft
        shoe_md = well.shoe_md
        scr = well.slow_circulating_rate.pressure_psi
        clf = well.effective_choke_line_friction

        reference_psia = psi_to_psia(
            formation_pressure - gradient * well.influx_height_tvd_ft / 2.0
        )

        trace: list[TracePoint] = []
        steps = 60
        total_volume = string_volume
        influx_out_strokes = None

        for i in range(steps + 1):
            pumped = total_volume * i / steps

            # --- string side: influx rising toward surface ---------------
            influx_bottom_md = well.string_md_at_volume_from_bit(pumped)
            volume_below_in_string = pumped

            influx_volume = well.pit_gain_bbl
            influx_top_md = influx_bottom_md
            for _ in range(6):
                capacity_above = string_volume - volume_below_in_string
                influx_volume = min(influx_volume, max(0.0, capacity_above))
                influx_top_md = well.string_md_at_volume_from_bit(
                    volume_below_in_string + influx_volume
                )
                zones = [
                    Zone(0.0, influx_top_md, mud, "mud above influx"),
                    Zone(influx_top_md, influx_bottom_md, influx_density, "influx"),
                    Zone(influx_bottom_md, bit_md, kill_mud, "mud behind influx"),
                ]
                column = FluidColumn(zones, well.survey)
                dp_surface = column.surface_pressure_for_bottomhole(formation_pressure)
                midpoint = (influx_top_md + influx_bottom_md) / 2.0
                gas_pressure = column.pressure_at(midpoint, dp_surface)
                if gas_pressure <= 1.0:
                    break
                influx_volume = (
                    well.pit_gain_bbl * reference_psia / psi_to_psia(gas_pressure)
                )

            zones = [
                Zone(0.0, influx_top_md, mud, "mud above influx"),
                Zone(influx_top_md, influx_bottom_md, influx_density, "influx"),
                Zone(influx_bottom_md, bit_md, kill_mud, "mud behind influx"),
            ]
            string_column = FluidColumn(zones, well.survey)
            dp_choke = max(
                0.0, string_column.surface_pressure_for_bottomhole(formation_pressure)
            )

            if influx_top_md <= 1.0 and influx_out_strokes is None:
                influx_out_strokes = well.pump.strokes_for(pumped)

            # --- annulus side: the pump side, staying full of mud --------
            kill_front_md = well.annulus_md_at_volume_from_surface(
                min(pumped, annulus_volume)
            )
            annulus_zones = [
                Zone(0.0, kill_front_md, kill_mud, "kill mud"),
                Zone(kill_front_md, hole_md, mud, "original mud"),
            ]
            annulus_column = FluidColumn(annulus_zones, well.survey)
            annulus_surface = (
                annulus_column.surface_pressure_for_bottomhole(formation_pressure)
                + scr
                - clf
            )
            shoe = (
                annulus_column.pressure_at(
                    shoe_md,
                    annulus_column.surface_pressure_for_bottomhole(formation_pressure),
                )
                if shoe_md is not None
                else None
            )

            trace.append(
                TracePoint(
                    x=well.pump.strokes_for(pumped),
                    stage="Reverse circulation",
                    drill_pipe_psi=dp_choke,
                    casing_psi=max(0.0, annulus_surface),
                    shoe_psi=shoe,
                    influx_volume_bbl=influx_volume,
                    influx_top_md_ft=influx_top_md,
                    influx_bottom_md_ft=influx_bottom_md,
                )
            )

        strokes_to_surface = well.pump.strokes_for(string_volume)
        forward_strokes = well.pump.strokes_for(annulus_volume)

        summary: dict[str, object] = {
            "Original mud weight (ppg)": round(mud, 2),
            "Kill mud weight (ppg)": round(kill_mud, 2),
            "Formation pressure (psi)": round(formation_pressure),
            "String volume (bbl)": round(string_volume, 1),
            "Annulus volume (bbl)": round(annulus_volume, 1),
            "Strokes for influx to surface (reverse)": round(
                influx_out_strokes or strokes_to_surface
            ),
            "Strokes if circulated forward": round(forward_strokes),
            "Strokes saved": round(forward_strokes - strokes_to_surface),
            "Starting drill pipe choke pressure (psi)": round(trace[0].drill_pipe_psi or 0),
            "Peak drill pipe choke pressure (psi)": round(
                max(p.drill_pipe_psi or 0 for p in trace)
            ),
            "Peak influx volume in string (bbl)": round(
                max(p.influx_volume_bbl or 0 for p in trace), 1
            ),
        }
        peak_shoe = max((p.shoe_psi for p in trace if p.shoe_psi is not None),
                        default=None)
        if peak_shoe is not None:
            summary["Peak shoe pressure (psi)"] = round(peak_shoe)
        if well.frac_pressure_psi is not None:
            summary["Shoe fracture pressure (psi)"] = round(well.frac_pressure_psi)

        stages = [
            KillStage(
                name="1. Confirm the string will flow backward",
                description="The single condition that decides whether this is possible.",
                actions=[
                    "Confirm there is no float valve, or that a circulating sub "
                    "is fitted and open.",
                    "Check the drill pipe pressure rating against the expected "
                    f"peak of {summary['Peak drill pipe choke pressure (psi)']} psi.",
                    "Line up the returns from the drill pipe to the choke "
                    "manifold and the separator.",
                ],
            ),
            KillStage(
                name="2. Establish a reverse circulating rate",
                description=(
                    "Friction in reverse differs from forward. Establish the rate "
                    "before starting the kill if at all possible."
                ),
                actions=[
                    "Bring the pump up slowly, pumping into the ANNULUS.",
                    "Hold bottomhole pressure constant using the drill pipe choke.",
                    "Record the reverse circulating pressure at kill rate.",
                ],
            ),
            KillStage(
                name="3. Circulate the influx up the string",
                description=(
                    f"The influx reaches surface after about "
                    f"{influx_out_strokes or strokes_to_surface:.0f} strokes -- "
                    f"against {forward_strokes:.0f} strokes circulating forward."
                ),
                strokes=influx_out_strokes or strokes_to_surface,
                actions=[
                    "Pump kill mud down the ANNULUS at kill rate.",
                    "Control bottomhole pressure with the choke on the DRILL PIPE "
                    "returns.",
                    "The influx expands rapidly in the small bore of the pipe. "
                    "Expect the choke to be busy near the end.",
                    "The casing shoe never sees the influx -- shoe pressure stays "
                    "close to its static value throughout.",
                ],
                table=[
                    {
                        "Strokes": round(p.x),
                        "DP choke psi": round(p.drill_pipe_psi or 0),
                        "Annulus psi": round(p.casing_psi or 0),
                        "Influx bbl": round(p.influx_volume_bbl or 0, 1),
                        "Influx top MD": round(p.influx_top_md_ft or 0),
                    }
                    for p in trace[::6]
                ],
            ),
            KillStage(
                name="4. Displace to kill mud and check",
                description="Complete the displacement and confirm the well is dead.",
                actions=[
                    f"Continue until the annulus is displaced to "
                    f"{kill_mud:.2f} ppg.",
                    "Shut down, shut in, and check for flow.",
                    "Consider a conventional circulation afterwards to confirm "
                    "the whole system is at kill weight.",
                ],
            ),
        ]

        notes = [
            "The strongest argument for this method: the influx never passes the "
            "casing shoe. On a well with marginal kick tolerance that can be "
            "decisive.",
            f"Much faster -- about {forward_strokes - strokes_to_surface:.0f} "
            "fewer strokes to get the influx to surface.",
            "Against it: a float in the string rules it out entirely, the bit "
            "can plug, and the drill pipe becomes a pressure vessel handling "
            "expanding gas in a small bore.",
            "Not part of many operators' standard procedures. Check the well "
            "control manual before planning on it.",
        ] + well.configuration.considerations()

        return self._new_plan(
            well,
            summary=summary,
            stages=stages,
            trace=trace,
            x_label="Pump strokes",
            notes=notes,
        )


# --------------------------------------------------------------------------
# Bullheading
# --------------------------------------------------------------------------

class Bullhead(KillMethod):
    """Pump the influx back into the formation it came from."""

    key = "bullhead"
    name = "Bullheading"
    summary = (
        "Pump the influx back into the formation. Nothing returns to surface. "
        "Used when circulating is impossible or unacceptable."
    )
    circulates = False

    #: Pressure above formation pressure needed to inject, psi.
    injection_margin_psi: float = 200.0

    def applicability(self, well: WellState) -> Applicability:
        result = super().applicability(well)

        result.warn(
            "The formation must accept fluid. A tight or damaged zone will not "
            "take the influx, and the pressure simply builds until something "
            "else breaks -- usually the shoe."
        )
        result.warn(
            "There are no returns, so there is no way to confirm what is "
            "happening downhole. Success is inferred from the pressure "
            "behaviour alone."
        )
        result.warn(
            "Gas can channel upward past the mud being pumped down rather than "
            "being pushed back. The heavier the mud and the slower the rate, the "
            "worse this gets."
        )

        if well.shoe_tvd_ft is not None and well.hole_tvd_ft > 0:
            if well.shoe_tvd_ft < well.hole_tvd_ft * 0.85:
                result.warn(
                    "The shoe is well above the kicking formation. Bullheading "
                    "raises pressure on the whole open hole, and the shoe is "
                    "usually the weakest point -- it may break down before the "
                    "kicking formation accepts fluid."
                )

        return result

    def plan(self, well: WellState) -> KillPlan:
        mud = well.mud_weight_ppg
        kill_mud = well.kill_mud_weight_ppg
        formation_pressure = well.formation_pressure_psi
        target_bhp = formation_pressure + self.injection_margin_psi
        influx_density = well.influx_density_ppg
        hole_md = well.hole_md_ft
        shoe_md = well.shoe_md
        annulus_volume = well.annulus.volume_bbl

        trace: list[TracePoint] = []
        steps = 60
        for i in range(steps + 1):
            pumped = annulus_volume * i / steps
            kill_front_md = well.annulus_md_at_volume_from_surface(pumped)

            influx_remaining = max(0.0, well.pit_gain_bbl - pumped)
            if influx_remaining > 0:
                influx_top_md = well.annulus_md_at_volume_from_bottom(influx_remaining)
            else:
                influx_top_md = hole_md

            zones = [Zone(0.0, kill_front_md, kill_mud, "kill mud")]
            if influx_top_md > kill_front_md:
                zones.append(
                    Zone(kill_front_md, influx_top_md, mud, "original mud")
                )
            if influx_remaining > 0 and hole_md > influx_top_md:
                zones.append(
                    Zone(influx_top_md, hole_md, influx_density, "influx")
                )

            column = FluidColumn(zones, well.survey)
            surface = column.surface_pressure_for_bottomhole(target_bhp)
            shoe = column.pressure_at(shoe_md, surface) if shoe_md is not None else None

            trace.append(
                TracePoint(
                    x=pumped,
                    stage="Bullheading",
                    drill_pipe_psi=None,
                    casing_psi=max(0.0, surface),
                    shoe_psi=shoe,
                    influx_volume_bbl=influx_remaining,
                    influx_top_md_ft=influx_top_md if influx_remaining > 0 else None,
                    influx_bottom_md_ft=hole_md if influx_remaining > 0 else None,
                )
            )

        starting_pressure = trace[0].casing_psi or 0.0
        peak_shoe = max((p.shoe_psi for p in trace if p.shoe_psi is not None),
                        default=None)

        summary: dict[str, object] = {
            "Kill mud weight (ppg)": round(kill_mud, 2),
            "Formation pressure (psi)": round(formation_pressure),
            "Injection margin (psi)": round(self.injection_margin_psi),
            "Target bottomhole pressure (psi)": round(target_bhp),
            "Starting surface pressure (psi)": round(starting_pressure),
            "Final surface pressure (psi)": round(trace[-1].casing_psi or 0),
            "Volume to pump (bbl)": round(annulus_volume, 1),
            "Strokes to pump": round(well.pump.strokes_for(annulus_volume)),
        }
        if peak_shoe is not None:
            summary["Peak shoe pressure (psi)"] = round(peak_shoe)
        if well.frac_pressure_psi is not None:
            summary["Shoe fracture pressure (psi)"] = round(well.frac_pressure_psi)
            summary["Margin at shoe (psi)"] = round(
                well.frac_pressure_psi - (peak_shoe or 0)
            )

        plan = self._new_plan(
            well,
            summary=summary,
            stages=[],
            trace=trace,
            x_label="Volume pumped (bbl)",
            notes=[
                "Bullheading is hardest at the start. The influx is light, so the "
                "column supplies the least hydrostatic and surface pressure is "
                "highest -- and so is the pressure on the shoe.",
                "As kill mud fills the annulus, hydrostatic rises and the "
                "required surface pressure falls. If pressure is NOT falling as "
                "you pump, the formation is not taking fluid.",
                "No returns means no verification. Watch the pressure trend, "
                "because it is the only signal available.",
                "Typically reserved for H2S at surface, a parted or plugged "
                "string, or a well that must not be allowed to bring the influx "
                "up.",
            ]
            + well.configuration.considerations(),
        )

        # The critical feasibility check.
        if peak_shoe is not None and well.frac_pressure_psi is not None:
            if peak_shoe > well.frac_pressure_psi:
                plan.applicability.block(
                    f"Bullheading would put {peak_shoe:.0f} psi on the shoe "
                    f"against a fracture pressure of {well.frac_pressure_psi:.0f} "
                    f"psi -- {peak_shoe - well.frac_pressure_psi:.0f} psi over. "
                    "The shoe would break down before the influx went away, "
                    "turning a contained kick into an underground blowout."
                )

        plan.stages = [
            KillStage(
                name="1. Check feasibility before pumping",
                description=(
                    "The shoe is usually the weak point. This check decides "
                    "whether the method is possible at all."
                ),
                actions=[
                    f"Surface pressure needed at the start: "
                    f"{starting_pressure:.0f} psi.",
                    f"That puts {peak_shoe:.0f} psi on the shoe."
                    if peak_shoe is not None
                    else "Shoe pressure cannot be checked without a shoe depth.",
                    f"Shoe fracture pressure: {well.frac_pressure_psi:.0f} psi."
                    if well.frac_pressure_psi is not None
                    else "No fracture gradient supplied -- this check cannot be made.",
                    "Also check casing burst, wellhead rating and surface "
                    "equipment against the starting pressure.",
                ],
            ),
            KillStage(
                name="2. Line up and start pumping",
                description=(
                    f"Pump {kill_mud:.2f} ppg mud down with the well closed in."
                ),
                strokes=well.pump.strokes_for(annulus_volume),
                actions=[
                    "Close the well in with no returns path.",
                    "Start pumping at a rate high enough to outrun gas slipping "
                    "back up past the mud.",
                    f"Expect to start near {starting_pressure:.0f} psi.",
                    "Do not exceed the limiting pressure identified in step 1.",
                ],
                table=[
                    {
                        "Volume bbl": round(p.x, 1),
                        "Surface psi": round(p.casing_psi or 0),
                        "Shoe psi": round(p.shoe_psi) if p.shoe_psi else "-",
                        "Influx left bbl": round(p.influx_volume_bbl or 0, 1),
                    }
                    for p in trace[::6]
                ],
            ),
            KillStage(
                name="3. Watch the pressure trend",
                description="The only diagnostic available.",
                actions=[
                    "Surface pressure should FALL steadily as heavier mud "
                    "replaces the influx.",
                    "Flat or rising pressure means the formation is not taking "
                    "fluid. Stop before something breaks.",
                    f"Expect to finish near "
                    f"{trace[-1].casing_psi or 0:.0f} psi.",
                ],
            ),
            KillStage(
                name="4. Confirm",
                description="Verify the well is dead.",
                actions=[
                    "Bleed down and watch for pressure build-up.",
                    "If a circulation path exists afterwards, circulate bottoms "
                    "up to confirm and to condition the mud.",
                ],
            ),
        ]

        return plan
