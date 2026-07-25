"""Stripping and snubbing: moving pipe in a well that is under pressure.

The Volumetric Method holds a well that cannot be circulated, but it does not
kill it. Stripping is what closes the loop: it returns the bit to bottom through
closed BOPs so that a conventional circulating kill becomes possible again.

## The one idea

Running pipe into a closed well adds steel to a fixed volume. That volume has to
come out, or the pressure spikes::

    volume to bleed per foot = closed-end displacement = OD² / 1029.4

Bleed exactly that and the mud level -- and therefore hydrostatic, and therefore
bottomhole pressure -- does not move. Bleed too little and bottomhole pressure
climbs toward the fracture pressure at the shoe. Bleed too much and the well
goes underbalanced and takes a second influx.

**Volume is the control variable, not pressure.** An accurately measured trip
tank is the instrument that matters. Casing pressure is the confirmation.

## Closed end, always

Stripping is done with a float in the string. Without one, the well would flow
up the inside of the pipe with nothing to stop it. The float means the pipe does
not fill as it goes, so it displaces its **full outside diameter**, not just the
steel::

    5in pipe, closed end: 25 / 1029.4     = 0.02429 bbl/ft
    5in x 4.276in, open:  (25 - 18.28)/1029.4 = 0.00652 bbl/ft

A factor of 3.7. Using the open-ended figure would leave you bleeding barely a
quarter of what the well is taking.

## Stripping versus snubbing

Well pressure pushes the pipe *up*, on the full cross-section of the closed end.
Pipe goes in under its own weight only while it outweighs that force::

    force up   = P × (π/4) × OD²
    weight     = weight per foot × length × buoyancy factor

Below the **balance point** the pipe is lighter than the force trying to eject
it, and it has to be pushed in against pressure -- that is snubbing, and it
needs a snubbing unit, not a rig floor. The balance point is a length of pipe,
so a shallow bit and a high surface pressure is the dangerous combination.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum

from .geometry import closed_end_displacement_bbl_per_ft, metal_displacement_bbl_per_ft
from .units import PSI_PER_PPG_FT, psi_to_psia

#: Density of steel, ppg. Used for the buoyancy factor.
STEEL_PPG: float = 65.5

#: Surface pressure above which an annular preventer is usually not relied on
#: for continuous stripping, psi. Element-specific -- check the actual BOP.
ANNULAR_STRIPPING_LIMIT_PSI: float = 1500.0


class StripDirection(Enum):
    """Which way the pipe is moving."""

    IN = "in"
    OUT = "out"

    @property
    def label(self) -> str:
        return "Stripping in" if self is StripDirection.IN else "Stripping out"


class StripTechnique(Enum):
    """How the pipe is passed through the stack."""

    ANNULAR = "annular"
    RAM_TO_RAM = "ram_to_ram"

    @property
    def label(self) -> str:
        return {
            StripTechnique.ANNULAR: "Through the annular preventer",
            StripTechnique.RAM_TO_RAM: "Ram to ram (surge stripping)",
        }[self]


# --------------------------------------------------------------------------
# Standalone helpers
# --------------------------------------------------------------------------

def buoyancy_factor(mud_weight_ppg: float) -> float:
    """Fraction of its air weight that steel retains in mud.

    ``BF = 1 - MW / 65.5``. At 9.6 ppg this is 0.853.
    """
    if mud_weight_ppg >= STEEL_PPG:
        raise ValueError("Mud heavier than steel is not physical")
    return 1.0 - mud_weight_ppg / STEEL_PPG


def upward_force_lbf(surface_pressure_psi: float, pipe_od_in: float) -> float:
    """Force well pressure exerts on closed-end pipe, lbf.

    Acts on the full outside area because the float seals the bore.
    """
    area = math.pi / 4.0 * pipe_od_in ** 2
    return surface_pressure_psi * area


def pipe_weight_in_mud_lbf(
    length_ft: float, weight_lb_per_ft: float, mud_weight_ppg: float
) -> float:
    """Buoyed weight of a length of pipe, lbf."""
    return length_ft * weight_lb_per_ft * buoyancy_factor(mud_weight_ppg)


def balance_point_length_ft(
    surface_pressure_psi: float,
    pipe_od_in: float,
    weight_lb_per_ft: float,
    mud_weight_ppg: float,
) -> float:
    """Length of pipe whose buoyed weight equals the upward force, ft.

    Shorter than this and the pipe must be snubbed in. Longer and it strips in
    under its own weight.
    """
    force = upward_force_lbf(surface_pressure_psi, pipe_od_in)
    per_foot = weight_lb_per_ft * buoyancy_factor(mud_weight_ppg)
    if per_foot <= 0:
        raise ValueError("Pipe weight per foot must be positive")
    return force / per_foot


def snub_force_lbf(
    surface_pressure_psi: float,
    pipe_od_in: float,
    length_in_hole_ft: float,
    weight_lb_per_ft: float,
    mud_weight_ppg: float,
) -> float:
    """Force needed to push pipe in, lbf. Zero or negative means it strips."""
    force = upward_force_lbf(surface_pressure_psi, pipe_od_in)
    weight = pipe_weight_in_mud_lbf(length_in_hole_ft, weight_lb_per_ft, mud_weight_ppg)
    return force - weight


def pressure_rise_if_not_bled(
    volume_displaced_bbl: float, gas_volume_bbl: float, surface_pressure_psi: float
) -> float:
    """Surface pressure after stripping in without bleeding, psi.

    The displaced volume has nowhere to go but into compressing the gas, by
    Boyle's law::

        P2 = P1 × Vg / (Vg - V)

    With no gas in the hole the mud is effectively incompressible and the rise
    is violent -- hundreds of psi for a single stand. This is why the trip tank
    measurement is not optional.
    """
    if gas_volume_bbl <= volume_displaced_bbl:
        raise ValueError(
            f"The displaced volume ({volume_displaced_bbl:.2f} bbl) is at least "
            f"as large as the gas in the hole ({gas_volume_bbl:.2f} bbl). There "
            "is nothing compressible left to absorb it -- the pressure rise "
            "would be limited only by the stiffness of the mud and the casing."
        )
    absolute = psi_to_psia(surface_pressure_psi) * gas_volume_bbl / (
        gas_volume_bbl - volume_displaced_bbl
    )
    return absolute - 14.7


def surge_pressure_estimate(
    pipe_speed_ft_per_min: float,
    hole_id_in: float,
    pipe_od_in: float,
    length_ft: float,
    model,
    mud_weight_ppg: float | None = None,
    clinging_factor: float = 0.45,
) -> float:
    """Surge pressure from running closed-end pipe, psi.

    Mud is displaced up the annulus by the advancing pipe, and some is dragged
    along with it::

        V_annulus = V_pipe × [clinging + OD² / (hole² - OD²)]

    That effective annular velocity is fed to the friction correlation.

    A rough estimate, and deliberately so -- it exists to answer "is this
    fast enough to matter?" rather than to give a number to design against.
    Surge adds directly to bottomhole pressure, so on a well with little margin
    at the shoe it sets the stripping speed.
    """
    from .rheology import BinghamPlastic

    area_term = hole_id_in ** 2 - pipe_od_in ** 2
    if area_term <= 0:
        raise ValueError("Hole ID must exceed pipe OD")

    effective = pipe_speed_ft_per_min * (
        clinging_factor + pipe_od_in ** 2 / area_term
    )
    # Convert an annular velocity back to the flow rate the correlations take.
    flow_gpm = effective * area_term / 24.5

    if isinstance(model, BinghamPlastic):
        if mud_weight_ppg is None:
            raise ValueError("The Bingham model needs mud_weight_ppg")
        gradient = model.annular_gradient_psi_per_ft(
            flow_gpm, hole_id_in, pipe_od_in, mud_weight_ppg
        )
    else:
        gradient = model.annular_gradient_psi_per_ft(flow_gpm, hole_id_in, pipe_od_in)
    return gradient * length_ft


# --------------------------------------------------------------------------
# The operation
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class StripStep:
    """One stand of a stripping operation."""

    stand: int
    pipe_depth_md_ft: float
    length_in_hole_ft: float
    displacement_bbl: float
    migration_bleed_bbl: float
    total_bleed_bbl: float
    cumulative_bleed_bbl: float
    snub_force_lbf: float
    needs_snubbing: bool


@dataclass
class StrippingOperation:
    """A stripping operation, from the current bit depth to a target.

    Args:
        pipe_od_in: Drill pipe outside diameter.
        pipe_id_in: Drill pipe inside diameter. Used only for the open-ended
            comparison; stripping itself uses the closed-end figure.
        pipe_weight_lb_per_ft: Nominal weight in air.
        stand_length_ft: Length of one stand, typically 93 ft for triples.
        start_depth_md_ft: Where the bit is now.
        target_depth_md_ft: Where it needs to get to.
        annular_capacity_bbl_per_ft: Annular capacity where mud is bled from.
        mud_weight_ppg: Mud in the hole.
        surface_pressure_psi: Casing pressure being held.
        direction: Stripping in or out.
        has_float: Whether a float is fitted. Stripping without one is not
            normal practice and the displacement figure changes.
        migration_rate_ft_per_hr: Gas migration rate, if gas is migrating.
        minutes_per_stand: How long one stand takes, for the migration
            allowance.
    """

    pipe_od_in: float
    pipe_id_in: float
    pipe_weight_lb_per_ft: float
    stand_length_ft: float
    start_depth_md_ft: float
    target_depth_md_ft: float
    annular_capacity_bbl_per_ft: float
    mud_weight_ppg: float
    surface_pressure_psi: float
    direction: StripDirection = StripDirection.IN
    has_float: bool = True
    migration_rate_ft_per_hr: float = 0.0
    minutes_per_stand: float = 6.0

    def __post_init__(self) -> None:
        if self.stand_length_ft <= 0:
            raise ValueError("Stand length must be positive")
        if self.annular_capacity_bbl_per_ft <= 0:
            raise ValueError("Annular capacity must be positive")
        if self.direction is StripDirection.IN:
            if self.target_depth_md_ft <= self.start_depth_md_ft:
                raise ValueError(
                    f"Stripping in, but the target ({self.target_depth_md_ft:.0f} ft) "
                    f"is not below the current depth ({self.start_depth_md_ft:.0f} ft)."
                )
        elif self.target_depth_md_ft >= self.start_depth_md_ft:
            raise ValueError(
                f"Stripping out, but the target ({self.target_depth_md_ft:.0f} ft) "
                f"is not above the current depth ({self.start_depth_md_ft:.0f} ft)."
            )

    # -- displacement --------------------------------------------------------

    @property
    def displacement_bbl_per_ft(self) -> float:
        """Volume displaced per foot of pipe moved, bbl/ft."""
        if self.has_float:
            return closed_end_displacement_bbl_per_ft(self.pipe_od_in)
        return metal_displacement_bbl_per_ft(self.pipe_od_in, self.pipe_id_in)

    @property
    def open_ended_displacement_bbl_per_ft(self) -> float:
        """The open-ended figure, for comparison. Using it here would be wrong."""
        return metal_displacement_bbl_per_ft(self.pipe_od_in, self.pipe_id_in)

    @property
    def volume_per_stand_bbl(self) -> float:
        """Mud to bleed for one stand, ignoring migration, bbl."""
        return self.displacement_bbl_per_ft * self.stand_length_ft

    @property
    def distance_ft(self) -> float:
        return abs(self.target_depth_md_ft - self.start_depth_md_ft)

    @property
    def stands_required(self) -> int:
        return max(1, math.ceil(self.distance_ft / self.stand_length_ft))

    @property
    def total_displacement_bbl(self) -> float:
        """Total volume to bleed (in) or pump (out), bbl."""
        return self.displacement_bbl_per_ft * self.distance_ft

    # -- migration -----------------------------------------------------------

    @property
    def migration_per_stand_ft(self) -> float:
        """How far gas rises during one stand, ft."""
        return self.migration_rate_ft_per_hr * self.minutes_per_stand / 60.0

    @property
    def migration_bleed_per_stand_bbl(self) -> float:
        """Extra volume to bleed for migration during one stand, bbl.

        Gas rising a distance ``d`` raises surface pressure by
        ``0.052 × MW × d``. Bringing that back down means removing a mud column
        of the same height, which is ``d × annular capacity`` of volume. The
        mud weight cancels -- the answer is just the swept volume.
        """
        if self.direction is StripDirection.OUT:
            return 0.0
        return self.migration_per_stand_ft * self.annular_capacity_bbl_per_ft

    @property
    def total_bleed_per_stand_bbl(self) -> float:
        """Everything to bleed for one stand, bbl."""
        return self.volume_per_stand_bbl + self.migration_bleed_per_stand_bbl

    @property
    def migration_pressure_rise_per_stand_psi(self) -> float:
        """Surface pressure rise from migration during one stand, psi."""
        return PSI_PER_PPG_FT * self.mud_weight_ppg * self.migration_per_stand_ft

    # -- forces --------------------------------------------------------------

    @property
    def buoyancy_factor(self) -> float:
        return buoyancy_factor(self.mud_weight_ppg)

    @property
    def upward_force_lbf(self) -> float:
        return upward_force_lbf(self.surface_pressure_psi, self.pipe_od_in)

    @property
    def balance_point_ft(self) -> float:
        """Length of pipe below which snubbing is required, ft."""
        return balance_point_length_ft(
            self.surface_pressure_psi,
            self.pipe_od_in,
            self.pipe_weight_lb_per_ft,
            self.mud_weight_ppg,
        )

    def needs_snubbing_at(self, length_in_hole_ft: float) -> bool:
        return length_in_hole_ft < self.balance_point_ft

    def snub_force_at(self, length_in_hole_ft: float) -> float:
        return snub_force_lbf(
            self.surface_pressure_psi,
            self.pipe_od_in,
            length_in_hole_ft,
            self.pipe_weight_lb_per_ft,
            self.mud_weight_ppg,
        )

    @property
    def snubbing_required(self) -> bool:
        """Whether any part of this operation falls below the balance point."""
        shallowest = min(self.start_depth_md_ft, self.target_depth_md_ft)
        return shallowest < self.balance_point_ft

    # -- technique -----------------------------------------------------------

    @property
    def recommended_technique(self) -> StripTechnique:
        """Annular or ram-to-ram, on surface pressure alone.

        A rule of thumb, not a specification. The real limit is the annular
        element's rating and condition, and the operator's procedure.
        """
        if self.surface_pressure_psi <= ANNULAR_STRIPPING_LIMIT_PSI:
            return StripTechnique.ANNULAR
        return StripTechnique.RAM_TO_RAM

    # -- schedule ------------------------------------------------------------

    def schedule(self) -> list[StripStep]:
        """One row per stand."""
        steps: list[StripStep] = []
        cumulative = 0.0
        sign = 1.0 if self.direction is StripDirection.IN else -1.0
        remaining = self.distance_ft

        for stand in range(1, self.stands_required + 1):
            moved = min(self.stand_length_ft, remaining)
            remaining -= moved
            depth = self.start_depth_md_ft + sign * (
                self.distance_ft - remaining
            )
            displacement = self.displacement_bbl_per_ft * moved
            migration = (
                self.migration_bleed_per_stand_bbl * moved / self.stand_length_ft
            )
            total = displacement + migration
            cumulative += total
            force = self.snub_force_at(depth)

            steps.append(
                StripStep(
                    stand=stand,
                    pipe_depth_md_ft=depth,
                    length_in_hole_ft=depth,
                    displacement_bbl=displacement,
                    migration_bleed_bbl=migration,
                    total_bleed_bbl=total,
                    cumulative_bleed_bbl=cumulative,
                    snub_force_lbf=force,
                    needs_snubbing=force > 0,
                )
            )
        return steps

    def summary(self) -> dict[str, object]:
        return {
            "Direction": self.direction.label,
            "From (ft MD)": round(self.start_depth_md_ft),
            "To (ft MD)": round(self.target_depth_md_ft),
            "Distance (ft)": round(self.distance_ft),
            "Stand length (ft)": round(self.stand_length_ft, 1),
            "Stands required": self.stands_required,
            "Displacement (bbl/ft)": round(self.displacement_bbl_per_ft, 5),
            "Volume per stand (bbl)": round(self.volume_per_stand_bbl, 2),
            "Migration bleed per stand (bbl)": round(
                self.migration_bleed_per_stand_bbl, 2
            ),
            "Total bleed per stand (bbl)": round(self.total_bleed_per_stand_bbl, 2),
            "Total volume (bbl)": round(self.total_displacement_bbl, 1),
            "Buoyancy factor": round(self.buoyancy_factor, 3),
            "Upward force on pipe (lbf)": round(self.upward_force_lbf),
            "Balance point (ft)": round(self.balance_point_ft),
            "Snubbing required": "yes" if self.snubbing_required else "no",
            "Technique": self.recommended_technique.label,
        }
