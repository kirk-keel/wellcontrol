"""Managed pressure drilling and underbalanced drilling.

Conventional drilling controls bottomhole pressure with one lever: mud weight.
That lever is coarse and slow, and it swings every time the pumps start or stop
because ECD appears and disappears with them.

MPD closes the annulus with a rotating control device and adds a second, fast
lever: **surface backpressure** applied through a choke::

    BHP = hydrostatic + annular friction + surface backpressure

The value of that second lever is that it can be adjusted in seconds. The
classic use is the connection. Conventionally, stopping the pumps drops
bottomhole pressure by the whole annular friction loss, and in a narrow window
that alone can bring the well in. Under MPD the choke closes as the pumps come
down, replacing friction with backpressure and holding bottomhole pressure
constant through the connection. This is Constant Bottomhole Pressure MPD, the
most widely used variant.

**MPD is not underbalanced drilling.** MPD holds the well overbalanced and uses
pressure control to keep it there precisely; influx is unwanted and is
circulated out. UBD deliberately drills underbalanced and produces the well
while drilling, with equipment to handle continuous flow at surface. They share
hardware and share almost none of their risk profile.

A well being drilled with MPD still needs a conventional well control plan.
The RCD and choke manifold are a drilling tool with limited pressure rating;
the BOP stack remains the barrier.
"""

from __future__ import annotations

from dataclasses import dataclass

from .hydrostatics import hydrostatic_pressure
from .units import PSI_PER_PPG_FT


# --------------------------------------------------------------------------
# Core pressure balance
# --------------------------------------------------------------------------

def bottomhole_pressure(
    mud_weight_ppg: float,
    tvd_ft: float,
    annular_friction_psi: float = 0.0,
    surface_backpressure_psi: float = 0.0,
) -> float:
    """Bottomhole pressure under MPD, psi.

    ``annular_friction_psi`` is zero when the pumps are off.
    """
    return (
        hydrostatic_pressure(mud_weight_ppg, tvd_ft)
        + annular_friction_psi
        + surface_backpressure_psi
    )


def required_backpressure(
    target_bhp_psi: float,
    mud_weight_ppg: float,
    tvd_ft: float,
    annular_friction_psi: float = 0.0,
) -> float:
    """Surface backpressure needed to hit a target bottomhole pressure, psi.

    A negative result means the mud alone already exceeds the target -- the
    choke cannot pull pressure *off* the well, so the mud weight has to come
    down instead.
    """
    return (
        target_bhp_psi
        - hydrostatic_pressure(mud_weight_ppg, tvd_ft)
        - annular_friction_psi
    )


def equivalent_mud_weight(
    mud_weight_ppg: float,
    tvd_ft: float,
    annular_friction_psi: float = 0.0,
    surface_backpressure_psi: float = 0.0,
) -> float:
    """The whole MPD pressure picture expressed as a mud weight, ppg."""
    if tvd_ft <= 0:
        raise ValueError("TVD must be positive")
    bhp = bottomhole_pressure(
        mud_weight_ppg, tvd_ft, annular_friction_psi, surface_backpressure_psi
    )
    return bhp / (PSI_PER_PPG_FT * tvd_ft)


# --------------------------------------------------------------------------
# Drilling window
# --------------------------------------------------------------------------

@dataclass
class DrillingWindow:
    """The operating envelope at a depth: pore pressure to fracture pressure.

    Attributes:
        pore_pressure_ppg: Pore pressure, ppg EMW.
        frac_gradient_ppg: Fracture gradient, ppg EMW.
        tvd_ft: Depth the window applies at, TVD.
        safety_margin_ppg: Margin held off each limit.
    """

    pore_pressure_ppg: float
    frac_gradient_ppg: float
    tvd_ft: float
    safety_margin_ppg: float = 0.0

    def __post_init__(self) -> None:
        if self.frac_gradient_ppg <= self.pore_pressure_ppg:
            raise ValueError(
                f"Fracture gradient ({self.frac_gradient_ppg:.2f} ppg) is not "
                f"above pore pressure ({self.pore_pressure_ppg:.2f} ppg). There "
                "is no window here at all."
            )

    @property
    def width_ppg(self) -> float:
        """Usable window width after safety margins, ppg."""
        return (
            self.frac_gradient_ppg
            - self.pore_pressure_ppg
            - 2 * self.safety_margin_ppg
        )

    @property
    def width_psi(self) -> float:
        return PSI_PER_PPG_FT * self.width_ppg * self.tvd_ft

    @property
    def lower_limit_ppg(self) -> float:
        return self.pore_pressure_ppg + self.safety_margin_ppg

    @property
    def upper_limit_ppg(self) -> float:
        return self.frac_gradient_ppg - self.safety_margin_ppg

    @property
    def min_bhp_psi(self) -> float:
        return PSI_PER_PPG_FT * self.lower_limit_ppg * self.tvd_ft

    @property
    def max_bhp_psi(self) -> float:
        return PSI_PER_PPG_FT * self.upper_limit_ppg * self.tvd_ft

    def is_within(self, bhp_psi: float) -> bool:
        return self.min_bhp_psi <= bhp_psi <= self.max_bhp_psi

    def needs_mpd(self, annular_friction_psi: float) -> bool:
        """Whether the window is too narrow to absorb the ECD swing.

        If the annular friction that appears and disappears with the pumps is
        wider than the whole window, then no single mud weight can be safe both
        circulating and static. That is the textbook case for MPD.
        """
        return annular_friction_psi > self.width_psi


