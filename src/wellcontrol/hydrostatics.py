"""Hydrostatic pressure: the foundation every other calculation sits on.

Primary well control is the mud column. Everything in this module is an
expression of one equation::

    P = 0.052 x MW x TVD

Note **TVD**, not MD. See :mod:`wellcontrol.survey`.

The three pressures that matter and how they relate:

* **Formation (pore) pressure** -- what the rock is pushing with.
* **Hydrostatic pressure** -- what the mud column is pushing back with.
* **Bottomhole pressure (BHP)** -- the total at the bottom of the hole:
  hydrostatic + any surface pressure + any friction while circulating.

Overbalanced means BHP > formation pressure and the well stays quiet.
Underbalanced means the formation flows and you have a kick.
"""

from __future__ import annotations

from dataclasses import dataclass

from .units import ppg_to_gradient, gradient_to_ppg


# --------------------------------------------------------------------------
# Core relationships
# --------------------------------------------------------------------------

def hydrostatic_pressure(mud_weight_ppg: float, tvd_ft: float, exact: bool = False) -> float:
    """Hydrostatic pressure of a mud column, psi.

    Args:
        mud_weight_ppg: Mud density, ppg.
        tvd_ft: True vertical depth of the column, ft.
        exact: Use the unrounded 1/19.25 constant instead of 0.052.
    """
    if tvd_ft < 0:
        raise ValueError("TVD cannot be negative")
    return ppg_to_gradient(mud_weight_ppg, exact) * tvd_ft


def mud_weight_for_pressure(pressure_psi: float, tvd_ft: float, exact: bool = False) -> float:
    """Mud weight that generates a given pressure at a given TVD, ppg."""
    if tvd_ft <= 0:
        raise ValueError("TVD must be positive")
    k = ppg_to_gradient(1.0, exact)
    return pressure_psi / (k * tvd_ft)


def equivalent_mud_weight(pressure_psi: float, tvd_ft: float, exact: bool = False) -> float:
    """Express any pressure as the mud weight that would produce it, ppg.

    Also written EMW. This is how pressures at different depths are compared
    on a single scale -- a 4,500 psi pore pressure at 9,000 ft and a 6,000 psi
    pore pressure at 12,000 ft are both 9.6 ppg EMW, i.e. the same problem.
    """
    return mud_weight_for_pressure(pressure_psi, tvd_ft, exact)


def pressure_gradient(mud_weight_ppg: float, exact: bool = False) -> float:
    """Pressure gradient of a fluid, psi/ft."""
    return ppg_to_gradient(mud_weight_ppg, exact)


def mud_weight_from_gradient(gradient_psi_per_ft: float, exact: bool = False) -> float:
    """Mud weight from a pressure gradient, ppg."""
    return gradient_to_ppg(gradient_psi_per_ft, exact)


# --------------------------------------------------------------------------
# Balance
# --------------------------------------------------------------------------

def overbalance(
    mud_weight_ppg: float,
    formation_pressure_psi: float,
    tvd_ft: float,
    surface_pressure_psi: float = 0.0,
    exact: bool = False,
) -> float:
    """Overbalance at the formation, psi. Negative means underbalanced."""
    bhp = hydrostatic_pressure(mud_weight_ppg, tvd_ft, exact) + surface_pressure_psi
    return bhp - formation_pressure_psi


def balance_mud_weight(
    formation_pressure_psi: float, tvd_ft: float, exact: bool = False
) -> float:
    """Mud weight that exactly balances formation pressure, ppg.

    This is the *balance point*, not a drilling mud weight. Drilling at exactly
    balanced means any swab, any connection, any drop in ECD puts the well
    underbalanced. Add a trip margin -- see :func:`trip_margin_mud_weight`.
    """
    return mud_weight_for_pressure(formation_pressure_psi, tvd_ft, exact)


def trip_margin_mud_weight(
    formation_pressure_psi: float,
    tvd_ft: float,
    margin_psi: float = 0.0,
    margin_ppg: float = 0.0,
    exact: bool = False,
) -> float:
    """Mud weight giving a stated overbalance for tripping, ppg.

    Supply the margin either as a pressure or as a mud weight increment.
    Typical field practice is 200-300 psi, or 0.2-0.5 ppg.
    """
    base = balance_mud_weight(formation_pressure_psi, tvd_ft, exact)
    extra = mud_weight_for_pressure(margin_psi, tvd_ft, exact) if margin_psi else 0.0
    return base + extra + margin_ppg


# --------------------------------------------------------------------------
# Multi-fluid columns
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class FluidSegment:
    """A vertical slice of a fluid column.

    Attributes:
        density_ppg: Fluid density, ppg. Use ~0.1-0.3 for gas, ~8.5 for salt
            water, ~7 for oil.
        vertical_height_ft: **Vertical** height of the segment, ft. In a
            deviated hole this is not the measured length.
        label: Optional description.
    """

    density_ppg: float
    vertical_height_ft: float
    label: str = ""

    @property
    def pressure_psi(self) -> float:
        return hydrostatic_pressure(self.density_ppg, self.vertical_height_ft)


def column_pressure(
    segments: list[FluidSegment], surface_pressure_psi: float = 0.0
) -> float:
    """Pressure at the bottom of a stacked fluid column, psi.

    Used for the annulus during a kick, where mud sits above an influx of
    different density, and for subsea wells where seawater sits above mud.
    """
    return surface_pressure_psi + sum(s.pressure_psi for s in segments)


