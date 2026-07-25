"""Stripping to bottom -- the operation that makes a kill possible again.

This is not a kill method. It is the intervention that comes between the
Volumetric Method and a conventional kill.

The sequence it belongs to:

1. A kick is taken with the bit **off bottom**. There is no circulation path to
   the influx, so neither Driller's nor Wait and Weight can be run.
2. The **Volumetric Method** holds bottomhole pressure while gas migrates. It
   buys time and margin. It does not kill the well.
3. **Stripping** returns the bit to bottom through closed BOPs, restoring the
   circulation path.
4. A conventional circulating kill finishes the job.

Skipping straight from step 2 to step 4 is not possible, and step 3 is where
most of the risk in that sequence sits: pipe is being moved in a live well, the
volume balance is manual, and the pipe may be trying to eject itself.

## What this method computes

* **Bleed volume per stand** -- pipe displacement, plus an allowance for gas
  migrating during the time the stand takes.
* **The balance point** -- the length of pipe below which the well pressure
  outweighs the string and it has to be snubbed rather than stripped.
* **Shoe pressure** as the gas migrates past it, so the operation can be
  checked against the fracture pressure before it starts.

## Simplification

The gas is tracked by migration alone. Pipe entering the hole displaces mud
which is bled off, so it does not move the gas materially, and the annular
capacity is taken as it stands at the start. The quantities this operation
turns on -- bleed volume, balance point, snub force, total volume -- do not
depend on that detail.
"""

from __future__ import annotations

from ..stripping import (
    ANNULAR_STRIPPING_LIMIT_PSI,
    StripDirection,
    StrippingOperation,
)
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