# --------------------------------------------------------------------------
# Constant bottomhole pressure through a connection
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class ConnectionStep:
    """One point in a pump ramp, with the backpressure needed to hold BHP."""

    pump_fraction: float
    flow_rate_gpm: float
    annular_friction_psi: float
    surface_backpressure_psi: float
    bottomhole_pressure_psi: float


def connection_schedule(
    target_bhp_psi: float,
    mud_weight_ppg: float,
    tvd_ft: float,
    full_rate_gpm: float,
    full_rate_friction_psi: float,
    steps: int = 5,
) -> list[ConnectionStep]:
    """Backpressure schedule for ramping the pumps down and back up.

    As the pumps come down, annular friction falls roughly with the square of
    the flow rate. The choke has to make up the difference so that bottomhole
    pressure never moves::

        SBP = target BHP - hydrostatic - friction(rate)

    Returns the schedule from full rate down to pumps off. Reverse it for
    coming back up.
    """
    if steps < 1:
        raise ValueError("Need at least one step")

    out: list[ConnectionStep] = []
    for i in range(steps + 1):
        fraction = 1.0 - i / steps
        rate = full_rate_gpm * fraction
        friction = full_rate_friction_psi * fraction ** 2
        backpressure = required_backpressure(
            target_bhp_psi, mud_weight_ppg, tvd_ft, friction
        )
        out.append(
            ConnectionStep(
                pump_fraction=fraction,
                flow_rate_gpm=rate,
                annular_friction_psi=friction,
                surface_backpressure_psi=backpressure,
                bottomhole_pressure_psi=bottomhole_pressure(
                    mud_weight_ppg, tvd_ft, friction, backpressure
                ),
            )
        )
    return out


def max_backpressure_check(
    schedule: list[ConnectionStep], rcd_rating_psi: float
) -> list[str]:
    """Check a connection schedule against the RCD pressure rating.

    Returns warnings; an empty list means the schedule stays within rating.
    """
    warnings: list[str] = []
    peak = max(s.surface_backpressure_psi for s in schedule)
    if peak > rcd_rating_psi:
        warnings.append(
            f"Peak backpressure {peak:.0f} psi exceeds the RCD rating of "
            f"{rcd_rating_psi:.0f} psi. The mud weight must come up so less "
            "backpressure is needed, or the connection cannot be made this way."
        )
    if any(s.surface_backpressure_psi < 0 for s in schedule):
        warnings.append(
            "The schedule calls for negative backpressure at some point, which "
            "a choke cannot deliver. The mud is already too heavy for the "
            "target at that rate."
        )
    return warnings


# --------------------------------------------------------------------------
# Underbalanced drilling
# --------------------------------------------------------------------------

def underbalance_psi(
    pore_pressure_psi: float,
    mud_weight_ppg: float,
    tvd_ft: float,
    annular_friction_psi: float = 0.0,
    surface_backpressure_psi: float = 0.0,
) -> float:
    """Degree of underbalance, psi. Positive means the well will flow.

    In UBD this is the design target, not a failure -- it is what produces the
    reservoir while drilling and avoids formation damage. It has to be
    maintained within a band: too little and the well stops producing and may
    take damage, too much and the surface separation package is overwhelmed.
    """
    bhp = bottomhole_pressure(
        mud_weight_ppg, tvd_ft, annular_friction_psi, surface_backpressure_psi
    )
    return pore_pressure_psi - bhp


def lightened_fluid_density(
    base_fluid_ppg: float, gas_fraction: float, gas_density_ppg: float = 0.1
) -> float:
    """Density of a gas-lightened drilling fluid, ppg.

    UBD reaches bottomhole pressures below pore pressure by injecting nitrogen
    or air into the mud. A simple volume-weighted mixture::

        rho_mix = (1 - x) x rho_fluid + x x rho_gas

    ``gas_fraction`` is the downhole gas volume fraction, which is far smaller
    than the surface injection ratio because the gas is compressed. A full UBD
    design needs multiphase flow modelling; this is a first estimate only.
    """
    if not 0.0 <= gas_fraction < 1.0:
        raise ValueError("Gas fraction must be between 0 and 1")
    return (1.0 - gas_fraction) * base_fluid_ppg + gas_fraction * gas_density_ppg