def pressure_at_depth(
    segments: list[FluidSegment], tvd_ft: float, surface_pressure_psi: float = 0.0
) -> float:
    """Pressure at an arbitrary TVD within a stacked fluid column, psi.

    Segments are given from surface downward.
    """
    if tvd_ft < 0:
        raise ValueError("TVD cannot be negative")
    pressure = surface_pressure_psi
    remaining = tvd_ft
    for seg in segments:
        if remaining <= 0:
            break
        height = min(seg.vertical_height_ft, remaining)
        pressure += hydrostatic_pressure(seg.density_ppg, height)
        remaining -= height
    if remaining > 1e-6:
        raise ValueError(
            f"TVD {tvd_ft} ft is below the bottom of the defined fluid column"
        )
    return pressure


# --------------------------------------------------------------------------
# Circulating density
# --------------------------------------------------------------------------

def equivalent_circulating_density(
    mud_weight_ppg: float,
    annular_pressure_loss_psi: float,
    tvd_ft: float,
    surface_backpressure_psi: float = 0.0,
    exact: bool = False,
) -> float:
    """Equivalent circulating density, ppg.

    While circulating, the mud returning up the annulus has to be pushed
    against friction, and that friction shows up as extra pressure on the
    bottom of the hole::

        ECD = MW + APL / (0.052 x TVD)

    ECD is why a well can be stable while circulating and start flowing the
    moment the pumps are shut down: stopping the pumps removes the friction
    term. It is also why a well can be static and start losing returns when
    the pumps come on.

    ``surface_backpressure_psi`` covers MPD operations where the choke is
    deliberately holding pressure at surface.
    """
    if tvd_ft <= 0:
        raise ValueError("TVD must be positive")
    k = ppg_to_gradient(1.0, exact)
    return mud_weight_ppg + (annular_pressure_loss_psi + surface_backpressure_psi) / (k * tvd_ft)


def equivalent_static_density(
    segments: list[FluidSegment], tvd_ft: float, surface_pressure_psi: float = 0.0
) -> float:
    """Equivalent static density of a layered column, ppg.

    The single mud weight that would give the same bottomhole pressure as the
    actual stack of fluids. Relevant with a slug in the hole, after a kill when
    the well holds two mud weights, or in HPHT wells where density varies with
    depth.
    """
    return equivalent_mud_weight(column_pressure(segments, surface_pressure_psi), tvd_ft)


# --------------------------------------------------------------------------
# Tripping
# --------------------------------------------------------------------------

def fill_volume_for_pipe_pulled(
    displacement_bbl_per_ft: float, length_pulled_ft: float
) -> float:
    """Mud needed to keep the hole full while pulling pipe, bbl.

    Use the **steel** displacement for open-ended pipe, and the **closed-end**
    displacement when pulling on a float. Comparing what the hole actually took
    against this figure is the primary kick indicator while tripping.
    """
    return displacement_bbl_per_ft * length_pulled_ft


def hydrostatic_drop_from_not_filling(
    displacement_bbl_per_ft: float,
    length_pulled_ft: float,
    annular_capacity_bbl_per_ft: float,
    mud_weight_ppg: float,
    exact: bool = False,
) -> tuple[float, float]:
    """Effect of pulling pipe without filling the hole.

    Returns ``(level_drop_ft, pressure_loss_psi)``.

    Every foot the mud level falls is hydrostatic pressure removed from the
    bottom of the hole. Pull enough stands dry without filling and the well
    goes underbalanced with no other warning.
    """
    if annular_capacity_bbl_per_ft <= 0:
        raise ValueError("Annular capacity must be positive")
    volume_removed = displacement_bbl_per_ft * length_pulled_ft
    level_drop = volume_removed / annular_capacity_bbl_per_ft
    return level_drop, hydrostatic_pressure(mud_weight_ppg, level_drop, exact)


def slug_volume_for_dry_pipe(
    dry_length_ft: float,
    pipe_capacity_bbl_per_ft: float,
    mud_weight_ppg: float,
    slug_weight_ppg: float,
) -> float:
    """Slug volume needed to pull a given length of dry pipe, bbl.

    A heavy slug pumped into the string before a trip pushes the level inside
    the pipe down, so the stands come out empty instead of dumping mud on the
    floor. The balance is::

        0.052 x (SW - MW) x slug length in pipe  =  0.052 x MW x dry length
    """
    if slug_weight_ppg <= mud_weight_ppg:
        raise ValueError("Slug must be heavier than the mud in the hole")
    return (
        dry_length_ft * pipe_capacity_bbl_per_ft * mud_weight_ppg
        / (slug_weight_ppg - mud_weight_ppg)
    )


def dry_pipe_length_from_slug(
    slug_volume_bbl: float,
    pipe_capacity_bbl_per_ft: float,
    mud_weight_ppg: float,
    slug_weight_ppg: float,
) -> float:
    """Length of pipe that will come out dry for a given slug, ft."""
    if slug_weight_ppg <= mud_weight_ppg:
        raise ValueError("Slug must be heavier than the mud in the hole")
    if pipe_capacity_bbl_per_ft <= 0:
        raise ValueError("Pipe capacity must be positive")
    return (
        slug_volume_bbl * (slug_weight_ppg - mud_weight_ppg)
        / (pipe_capacity_bbl_per_ft * mud_weight_ppg)
    )
