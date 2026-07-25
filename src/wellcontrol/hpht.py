"""HPHT wells: mud density is not constant.

Everywhere else in this package mud weight is treated as a fixed number. In a
high pressure, high temperature well that assumption breaks down, and it breaks
down in two directions at once:

* **Pressure compresses the mud**, making it denser with depth. At 15,000 psi
  an oil-based mud can be 3-5% heavier than it was in the pit.
* **Temperature expands it**, making it lighter with depth. At 350 degF the
  same mud can be 5-8% lighter.

The two effects partly cancel, which is exactly what makes them dangerous --
it is tempting to ignore both. They do not cancel evenly: compression dominates
in the deep, cool part of a well and expansion dominates in the hot part, and
the net error in bottomhole pressure can run to hundreds of psi in either
direction. In a well whose drilling window is 0.5 ppg wide, that is the whole
window.

Oil-based muds are far more sensitive than water-based to both effects, because
the base oil is more compressible and more thermally expansive than water.

The model here is the standard linear one::

    rho(P,T) = rho_ref x [1 + C_p x (P - P_ref) - C_t x (T - T_ref)]

It is adequate for planning. For a real HPHT well, use PVT data measured on the
actual mud -- the coefficients vary substantially between mud systems, and a
correlation is no substitute for a lab report.
"""

from __future__ import annotations

from dataclasses import dataclass

from .units import PSI_PER_PPG_FT


# --------------------------------------------------------------------------
# Temperature
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class TemperatureProfile:
    """A linear geothermal temperature profile.

    Attributes:
        surface_temp_f: Temperature at surface (or at the mudline for a subsea
            well, which is typically 35-40 degF regardless of latitude).
        gradient_f_per_100ft: Geothermal gradient. 1.0-1.6 degF/100 ft is
            typical; HPHT basins run higher.
        datum_tvd_ft: TVD at which ``surface_temp_f`` applies. Use the mudline
            TVD for a subsea well.
    """

    surface_temp_f: float
    gradient_f_per_100ft: float
    datum_tvd_ft: float = 0.0

    def temperature_at(self, tvd_ft: float) -> float:
        """Static formation temperature at a TVD, degF."""
        depth_below_datum = max(0.0, tvd_ft - self.datum_tvd_ft)
        return self.surface_temp_f + self.gradient_f_per_100ft * depth_below_datum / 100.0

    @classmethod
    def from_bottomhole(
        cls, surface_temp_f: float, bottomhole_temp_f: float, tvd_ft: float
    ) -> "TemperatureProfile":
        """Fit a profile to a measured bottomhole temperature."""
        if tvd_ft <= 0:
            raise ValueError("TVD must be positive")
        gradient = (bottomhole_temp_f - surface_temp_f) / tvd_ft * 100.0
        return cls(surface_temp_f=surface_temp_f, gradient_f_per_100ft=gradient)


# --------------------------------------------------------------------------
# Mud PVT behaviour
# --------------------------------------------------------------------------

#: Representative coefficients. Replace with measured PVT data for real work.
TYPICAL_COEFFICIENTS: dict[str, tuple[float, float]] = {
    # name: (compressibility 1/psi, thermal expansion 1/degF)
    "water_based": (2.7e-6, 1.7e-4),
    "oil_based": (3.5e-6, 2.6e-4),
    "synthetic_based": (3.2e-6, 2.4e-4),
}


@dataclass(frozen=True)
class MudPVT:
    """Pressure and temperature behaviour of a mud.

    Attributes:
        surface_density_ppg: Density measured at the reference conditions.
        compressibility_per_psi: Fractional density increase per psi.
        thermal_expansion_per_f: Fractional density decrease per degF.
        reference_pressure_psi: Pressure at which the surface density applies.
        reference_temp_f: Temperature at which the surface density applies.
    """

    surface_density_ppg: float
    compressibility_per_psi: float = 3.5e-6
    thermal_expansion_per_f: float = 2.6e-4
    reference_pressure_psi: float = 14.7
    reference_temp_f: float = 70.0

    @classmethod
    def typical(
        cls, surface_density_ppg: float, mud_type: str = "oil_based", **kwargs
    ) -> "MudPVT":
        """Build from representative coefficients for a mud type.

        ``mud_type`` is one of ``water_based``, ``oil_based`` or
        ``synthetic_based``.
        """
        if mud_type not in TYPICAL_COEFFICIENTS:
            raise ValueError(
                f"Unknown mud type '{mud_type}'. Choose from "
                f"{sorted(TYPICAL_COEFFICIENTS)}."
            )
        compressibility, expansion = TYPICAL_COEFFICIENTS[mud_type]
        return cls(
            surface_density_ppg=surface_density_ppg,
            compressibility_per_psi=compressibility,
            thermal_expansion_per_f=expansion,
            **kwargs,
        )

    def density_at(self, pressure_psi: float, temperature_f: float) -> float:
        """Mud density at downhole conditions, ppg."""
        factor = (
            1.0
            + self.compressibility_per_psi * (pressure_psi - self.reference_pressure_psi)
            - self.thermal_expansion_per_f * (temperature_f - self.reference_temp_f)
        )
        if factor <= 0:
            raise ValueError(
                "The density model has gone non-physical at "
                f"{pressure_psi:.0f} psi and {temperature_f:.0f} degF. Check the "
                "coefficients."
            )
        return self.surface_density_ppg * factor


