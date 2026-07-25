"""Mud rheology and friction pressure losses.

Friction is what separates static pressure from circulating pressure. Two
places it matters directly for well control:

* **ECD** -- annular friction adds to bottomhole pressure while circulating.
  In a narrow-margin well the difference between mud weight and ECD is the
  whole drilling window.
* **Slow circulating rate pressure** -- the pressure needed to move mud at kill
  rate. This is measured, not calculated, before it is ever needed, because
  during a kick there is no time to work it out and no way to measure it
  without disturbing the well.

Two rheological models are provided. **Bingham plastic** (plastic viscosity and
yield point) is the field standard, is what the mud report gives you, and is
adequate for well control work. **Power law** fits shear-thinning muds better at
the low annular shear rates that dominate ECD, and is the better choice for
narrow-margin and MPD work.

All friction correlations are approximations. Where a measured slow circulating
rate pressure exists, use it in preference to anything computed here.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


# --------------------------------------------------------------------------
# Velocities
# --------------------------------------------------------------------------

def annular_velocity_ft_per_min(
    flow_rate_gpm: float, hole_id_in: float, pipe_od_in: float
) -> float:
    """Average annular velocity, ft/min."""
    area_term = hole_id_in ** 2 - pipe_od_in ** 2
    if area_term <= 0:
        raise ValueError("Hole ID must exceed pipe OD")
    return 24.5 * flow_rate_gpm / area_term


def pipe_velocity_ft_per_min(flow_rate_gpm: float, id_in: float) -> float:
    """Average velocity inside a pipe, ft/min."""
    if id_in <= 0:
        raise ValueError("Pipe ID must be positive")
    return 24.5 * flow_rate_gpm / id_in ** 2


# --------------------------------------------------------------------------
# Rheological models
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class BinghamPlastic:
    """Bingham plastic model, straight off the mud report.

    Attributes:
        plastic_viscosity_cp: PV, cP. Resistance from solids content.
        yield_point_lb_100ft2: YP, lb/100 ft^2. Gel strength / carrying capacity.
    """

    plastic_viscosity_cp: float
    yield_point_lb_100ft2: float

    @classmethod
    def from_dial_readings(cls, r600: float, r300: float) -> "BinghamPlastic":
        """Derive PV and YP from Fann viscometer dial readings::

            PV = R600 - R300
            YP = R300 - PV
        """
        pv = r600 - r300
        return cls(plastic_viscosity_cp=pv, yield_point_lb_100ft2=r300 - pv)

    def critical_velocity_annulus(
        self, mud_weight_ppg: float, hole_id_in: float, pipe_od_in: float
    ) -> float:
        """Velocity at which annular flow turns turbulent, ft/min."""
        gap = hole_id_in - pipe_od_in
        if gap <= 0:
            raise ValueError("Hole ID must exceed pipe OD")
        pv = self.plastic_viscosity_cp
        yp = self.yield_point_lb_100ft2
        return (
            97.0 * pv
            + 97.0 * math.sqrt(pv ** 2 + 8.2 * mud_weight_ppg * yp * gap ** 2)
        ) / (mud_weight_ppg * gap)

    def critical_velocity_pipe(self, mud_weight_ppg: float, id_in: float) -> float:
        """Velocity at which flow inside the pipe turns turbulent, ft/min."""
        pv = self.plastic_viscosity_cp
        yp = self.yield_point_lb_100ft2
        return (
            97.0 * pv
            + 97.0 * math.sqrt(pv ** 2 + 6.2 * mud_weight_ppg * yp * id_in ** 2)
        ) / (mud_weight_ppg * id_in)

    def annular_gradient_psi_per_ft(
        self,
        flow_rate_gpm: float,
        hole_id_in: float,
        pipe_od_in: float,
        mud_weight_ppg: float,
    ) -> float:
        """Annular friction gradient, psi/ft.

        Picks laminar or turbulent based on the critical velocity.
        """
        gap = hole_id_in - pipe_od_in
        velocity = annular_velocity_ft_per_min(flow_rate_gpm, hole_id_in, pipe_od_in)
        critical = self.critical_velocity_annulus(mud_weight_ppg, hole_id_in, pipe_od_in)
        pv = self.plastic_viscosity_cp
        yp = self.yield_point_lb_100ft2

        if velocity <= critical:
            return pv * velocity / (60000.0 * gap ** 2) + yp / (200.0 * gap)
        return (
            mud_weight_ppg ** 0.75 * velocity ** 1.75 * pv ** 0.25
            / (1396.0 * gap ** 1.25)
        )

    def pipe_gradient_psi_per_ft(
        self, flow_rate_gpm: float, id_in: float, mud_weight_ppg: float
    ) -> float:
        """Friction gradient inside the drill string, psi/ft."""
        velocity = pipe_velocity_ft_per_min(flow_rate_gpm, id_in)
        critical = self.critical_velocity_pipe(mud_weight_ppg, id_in)
        pv = self.plastic_viscosity_cp
        yp = self.yield_point_lb_100ft2

        if velocity <= critical:
            return pv * velocity / (90000.0 * id_in ** 2) + yp / (225.0 * id_in)
        return (
            mud_weight_ppg ** 0.75 * velocity ** 1.75 * pv ** 0.25
            / (1800.0 * id_in ** 1.25)
        )


@dataclass(frozen=True)
class PowerLaw:
    """Power law model, fitted separately for the pipe and the annulus.

    The pipe fit uses the high-shear 600/300 rpm readings; the annulus fit uses
    the low-shear 100/3 rpm readings, because those are the shear rates each
    region actually sees. Using one fit for both is a common and avoidable
    error.

    Attributes:
        n_pipe: Flow behaviour index for the string.
        k_pipe: Consistency index for the string, lb-s^n/100 ft^2.
        n_annulus: Flow behaviour index for the annulus.
        k_annulus: Consistency index for the annulus, lb-s^n/100 ft^2.
    """

    n_pipe: float
    k_pipe: float
    n_annulus: float
    k_annulus: float

    @classmethod
    def from_dial_readings(
        cls, r600: float, r300: float, r100: float, r3: float
    ) -> "PowerLaw":
        """Fit both regions from four Fann dial readings."""
        for name, value in (("R600", r600), ("R300", r300), ("R100", r100), ("R3", r3)):
            if value <= 0:
                raise ValueError(f"{name} must be positive to fit a power law")
        n_pipe = 3.32 * math.log10(r600 / r300)
        k_pipe = 5.11 * r600 / (1022.0 ** n_pipe)
        n_ann = 0.657 * math.log10(r100 / r3)
        k_ann = 5.11 * r100 / (170.2 ** n_ann)
        return cls(n_pipe=n_pipe, k_pipe=k_pipe, n_annulus=n_ann, k_annulus=k_ann)

    def annular_gradient_psi_per_ft(
        self, flow_rate_gpm: float, hole_id_in: float, pipe_od_in: float
    ) -> float:
        """Annular friction gradient, psi/ft (laminar power law)."""
        gap = hole_id_in - pipe_od_in
        if gap <= 0:
            raise ValueError("Hole ID must exceed pipe OD")
        n = self.n_annulus
        velocity = annular_velocity_ft_per_min(flow_rate_gpm, hole_id_in, pipe_od_in)
        shear = (2.4 * velocity / gap) * ((2.0 * n + 1.0) / (3.0 * n))
        return shear ** n * self.k_annulus / (300.0 * gap)

    def pipe_gradient_psi_per_ft(self, flow_rate_gpm: float, id_in: float) -> float:
        """Friction gradient inside the string, psi/ft (laminar power law)."""
        if id_in <= 0:
            raise ValueError("Pipe ID must be positive")
        n = self.n_pipe
        velocity = pipe_velocity_ft_per_min(flow_rate_gpm, id_in)
        shear = (1.6 * velocity / id_in) * ((3.0 * n + 1.0) / (4.0 * n))
        return shear ** n * self.k_pipe / (300.0 * id_in)


# --------------------------------------------------------------------------
# Whole-annulus loss
# --------------------------------------------------------------------------

def annular_pressure_loss(
    annulus,
    flow_rate_gpm: float,
    model: BinghamPlastic | PowerLaw,
    mud_weight_ppg: float | None = None,
    top_md: float = 0.0,
    bottom_md: float | None = None,
) -> float:
    """Total annular friction pressure loss, psi.

    Sums the friction gradient across every geometry interval of the annulus,
    so the tighter clearance around the drill collars is accounted for properly
    instead of being averaged away.

    Args:
        annulus: A :class:`wellcontrol.geometry.Annulus`.
        flow_rate_gpm: Circulating rate.
        model: A :class:`BinghamPlastic` or :class:`PowerLaw` instance.
        mud_weight_ppg: Required for the Bingham model (turbulent term),
            ignored by the power law model.
        top_md: Shallowest depth to include, MD ft.
        bottom_md: Deepest depth to include, MD ft. Defaults to the bit.

    Returns:
        Pressure loss in psi.
    """
    if isinstance(model, BinghamPlastic) and mud_weight_ppg is None:
        raise ValueError("The Bingham model needs mud_weight_ppg")

    limit = annulus.string.bit_depth_md if bottom_md is None else bottom_md
    total = 0.0
    for interval in annulus.intervals:
        lo = max(interval.top_md, top_md)
        hi = min(interval.bottom_md, limit)
        if hi <= lo:
            continue
        # Below the bit the pipe OD is zero and there is effectively no
        # circulation past it; skip those intervals.
        if interval.pipe_od_in <= 0:
            continue
        if isinstance(model, BinghamPlastic):
            gradient = model.annular_gradient_psi_per_ft(
                flow_rate_gpm, interval.hole_id_in, interval.pipe_od_in, mud_weight_ppg
            )
        else:
            gradient = model.annular_gradient_psi_per_ft(
                flow_rate_gpm, interval.hole_id_in, interval.pipe_od_in
            )
        total += gradient * (hi - lo)
    return total


def string_pressure_loss(
    string,
    flow_rate_gpm: float,
    model: BinghamPlastic | PowerLaw,
    mud_weight_ppg: float | None = None,
) -> float:
    """Total friction pressure loss inside the drill string, psi.

    Excludes bit nozzle pressure drop -- add that separately with
    :func:`bit_pressure_drop`.
    """
    if isinstance(model, BinghamPlastic) and mud_weight_ppg is None:
        raise ValueError("The Bingham model needs mud_weight_ppg")

    total = 0.0
    for comp in string.components:
        if isinstance(model, BinghamPlastic):
            gradient = model.pipe_gradient_psi_per_ft(
                flow_rate_gpm, comp.id_in, mud_weight_ppg
            )
        else:
            gradient = model.pipe_gradient_psi_per_ft(flow_rate_gpm, comp.id_in)
        total += gradient * comp.length_ft
    return total


def bit_pressure_drop(
    flow_rate_gpm: float,
    mud_weight_ppg: float,
    nozzle_sizes_32nds: list[int],
    discharge_coefficient: float = 0.95,
) -> float:
    """Pressure drop across the bit nozzles, psi.

    Nozzle sizes are in 32nds of an inch, as they are ordered and stamped.

    Note that bit pressure drop is *not* part of the annular pressure that acts
    on the formation -- it is spent inside the bit. It does not contribute to
    ECD, but it is a large part of the standpipe pressure, which is why kill
    rate pressures are so much lower than drilling pressures.
    """
    if not nozzle_sizes_32nds:
        raise ValueError("At least one nozzle is required")
    area = sum(math.pi / 4.0 * (n / 32.0) ** 2 for n in nozzle_sizes_32nds)
    return (
        mud_weight_ppg * flow_rate_gpm ** 2
        / (12042.0 * discharge_coefficient ** 2 * area ** 2)
    )