class StrippingToBottom(KillMethod):
    """Strip pipe back to bottom through closed BOPs to restore circulation."""

    key = "stripping"
    name = "Stripping to Bottom"
    summary = (
        "Run pipe back to bottom through closed BOPs, bleeding the pipe "
        "displacement to hold bottomhole pressure constant. Restores the "
        "circulation path so the well can then be killed conventionally."
    )
    circulates = False
    requires_migration = False

    def _operation(self, well: WellState) -> StrippingOperation:
        gas_top = well.influx_top_md_ft
        capacity = well.annulus.capacity_at(min(gas_top, well.hole_md_ft - 1.0))
        return StrippingOperation(
            pipe_od_in=well.annulus.string.components[-1].od_in,
            pipe_id_in=well.annulus.string.components[-1].id_in,
            pipe_weight_lb_per_ft=well.pipe_weight_lb_per_ft,
            stand_length_ft=well.stand_length_ft,
            start_depth_md_ft=well.bit_md_ft,
            target_depth_md_ft=well.hole_md_ft,
            annular_capacity_bbl_per_ft=capacity,
            mud_weight_ppg=well.mud_weight_ppg,
            surface_pressure_psi=well.sicp_psi,
            direction=StripDirection.IN,
            has_float=True,
            migration_rate_ft_per_hr=well.gas_migration_rate_ft_per_hr,
        )

    # -- applicability -------------------------------------------------------

    def applicability(self, well: WellState) -> Applicability:
        result = super().applicability(well)

        if well.bit_md_ft >= well.hole_md_ft - 1.0:
            result.block(
                f"The bit is already on bottom ({well.bit_md_ft:,.0f} ft of "
                f"{well.hole_md_ft:,.0f} ft). There is nothing to strip, and the "
                "well can be circulated -- use Driller's Method or Wait and "
                "Weight instead."
            )
            return result

        operation = self._operation(well)

        result.warn(
            "Stripping requires a float in the string. Without one the well "
            "flows up the inside of the pipe with nothing to stop it. The float "
            "is also why the pipe displaces its full outside diameter rather "
            "than just the steel."
        )

        if operation.snubbing_required:
            result.warn(
                f"Well pressure exerts {operation.upward_force_lbf:,.0f} lbf on "
                f"the pipe, which outweighs the string until "
                f"{operation.balance_point_ft:,.0f} ft is in the hole. The bit "
                f"is at {well.bit_md_ft:,.0f} ft, so the shallow part of this "
                "operation needs a snubbing unit, not a rig floor. Stripping "
                "and snubbing are different operations with different equipment."
            )

        if operation.recommended_technique.value == "ram_to_ram":
            result.warn(
                f"At {well.sicp_psi:,.0f} psi surface pressure, continuous "
                "stripping through the annular preventer is above the usual "
                f"{ANNULAR_STRIPPING_LIMIT_PSI:,.0f} psi rule of thumb. Plan for "
                "ram-to-ram (surge) stripping, and check the annular element's "
                "actual rating."
            )

        if (
            well.configuration.trajectory.migration_reliable
            and well.gas_migration_rate_ft_per_hr <= 0
        ):
            result.warn(
                "No gas migration rate has been entered for a well where gas "
                "will migrate. The bleed schedule therefore allows for pipe "
                "displacement only. Measure the migration rate from the rate of "
                "shut-in pressure rise and re-run, or the well will gain "
                "pressure faster than the schedule expects."
            )

        if well.configuration.is_horizontal:
            result.warn(
                "In the lateral the pipe displaces mud but gains almost no "
                "hydrostatic, so bleeding the displacement still holds "
                "bottomhole pressure -- but gas in the lateral will not migrate "
                "to meet the bit. Stripping through the build section is what "
                "re-establishes contact with the influx."
            )

        maasp = well.maasp_psi()
        if maasp is not None and well.sicp_psi > maasp:
            result.block(
                f"Casing pressure ({well.sicp_psi:,.0f} psi) already exceeds "
                f"MAASP ({maasp:,.0f} psi). Stripping cannot begin from here -- "
                "the shoe is the problem before the pipe is."
            )

        return result

    # -- plan ----------------------------------------------------------------

    def plan(self, well: WellState) -> KillPlan:
        if well.bit_md_ft >= well.hole_md_ft - 1.0:
            plan = self._new_plan(
                well,
                summary={"Bit depth (ft MD)": round(well.bit_md_ft)},
                stages=[
                    KillStage(
                        name="Nothing to strip",
                        description="The bit is already on bottom.",
                        actions=[
                            "Circulate and kill conventionally.",
                        ],
                    )
                ],
                trace=[
                    TracePoint(x=0.0, stage="n/a", casing_psi=well.sicp_psi,
                               pipe_depth_md_ft=well.bit_md_ft)
                ],
                x_label="Stand",
                notes=well.configuration.considerations(),
            )
            return plan

        operation = self._operation(well)
        steps = operation.schedule()

        formation_pressure = well.formation_pressure_psi
        mud = well.mud_weight_ppg
        influx_density = well.influx_density_ppg
        gradient = well.influx_gradient_psi_per_ft
        hole_md = well.hole_md_ft
        shoe_md = well.shoe_md
        annulus_volume = well.annulus.volume_bbl

        initial_gas_top = well.influx_top_md_ft
        reference_psia = psi_to_psia(
            formation_pressure - gradient * well.influx_height_tvd_ft / 2.0
        )

        trace: list[TracePoint] = []
        for index, step in enumerate(steps):
            hours = index * operation.minutes_per_stand / 60.0
            risen = well.gas_migration_rate_ft_per_hr * hours
            gas_top = max(0.0, initial_gas_top - risen)
            volume_above = well.annulus.volume_between(0.0, gas_top)

            gas_volume = well.pit_gain_bbl
            gas_bottom = hole_md
            for _ in range(6):
                gas_volume = min(gas_volume, annulus_volume - volume_above)
                gas_bottom = well.annulus_md_at_volume_from_surface(
                    volume_above + gas_volume
                )
                zones = [
                    Zone(0.0, gas_top, mud, "mud above gas"),
                    Zone(gas_top, gas_bottom, influx_density, "gas"),
                    Zone(gas_bottom, hole_md, mud, "mud below gas"),
                ]
                column = FluidColumn(zones, well.survey)
                casing = column.surface_pressure_for_bottomhole(formation_pressure)
                midpoint = (gas_top + gas_bottom) / 2.0
                pressure = column.pressure_at(midpoint, casing)
                if pressure <= 1.0:
                    break
                gas_volume = well.pit_gain_bbl * reference_psia / psi_to_psia(pressure)

            zones = [
                Zone(0.0, gas_top, mud, "mud above gas"),
                Zone(gas_top, gas_bottom, influx_density, "gas"),
                Zone(gas_bottom, hole_md, mud, "mud below gas"),
            ]
            column = FluidColumn(zones, well.survey)
            casing = max(0.0, column.surface_pressure_for_bottomhole(formation_pressure))
            shoe = column.pressure_at(shoe_md, casing) if shoe_md is not None else None

            trace.append(
                TracePoint(
                    x=float(step.stand),
                    stage="Stripping in",
                    casing_psi=casing,
                    shoe_psi=shoe,
                    influx_volume_bbl=gas_volume,
                    influx_top_md_ft=gas_top,
                    influx_bottom_md_ft=gas_bottom,
                    pipe_depth_md_ft=step.pipe_depth_md_ft,
                    note=f"{step.cumulative_bleed_bbl:.1f} bbl bled",
                )
            )

        summary: dict[str, object] = dict(operation.summary())
        summary["Formation pressure (psi)"] = round(formation_pressure)
        summary["Open-ended displacement, for comparison (bbl/ft)"] = round(
            operation.open_ended_displacement_bbl_per_ft, 5
        )
        summary["Total time at "
                f"{operation.minutes_per_stand:.0f} min/stand (hr)"] = round(
            operation.stands_required * operation.minutes_per_stand / 60.0, 1
        )
        peak_shoe = max((p.shoe_psi for p in trace if p.shoe_psi is not None),
                        default=None)
        if peak_shoe is not None:
            summary["Peak shoe pressure (psi)"] = round(peak_shoe)
        if well.frac_pressure_psi is not None:
            summary["Shoe fracture pressure (psi)"] = round(well.frac_pressure_psi)

        no_bleed_note = self._no_bleed_warning(operation, well)

        stages = [
            KillStage(
                name="1. Rig up and confirm the string",
                description=(
                    "Stripping cannot start without a float and a measured tank."
                ),
                actions=[
                    "Confirm a float is fitted. Without one the well flows up "
                    "the drill pipe.",
                    f"Line up a calibrated trip tank. You need to measure "
                    f"{operation.volume_per_stand_bbl:.2f} bbl per stand to "
                    "within a few tenths.",
                    f"Technique: {operation.recommended_technique.label}.",
                    f"Current casing pressure: {well.sicp_psi:,.0f} psi."
                    + (
                        f"  MAASP: {well.maasp_psi():,.0f} psi."
                        if well.maasp_psi() is not None else ""
                    ),
                ],
            ),
            KillStage(
                name="2. Check the balance point before running",
                description=(
                    "Well pressure pushes the pipe up. Below the balance point "
                    "it has to be snubbed, not stripped."
                ),
                actions=[
                    f"Upward force on the pipe: "
                    f"{operation.upward_force_lbf:,.0f} lbf.",
                    f"Buoyancy factor at {mud:.1f} ppg: "
                    f"{operation.buoyancy_factor:.3f}.",
                    f"Balance point: {operation.balance_point_ft:,.0f} ft of "
                    "pipe in the hole.",
                    (
                        f"The bit is at {well.bit_md_ft:,.0f} ft, which is BELOW "
                        "the balance point -- the string will strip in under its "
                        "own weight."
                        if not operation.snubbing_required
                        else f"The bit is at {well.bit_md_ft:,.0f} ft, ABOVE the "
                        f"balance point of {operation.balance_point_ft:,.0f} ft. "
                        "A snubbing unit is required for the shallow part."
                    ),
                ],
            ),
            KillStage(
                name="3. Strip in, bleeding volume for every stand",
                description=(
                    f"{operation.stands_required} stands from "
                    f"{well.bit_md_ft:,.0f} ft to {hole_md:,.0f} ft, bleeding "
                    f"{operation.total_bleed_per_stand_bbl:.2f} bbl per stand."
                ),
                strokes=None,
                actions=[
                    f"Bleed {operation.volume_per_stand_bbl:.2f} bbl per stand "
                    "for pipe displacement.",
                    (
                        f"Bleed a further "
                        f"{operation.migration_bleed_per_stand_bbl:.2f} bbl per "
                        f"stand for gas migrating "
                        f"{operation.migration_per_stand_ft:.0f} ft in the "
                        f"{operation.minutes_per_stand:.0f} minutes a stand "
                        "takes."
                        if operation.migration_bleed_per_stand_bbl > 0
                        else "No migration allowance -- gas is not migrating, or "
                             "no rate was entered."
                    ),
                    "Casing pressure should stay CONSTANT. Volume is the "
                    "control; pressure is the confirmation.",
                    "Rising pressure means you are under-bleeding, or gas is "
                    "migrating faster than allowed for.",
                    "Falling pressure means you are over-bleeding -- stop before "
                    "the well takes a second influx.",
                    no_bleed_note,
                ],
                table=[
                    {
                        "Stand": s.stand,
                        "Bit depth (ft)": round(s.pipe_depth_md_ft),
                        "Bleed (bbl)": round(s.total_bleed_bbl, 2),
                        "Cumulative (bbl)": round(s.cumulative_bleed_bbl, 1),
                        "Snub force (lbf)": (
                            round(s.snub_force_lbf) if s.needs_snubbing else "-"
                        ),
                    }
                    for s in steps[:: max(1, len(steps) // 20)]
                ],
            ),
            KillStage(
                name="4. On bottom - circulate and kill",
                description=(
                    "The point of the whole operation: a circulation path to "
                    "the influx."
                ),
                actions=[
                    "Confirm the bit is on bottom and the string is not plugged.",
                    "Record SIDPP once circulation is established -- it may have "
                    "changed while the well sat.",
                    "Kill conventionally with Driller's Method or Wait and "
                    "Weight.",
                ],
            ),
        ]

        notes = [
            "Stripping is not a kill. It restores the circulation path so that "
            "a kill becomes possible.",
            "Volume is the control variable. A calibrated trip tank matters more "
            "than the pressure gauge.",
            "The float is what makes the pipe displace its full OD rather than "
            f"just the steel -- {operation.displacement_bbl_per_ft:.5f} against "
            f"{operation.open_ended_displacement_bbl_per_ft:.5f} bbl/ft, a factor "
            f"of {operation.displacement_bbl_per_ft / operation.open_ended_displacement_bbl_per_ft:.1f}. "
            "Bleeding to the open-ended figure would under-bleed badly.",
            "Run slowly. Surge pressure adds directly to bottomhole pressure, "
            "and on a well with little margin at the shoe it sets the speed.",
        ] + well.configuration.considerations()

        plan = self._new_plan(
            well,
            summary=summary,
            stages=stages,
            trace=trace,
            x_label="Stand number",
            notes=notes,
        )

        if peak_shoe is not None and well.frac_pressure_psi is not None:
            margin = well.frac_pressure_psi - peak_shoe
            plan.summary["Margin at shoe (psi)"] = round(margin)
            if margin < 0:
                plan.applicability.block(
                    f"Shoe pressure reaches {peak_shoe:,.0f} psi during the "
                    f"operation against a fracture pressure of "
                    f"{well.frac_pressure_psi:,.0f} psi. The gas migrating "
                    "upward would break down the shoe before the bit gets to "
                    "bottom."
                )

        return plan

    @staticmethod
    def _no_bleed_warning(operation: StrippingOperation, well: WellState) -> str:
        """Quantify what happens if a stand goes in without bleeding."""
        try:
            risen = pressure = _pressure_after_missed_stand(operation, well)
        except ValueError:
            return (
                "If a stand goes in without bleeding, the mud has nowhere to go "
                "and the pressure rise is limited only by the stiffness of the "
                "mud and the casing. Do not miss one."
            )
        del risen
        return (
            f"Miss the bleed on one stand and surface pressure jumps from "
            f"{well.sicp_psi:,.0f} to about {pressure:,.0f} psi as the "
            f"{operation.volume_per_stand_bbl:.2f} bbl compresses the gas."
        )


def _pressure_after_missed_stand(
    operation: StrippingOperation, well: WellState
) -> float:
    from ..stripping import pressure_rise_if_not_bled

    return pressure_rise_if_not_bled(
        operation.volume_per_stand_bbl, well.pit_gain_bbl, well.sicp_psi
    )
