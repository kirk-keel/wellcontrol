"""Volumetric and Lube-and-Bleed: controlling a well you cannot circulate.

Both methods exist for the situation where the drill string cannot be used --
off bottom, plugged, washed out, or out of the hole entirely. There is no drill
pipe gauge to follow and no way to pump mud round, so bottomhole pressure has to
be managed from surface using pressure and volume alone.

**Neither method kills the well.** The Volumetric Method holds bottomhole
pressure roughly constant while gas migrates to surface. Lube and Bleed then
replaces that gas with mud once it arrives. Together they can return a well to a
state where it is full of mud and dead, but the usual role is to hold the
situation while a route to circulation is restored -- typically by stripping
pipe back to bottom.

**Both depend entirely on gas migrating upward.** Gas rises because it is
buoyant, and buoyancy needs a vertical direction to act in. An influx lying in a
horizontal lateral will not move on its own, and neither method can start.
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
# Volumetric Method
# --------------------------------------------------------------------------

class VolumetricMethod(KillMethod):
    """Let migrating gas expand by bleeding measured volumes of mud."""

    key = "volumetric"
    name = "Volumetric Method"
    summary = (
        "Hold bottomhole pressure roughly constant while gas migrates, by "
        "bleeding measured volumes of mud to let it expand. Used when the well "
        "cannot be circulated."
    )
    circulates = False
    requires_migration = True

    #: Overbalance built in before any bleeding starts, psi.
    safety_margin_psi: float = 100.0
    #: Pressure the well is allowed to swing through on each cycle, psi.
    working_margin_psi: float = 100.0

    def applicability(self, well: WellState) -> Applicability:
        result = super().applicability(well)

        if well.influx_height_tvd_ft < 1.0:
            result.block(
                "The influx has no vertical height -- it is lying in a "
                "horizontal or near-horizontal section. Gas will not migrate, "
                "so there is nothing for this method to track and no pressure "
                "rise to bleed against. The influx must first be moved into a "
                "section with inclination before the Volumetric Method can do "
                "anything."
            )

        if well.pit_gain_bbl <= 0:
            result.block("No influx volume recorded, so there is nothing to track.")

        return result

    def plan(self, well: WellState) -> KillPlan:
        mud = well.mud_weight_ppg
        formation_pressure = well.formation_pressure_psi
        target_bhp = formation_pressure + self.safety_margin_psi
        gradient = well.influx_gradient_psi_per_ft
        influx_density = well.influx_density_ppg
        hole_md = well.hole_md_ft
        shoe_md = well.shoe_md
        annulus_volume = well.annulus.volume_bbl

        # Annular capacity near surface -- this is where mud is bled from.
        surface_capacity = well.annulus.capacity_at(10.0)

        # Bleed volume per cycle: the volume whose hydrostatic equals the
        # working margin.
        bleed_per_cycle = (
            self.working_margin_psi * surface_capacity / (PSI_PER_PPG_FT * mud)
        )

        # -- simulate the gas rising -------------------------------------
        initial_top = well.influx_top_md_ft
        initial_volume = well.pit_gain_bbl
        reference_psia = psi_to_psia(
            formation_pressure - gradient * well.influx_height_tvd_ft / 2.0
        )

        trace: list[TracePoint] = []
        steps = 60
        peak_casing = 0.0
        total_bleed = 0.0

        for i in range(steps + 1):
            gas_top_md = initial_top * (1.0 - i / steps)
            volume_above_gas = well.annulus.volume_between(0.0, gas_top_md)

            volume = initial_volume
            gas_bottom_md = hole_md
            for _ in range(6):
                capacity_below = annulus_volume - volume_above_gas
                volume = min(volume, capacity_below)
                gas_bottom_md = well.annulus_md_at_volume_from_surface(
                    volume_above_gas + volume
                )
                zones = [
                    Zone(0.0, gas_top_md, mud, "mud above gas"),
                    Zone(gas_top_md, gas_bottom_md, influx_density, "gas"),
                    Zone(gas_bottom_md, hole_md, mud, "mud below gas"),
                ]
                column = FluidColumn(zones, well.survey)
                casing = column.surface_pressure_for_bottomhole(target_bhp)
                midpoint = (gas_top_md + gas_bottom_md) / 2.0
                gas_pressure = column.pressure_at(midpoint, casing)
                if gas_pressure <= 1.0:
                    break
                volume = initial_volume * reference_psia / psi_to_psia(gas_pressure)

            zones = [
                Zone(0.0, gas_top_md, mud, "mud above gas"),
                Zone(gas_top_md, gas_bottom_md, influx_density, "gas"),
                Zone(gas_bottom_md, hole_md, mud, "mud below gas"),
            ]
            column = FluidColumn(zones, well.survey)
            casing = max(0.0, column.surface_pressure_for_bottomhole(target_bhp))
            shoe = column.pressure_at(shoe_md, casing) if shoe_md is not None else None
            total_bleed = max(0.0, volume - initial_volume)
            peak_casing = max(peak_casing, casing)

            trace.append(
                TracePoint(
                    x=total_bleed,
                    stage="Gas migrating",
                    drill_pipe_psi=None,
                    casing_psi=casing,
                    shoe_psi=shoe,
                    influx_volume_bbl=volume,
                    influx_top_md_ft=gas_top_md,
                    influx_bottom_md_ft=gas_bottom_md,
                )
            )

        cycles = max(1, round(total_bleed / bleed_per_cycle)) if bleed_per_cycle else 0

        summary: dict[str, object] = {
            "Mud weight (ppg)": round(mud, 2),
            "Formation pressure (psi)": round(formation_pressure),
            "Safety margin (psi)": round(self.safety_margin_psi),
            "Working margin per cycle (psi)": round(self.working_margin_psi),
            "Target bottomhole pressure (psi)": round(target_bhp),
            "Initial SICP (psi)": round(well.sicp_psi),
            "Annular capacity at surface (bbl/ft)": round(surface_capacity, 5),
            "Bleed volume per cycle (bbl)": round(bleed_per_cycle, 2),
            "Total mud to bleed (bbl)": round(total_bleed, 1),
            "Approximate cycles to surface": cycles,
            "Peak casing pressure (psi)": round(peak_casing),
            "Gas volume at surface (bbl)": round(trace[-1].influx_volume_bbl or 0.0, 1),
        }
        maasp = well.maasp_psi()
        if maasp is not None:
            summary["MAASP (psi)"] = round(maasp)
            if peak_casing > maasp:
                summary["MAASP exceeded by (psi)"] = round(peak_casing - maasp)

        stages = [
            KillStage(
                name="1. Build the safety margin",
                description=(
                    f"Let casing pressure rise {self.safety_margin_psi:.0f} psi "
                    "above the shut-in value without bleeding anything."
                ),
                actions=[
                    f"Record the starting SICP: {well.sicp_psi:.0f} psi.",
                    f"Allow it to rise to "
                    f"{well.sicp_psi + self.safety_margin_psi:.0f} psi as gas "
                    "migrates. Do not bleed.",
                    "This builds the overbalance that the rest of the operation "
                    "works against.",
                ],
            ),
            KillStage(
                name="2. Let the working margin build",
                description=(
                    f"Allow a further {self.working_margin_psi:.0f} psi of rise."
                ),
                actions=[
                    f"Allow casing pressure to rise a further "
                    f"{self.working_margin_psi:.0f} psi, to "
                    f"{well.sicp_psi + self.safety_margin_psi + self.working_margin_psi:.0f} psi.",
                    "Still do not bleed. The rise is the gas telling you it has "
                    "moved up.",
                ],
            ),
            KillStage(
                name="3. Bleed mud, not gas",
                description=(
                    f"Bleed {bleed_per_cycle:.1f} bbl of mud to bring pressure "
                    f"back down by {self.working_margin_psi:.0f} psi."
                ),
                actions=[
                    f"Bleed {bleed_per_cycle:.2f} bbl of MUD through the choke.",
                    "Measure it into a calibrated trip tank. This is a volume "
                    "operation -- the volume is the control, not the pressure.",
                    f"Casing pressure falls back to "
                    f"{well.sicp_psi + self.safety_margin_psi:.0f} psi.",
                    "Bleeding GAS instead of mud would lose the overbalance and "
                    "let the well take another influx.",
                ],
                table=[
                    {
                        "Cycle": n,
                        "Bleed this cycle (bbl)": round(bleed_per_cycle, 2),
                        "Cumulative bled (bbl)": round(bleed_per_cycle * n, 1),
                    }
                    for n in range(1, min(cycles, 15) + 1)
                ],
            ),
            KillStage(
                name="4. Repeat until gas reaches surface",
                description=(
                    f"About {cycles} cycles, bleeding roughly "
                    f"{total_bleed:.0f} bbl in total."
                ),
                actions=[
                    "Repeat steps 2 and 3 for each cycle.",
                    "Casing pressure climbs steadily overall as gas replaces mud "
                    f"higher in the hole -- expect a peak near "
                    f"{peak_casing:.0f} psi.",
                    "Watch that peak against MAASP. If the trend will exceed it, "
                    "this method alone will not get the gas to surface safely.",
                    "Once gas is at surface, switch to Lube and Bleed to replace "
                    "it with mud.",
                ],
            ),
        ]

        notes = [
            "This method does not kill the well. It holds bottomhole pressure "
            "roughly constant while the gas relocates itself to surface.",
            "Bleed MUD, never gas, while the gas is still downhole. Bleeding gas "
            "removes the expansion you are trying to accommodate.",
            "Volume is the control variable. An accurately measured trip tank "
            "matters more than the pressure gauge here.",
            "The usual purpose is to buy time and margin while a route back to "
            "circulation is restored, most often by stripping pipe to bottom.",
        ] + well.configuration.considerations()

        plan = self._new_plan(
            well,
            summary=summary,
            stages=stages,
            trace=trace,
            x_label="Cumulative mud bled (bbl)",
            notes=notes,
        )

        # Casing pressure climbs the whole way as gas replaces mud higher in
        # the hole. On a well with a weak shoe it can run past MAASP long
        # before the gas reaches surface, and this method has no way to stop
        # that -- the gas is going up whether or not the shoe can take it.
        if maasp is not None and peak_casing > maasp:
            plan.applicability.warn(
                f"Casing pressure is projected to peak at {peak_casing:.0f} psi, "
                f"which is {peak_casing - maasp:.0f} psi above MAASP "
                f"({maasp:.0f} psi). The Volumetric Method cannot prevent this "
                "-- the gas rises regardless. Plan to regain circulation, or to "
                "accept the shoe exposure, before the pressure gets there."
            )
        if well.frac_pressure_psi is not None:
            peak_shoe = max(
                (p.shoe_psi for p in trace if p.shoe_psi is not None), default=None
            )
            if peak_shoe is not None:
                plan.summary["Peak shoe pressure (psi)"] = round(peak_shoe)
                if peak_shoe > well.frac_pressure_psi:
                    plan.applicability.block(
                        f"Shoe pressure reaches {peak_shoe:.0f} psi against a "
                        f"fracture pressure of {well.frac_pressure_psi:.0f} psi. "
                        "Letting the gas migrate up under this method would "
                        "break down the shoe."
                    )

        return plan


# --------------------------------------------------------------------------
# Lube and Bleed
# --------------------------------------------------------------------------

class LubeAndBleed(KillMethod):
    """Replace gas at surface with mud, one measured slug at a time."""

    key = "lube_and_bleed"
    name = "Lube and Bleed"
    summary = (
        "With gas at surface and no way to circulate, pump measured volumes of "
        "mud in, let them fall through the gas, then bleed gas off. Repeat "
        "until the well is full of mud and dead."
    )
    circulates = False
    requires_migration = True
    requires_gas_at_surface = True

    #: Mud volume lubricated in per cycle, bbl.
    lube_volume_bbl: float = 5.0

    def applicability(self, well: WellState) -> Applicability:
        result = super().applicability(well)

        result.warn(
            "This method assumes the gas has already reached surface -- "
            "normally after the Volumetric Method, or after migration in a "
            "shut-in well. If the influx is still downhole, it is not yet "
            "applicable."
        )

        if well.influx_height_tvd_ft < 1.0:
            result.block(
                "The influx has no vertical height and cannot migrate to "
                "surface on its own, so gas will not arrive at the stack for "
                "this method to work on."
            )

        result.warn(
            "Mud must fall through the gas under gravity between pumping and "
            "bleeding. Allow real waiting time -- typically 15-30 minutes per "
            "cycle. Bleeding before the mud has fallen simply vents the mud "
            "back out."
        )

        return result

    def plan(self, well: WellState) -> KillPlan:
        mud = well.mud_weight_ppg
        kill_mud = well.kill_mud_weight_ppg
        formation_pressure = well.formation_pressure_psi
        sicp = well.sicp_psi
        shoe_md = well.shoe_md
        surface_capacity = well.annulus.capacity_at(10.0)

        # Estimate the gas volume now sitting at surface, by expanding the
        # original influx from formation pressure down to the surface pressure.
        gas_volume = well.pit_gain_bbl * psi_to_psia(formation_pressure) / psi_to_psia(
            sicp
        )
        gas_volume = min(gas_volume, well.annulus.volume_bbl * 0.95)

        # Each cycle removes the hydrostatic of the mud lubricated in.
        pressure_drop_per_cycle = (
            PSI_PER_PPG_FT * kill_mud * (self.lube_volume_bbl / surface_capacity)
        )
        cycles = max(1, int(sicp / pressure_drop_per_cycle) + 1) if (
            pressure_drop_per_cycle > 0
        ) else 0

        # Pressure rise when pumping into a closed gas cap, by Boyle.
        if gas_volume > self.lube_volume_bbl:
            pump_in_pressure = (
                psi_to_psia(sicp) * gas_volume / (gas_volume - self.lube_volume_bbl)
                - 14.7
            )
        else:
            pump_in_pressure = float("inf")

        trace: list[TracePoint] = []
        pressure = sicp
        pumped = 0.0
        for cycle in range(cycles + 1):
            gas_top = 0.0
            gas_bottom = well.annulus_md_at_volume_from_surface(max(gas_volume, 0.0))
            zones = [
                Zone(gas_top, gas_bottom, well.influx_density_ppg, "gas cap"),
                Zone(gas_bottom, well.hole_md_ft, mud, "mud"),
            ]
            column = FluidColumn(zones, well.survey)
            shoe = (
                column.pressure_at(shoe_md, pressure) if shoe_md is not None else None
            )
            trace.append(
                TracePoint(
                    x=pumped,
                    stage="Lube and bleed",
                    drill_pipe_psi=None,
                    casing_psi=max(0.0, pressure),
                    shoe_psi=shoe,
                    influx_volume_bbl=max(0.0, gas_volume),
                    influx_top_md_ft=0.0,
                    influx_bottom_md_ft=gas_bottom,
                    note=f"cycle {cycle}",
                )
            )
            pressure -= pressure_drop_per_cycle
            pumped += self.lube_volume_bbl
            gas_volume = max(0.0, gas_volume - self.lube_volume_bbl)
            if pressure <= 0:
                break

        summary: dict[str, object] = {
            "Mud weight for lubrication (ppg)": round(kill_mud, 2),
            "Starting surface pressure (psi)": round(sicp),
            "Estimated gas volume at surface (bbl)": round(
                well.pit_gain_bbl
                * psi_to_psia(formation_pressure)
                / psi_to_psia(sicp),
                1,
            ),
            "Lube volume per cycle (bbl)": round(self.lube_volume_bbl, 1),
            "Pressure drop per cycle (psi)": round(pressure_drop_per_cycle),
            "Pressure rise on pumping in (psi)": (
                round(pump_in_pressure) if pump_in_pressure != float("inf") else "n/a"
            ),
            "Cycles to zero surface pressure": cycles,
            "Total mud to lubricate (bbl)": round(cycles * self.lube_volume_bbl, 1),
        }
        maasp = well.maasp_psi()
        if maasp is not None:
            summary["MAASP (psi)"] = round(maasp)

        stages = [
            KillStage(
                name="1. Record the starting condition",
                description="Establish the gas cap volume and surface pressure.",
                actions=[
                    f"Surface pressure: {sicp:.0f} psi.",
                    f"Estimated gas at surface: "
                    f"{summary['Estimated gas volume at surface (bbl)']} bbl.",
                    "Confirm the gas is genuinely at surface before starting.",
                ],
            ),
            KillStage(
                name="2. Lubricate mud in",
                description=(
                    f"Pump {self.lube_volume_bbl:.1f} bbl of "
                    f"{kill_mud:.1f} ppg mud into the annulus."
                ),
                actions=[
                    f"Pump exactly {self.lube_volume_bbl:.1f} bbl in. Measure it.",
                    f"Surface pressure will RISE to roughly "
                    f"{pump_in_pressure:.0f} psi as the gas is compressed."
                    if pump_in_pressure != float("inf")
                    else "Surface pressure will rise as the gas is compressed.",
                    "Check that rise against MAASP and the wellhead rating "
                    "before choosing the lube volume.",
                ],
            ),
            KillStage(
                name="3. Wait for the mud to fall",
                description="Gravity separation. This is the step people rush.",
                actions=[
                    "Wait 15-30 minutes for the mud to fall through the gas.",
                    "Surface pressure will drift down slightly as it does.",
                    "Bleeding before the mud has fallen just vents the mud back.",
                ],
            ),
            KillStage(
                name="4. Bleed gas",
                description=(
                    f"Bleed gas until surface pressure has dropped "
                    f"{pressure_drop_per_cycle:.0f} psi net."
                ),
                actions=[
                    "Bleed GAS only, through the choke.",
                    f"Take pressure down by {pressure_drop_per_cycle:.0f} psi "
                    "below where it stood before the mud was pumped in.",
                    "That drop is the hydrostatic the lubricated mud added.",
                    "Do not bleed mud -- if mud reaches the choke, stop.",
                ],
            ),
            KillStage(
                name="5. Repeat",
                description=(
                    f"About {cycles} cycles to bring surface pressure to zero."
                ),
                actions=[
                    f"Repeat steps 2 to 4 roughly {cycles} times.",
                    f"Total mud lubricated: about "
                    f"{cycles * self.lube_volume_bbl:.0f} bbl.",
                    "The well is dead when surface pressure is zero and it stays "
                    "there with the choke closed.",
                ],
                table=[
                    {
                        "Cycle": n,
                        "Mud in (bbl)": round(self.lube_volume_bbl, 1),
                        "Cumulative (bbl)": round(self.lube_volume_bbl * n, 1),
                        "Pressure after (psi)": max(
                            0, round(sicp - pressure_drop_per_cycle * n)
                        ),
                    }
                    for n in range(1, min(cycles, 20) + 1)
                ],
            ),
        ]

        notes = [
            "Slow. Each cycle needs real waiting time for gravity separation, so "
            "a full lube and bleed can take many hours.",
            "Bleed gas, not mud. The opposite of the Volumetric Method, because "
            "here the gas is what you are trying to remove.",
            "Works only with free gas. In oil-based mud, gas goes into solution "
            "and there is no discrete gas cap to lubricate against.",
            "Check the pump-in pressure rise against MAASP before choosing the "
            "lube volume -- a bigger slug means a bigger spike.",
        ] + well.configuration.considerations()

        return self._new_plan(
            well,
            summary=summary,
            stages=stages,
            trace=trace,
            x_label="Cumulative mud lubricated (bbl)",
            notes=notes,
        )