# --------------------------------------------------------------------------
# Integrated column
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class DensityStep:
    """One depth step of an integrated pressure/density profile."""

    tvd_ft: float
    pressure_psi: float
    temperature_f: float
    density_ppg: float


def integrate_column(
    mud: MudPVT,
    temperature: TemperatureProfile,
    total_tvd_ft: float,
    surface_pressure_psi: float = 0.0,
    step_ft: float = 250.0,
    top_tvd_ft: float = 0.0,
) -> list[DensityStep]:
    """March down the well computing pressure and density together, psi/ppg.

    Density depends on pressure and pressure depends on density, so each step
    is solved with a short fixed-point iteration on the mid-point conditions.
    Returns one :class:`DensityStep` per depth node, starting at ``top_tvd_ft``.
    """
    if total_tvd_ft <= top_tvd_ft:
        raise ValueError("Total TVD must be below the top of the column")
    if step_ft <= 0:
        raise ValueError("Step must be positive")

    depth = top_tvd_ft
    pressure = surface_pressure_psi
    temp = temperature.temperature_at(depth)
    steps = [
        DensityStep(depth, pressure, temp, mud.density_at(max(pressure, 0.0), temp))
    ]

    while depth < total_tvd_ft - 1e-9:
        interval = min(step_ft, total_tvd_ft - depth)
        mid_depth = depth + interval / 2.0
        mid_temp = temperature.temperature_at(mid_depth)

        # Fixed-point: guess the mid-interval pressure, get a density, use it
        # to refine the pressure. Converges in two or three passes.
        mid_pressure = pressure
        density = mud.density_at(max(mid_pressure, 0.0), mid_temp)
        for _ in range(4):
            mid_pressure = pressure + PSI_PER_PPG_FT * density * interval / 2.0
            density = mud.density_at(max(mid_pressure, 0.0), mid_temp)

        pressure += PSI_PER_PPG_FT * density * interval
        depth += interval
        steps.append(
            DensityStep(depth, pressure, temperature.temperature_at(depth), density)
        )

    return steps


def bottomhole_pressure(
    mud: MudPVT,
    temperature: TemperatureProfile,
    total_tvd_ft: float,
    surface_pressure_psi: float = 0.0,
    step_ft: float = 250.0,
) -> float:
    """Bottomhole pressure accounting for PVT effects, psi."""
    return integrate_column(
        mud, temperature, total_tvd_ft, surface_pressure_psi, step_ft
    )[-1].pressure_psi


def equivalent_static_density(
    mud: MudPVT,
    temperature: TemperatureProfile,
    total_tvd_ft: float,
    surface_pressure_psi: float = 0.0,
    step_ft: float = 250.0,
) -> float:
    """Equivalent static density of a PVT-corrected column, ppg.

    The single mud weight that would give the same bottomhole pressure. This is
    what should be compared against pore pressure and fracture gradient -- not
    the density measured in the pit.
    """
    pressure = bottomhole_pressure(
        mud, temperature, total_tvd_ft, surface_pressure_psi, step_ft
    )
    return pressure / (PSI_PER_PPG_FT * total_tvd_ft)


def pvt_error_psi(
    mud: MudPVT,
    temperature: TemperatureProfile,
    total_tvd_ft: float,
    step_ft: float = 250.0,
) -> float:
    """Error from assuming constant density, psi.

    Positive means the simple ``0.052 x MW x TVD`` calculation **under**
    estimates bottomhole pressure -- compression is winning, and the well has
    more overbalance than the kill sheet says. Negative means it over-estimates
    -- expansion is winning, the real bottomhole pressure is lower than
    believed, and the well is closer to flowing than it appears.

    The second case is the one that kills people.
    """
    corrected = bottomhole_pressure(mud, temperature, total_tvd_ft, 0.0, step_ft)
    naive = PSI_PER_PPG_FT * mud.surface_density_ppg * total_tvd_ft
    return corrected - naive
