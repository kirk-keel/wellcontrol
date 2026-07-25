"""Kick detection and shut-in analysis.

Once a well is shut in you have three measured numbers -- SIDPP, SICP and pit
gain -- and from them you can work out everything about the influx: what the
formation pressure is, how tall the influx is, and what it is made of.

The two shut-in pressures both read the same bottomhole pressure by two
different routes:

* **SIDPP** (drill pipe side) reads through clean mud of known weight, so it is
  a clean measurement of how far underbalanced the mud was.
* **SICP** (annulus side) reads through mud *plus* the influx. Because the
  influx is lighter than mud, it contributes less hydrostatic, so SICP is
  higher than SIDPP. That difference is what identifies the influx.

**SICP is always the higher of the two.** If it is not, something is wrong --
plugged nozzle, float in the string, gas already up the drill pipe, or the
gauge. Do not proceed on numbers that fail that check.
"""

from __future__ import annotations

from dataclasses import dataclass

from .geometry import Annulus
from .hydrostatics import hydrostatic_pressure, pressure_gradient
from .survey import Survey
from .units import PSI_PER_PPG_FT, f_to_rankine, psi_to_psia


# --------------------------------------------------------------------------
# Influx classification
# --------------------------------------------------------------------------

def classify_influx(density_ppg: float) -> str:
    """Name the influx from its density.

    Rough field bands. Treat anything at or below ~4 ppg as gas and plan for
    expansion -- the consequences of mistaking gas for water are much worse
    than the reverse.
    """
    if density_ppg < 0:
        return "invalid (negative density)"
    if density_ppg <= 4.0:
        return "gas"
    if density_ppg <= 7.0:
        return "oil or mixed gas/liquid"
    if density_ppg <= 9.5:
        return "salt water"
    return "unexpectedly heavy - re-check the readings"


# --------------------------------------------------------------------------
# Shut-in analysis
# --------------------------------------------------------------------------

@dataclass
class ShutInAnalysis:
    """Full analysis of a shut-in well from the three measured numbers.

    Args:
        sidpp_psi: Shut-in drill pipe pressure.
        sicp_psi: Shut-in casing pressure.
        pit_gain_bbl: Volume gained in the pits -- the influx volume.
        mud_weight_ppg: Original mud weight in the hole.
        annulus: Wellbore/string geometry.
        survey: Directional survey, for MD/TVD conversion.
    """

    sidpp_psi: float
    sicp_psi: float
    pit_gain_bbl: float
    mud_weight_ppg: float
    annulus: Annulus
    survey: Survey

    def __post_init__(self) -> None:
        if self.pit_gain_bbl < 0:
            raise ValueError("Pit gain cannot be negative")
        if self.sidpp_psi < 0 or self.sicp_psi < 0:
            raise ValueError("Shut-in pressures cannot be negative")

    # -- depths --------------------------------------------------------------

    @property
    def bit_tvd_ft(self) -> float:
        return self.survey.tvd_at(self.annulus.string.bit_depth_md)

    @property
    def hole_tvd_ft(self) -> float:
        return self.survey.tvd_at(self.annulus.wellbore.total_depth_md)

    # -- pressures -----------------------------------------------------------

    @property
    def formation_pressure_psi(self) -> float:
        """Formation pore pressure, psi.

        Read up the drill pipe, which contains clean mud of known density::

            Pf = SIDPP + 0.052 x MW x TVD
        """
        return self.sidpp_psi + hydrostatic_pressure(self.mud_weight_ppg, self.bit_tvd_ft)

    @property
    def formation_pressure_emw_ppg(self) -> float:
        """Formation pressure expressed as an equivalent mud weight, ppg."""
        return self.formation_pressure_psi / (PSI_PER_PPG_FT * self.bit_tvd_ft)

    @property
    def underbalance_psi(self) -> float:
        """How far underbalanced the well was. Equal to SIDPP by definition."""
        return self.sidpp_psi

    # -- influx geometry -----------------------------------------------------

    @property
    def influx_height_md_ft(self) -> float:
        """Measured length of the influx in the annulus, ft.

        Filled from total depth upward through each annular interval, so the
        capacity change at the top of the collars is honoured.
        """
        return self.annulus.height_of_volume_from_bottom(self.pit_gain_bbl)

    @property
    def influx_top_md_ft(self) -> float:
        """MD of the top of the influx, ft."""
        return self.annulus.wellbore.total_depth_md - self.influx_height_md_ft

    @property
    def influx_height_tvd_ft(self) -> float:
        """**Vertical** height of the influx, ft.

        This is the number that matters for pressure. In a horizontal lateral
        it can be near zero even for a large influx, which has two
        consequences: the influx barely changes SICP, and it cannot migrate.
        """
        return self.survey.vertical_height_of(
            self.influx_top_md_ft, self.annulus.wellbore.total_depth_md
        )

    # -- influx identity -----------------------------------------------------

    @property
    def influx_gradient_psi_per_ft(self) -> float:
        """Pressure gradient of the influx, psi/ft.

        Derived from the difference between the two shut-in pressures::

            influx gradient = 0.052 x MW - (SICP - SIDPP) / influx height (TVD)
        """
        height = self.influx_height_tvd_ft
        if height < 1.0:
            raise ValueError(
                "The influx has essentially no vertical height "
                f"({height:.2f} ft), so its density cannot be resolved from the "
                "shut-in pressures. This is normal for an influx sitting in a "
                "horizontal lateral -- identify the influx from returns at the "
                "gas trap instead."
            )
        return pressure_gradient(self.mud_weight_ppg) - (
            self.sicp_psi - self.sidpp_psi
        ) / height

    @property
    def influx_density_ppg(self) -> float:
        """Density of the influx, ppg."""
        return self.influx_gradient_psi_per_ft / PSI_PER_PPG_FT

    @property
    def influx_type(self) -> str:
        """Best guess at what came in."""
        try:
            return classify_influx(self.influx_density_ppg)
        except ValueError:
            return "indeterminate (no vertical height)"

    @property
    def spans_annular_geometry_change(self) -> bool:
        """Whether the influx straddles a change in annular capacity.

        An influx tall enough to reach past the top of the BHA occupies two
        different annular capacities at once. That is normal and not an error,
        but it means the influx height came from filling two sections rather
        than one, and the simple single-capacity arithmetic on a paper kill
        sheet would have got it wrong.
        """
        top = self.influx_top_md_ft
        for interval in self.annulus.intervals:
            if interval.top_md < self.annulus.wellbore.total_depth_md - 1e-9:
                if top < interval.top_md - 1e-9:
                    return True
        return False

    # -- sanity --------------------------------------------------------------

    def validate(self) -> list[str]:
        """Check the readings for physical consistency.

        Returns a list of warnings. An empty list means the numbers hang
        together. This is worth running before any kill sheet is filled in.
        """
        warnings: list[str] = []

        if self.sicp_psi < self.sidpp_psi:
            warnings.append(
                f"SICP ({self.sicp_psi:.0f} psi) is below SIDPP "
                f"({self.sidpp_psi:.0f} psi). The influx is lighter than mud, so "
                "casing pressure should be the higher of the two. Suspect a "
                "plugged bit nozzle, a float in the string, gas up the drill "
                "pipe, or a bad gauge."
            )

        if self.pit_gain_bbl == 0 and (self.sidpp_psi > 0 or self.sicp_psi > 0):
            warnings.append(
                "Shut-in pressure with no pit gain. This can be trapped pump "
                "pressure rather than a kick -- bleed a small volume and see "
                "whether the pressure returns."
            )

        try:
            density = self.influx_density_ppg
        except ValueError as exc:
            warnings.append(str(exc))
        else:
            if density < 0:
                warnings.append(
                    f"Computed influx density is negative ({density:.2f} ppg), "
                    "which is not physical. The influx height is probably "
                    "under-estimated -- check the pit gain and the annular "
                    "capacities."
                )
            elif density > self.mud_weight_ppg:
                warnings.append(
                    f"Computed influx density ({density:.2f} ppg) is heavier than "
                    f"the mud ({self.mud_weight_ppg:.2f} ppg). Re-check the "
                    "readings; an influx heavier than the mud would not have "
                    "raised the casing pressure above the drill pipe pressure."
                )

        return warnings

    def summary(self) -> dict[str, float | str]:
        """Everything the shut-in readings tell you, as a dict."""
        out: dict[str, float | str] = {
            "SIDPP (psi)": round(self.sidpp_psi, 1),
            "SICP (psi)": round(self.sicp_psi, 1),
            "Pit gain (bbl)": round(self.pit_gain_bbl, 2),
            "Mud weight (ppg)": round(self.mud_weight_ppg, 2),
            "Bit TVD (ft)": round(self.bit_tvd_ft, 1),
            "Formation pressure (psi)": round(self.formation_pressure_psi, 1),
            "Formation pressure (ppg EMW)": round(self.formation_pressure_emw_ppg, 2),
            "Influx height, measured (ft)": round(self.influx_height_md_ft, 1),
            "Influx height, vertical (ft)": round(self.influx_height_tvd_ft, 1),
            "Influx top (ft MD)": round(self.influx_top_md_ft, 1),
        }
        try:
            out["Influx density (ppg)"] = round(self.influx_density_ppg, 2)
            out["Influx gradient (psi/ft)"] = round(self.influx_gradient_psi_per_ft, 4)
        except ValueError:
            out["Influx density (ppg)"] = "indeterminate"
            out["Influx gradient (psi/ft)"] = "indeterminate"
        out["Influx type"] = self.influx_type
        out["Spans an annular capacity change"] = (
            "yes" if self.spans_annular_geometry_change else "no"
        )
        return out


# --------------------------------------------------------------------------
# Gas behaviour
# --------------------------------------------------------------------------

def gas_migration_rate_ft_per_hr(
    pressure_rise_psi_per_hr: float, mud_weight_ppg: float
) -> float:
    """Gas migration rate from the rate of shut-in pressure rise, ft/hr.

    A gas bubble that migrates without being allowed to expand carries its
    original pressure up the hole with it, so surface pressure rises by the
    hydrostatic it leaves behind::

        migration rate = pressure rise per hour / (0.052 x MW)

    Typical rates are 1,000-2,000 ft/hr in water-based mud, and much slower in
    oil-based mud where gas goes into solution instead. If shut-in pressures
    are climbing steadily, gas is migrating and the well needs attention before
    surface pressure reaches the limit at the shoe.
    """
    return pressure_rise_psi_per_hr / (PSI_PER_PPG_FT * mud_weight_ppg)


def gas_expansion_boyle(
    p1_psig: float,
    v1_bbl: float,
    p2_psig: float,
    t1_f: float | None = None,
    t2_f: float | None = None,
    z1: float = 1.0,
    z2: float = 1.0,
) -> float:
    """Volume of a gas bubble after a pressure change, bbl.

    Boyle's law with optional temperature and compressibility terms::

        P1 V1 / (Z1 T1) = P2 V2 / (Z2 T2)

    Pressures are converted to absolute internally -- this is the step most
    often skipped, and near surface it matters enormously: a bubble going from
    100 psig to 0 psig does not stay the same size, it roughly octuples.

    Omit the temperatures for the isothermal case. Real gas kicks also cool as
    they expand and gas is not ideal, so ``z`` factors are available; leaving
    them at 1.0 is conservative for kick tolerance work because it slightly
    over-estimates expansion at depth.
    """
    if p2_psig <= -14.7:
        raise ValueError("Absolute pressure must stay positive")
    p1 = psi_to_psia(p1_psig)
    p2 = psi_to_psia(p2_psig)
    ratio = (p1 * v1_bbl) / p2
    if t1_f is not None and t2_f is not None:
        ratio *= f_to_rankine(t2_f) / f_to_rankine(t1_f)
    return ratio * (z2 / z1)


def pressure_after_expansion(
    p1_psig: float, v1_bbl: float, v2_bbl: float
) -> float:
    """Gas pressure after expanding to a new volume, psig (isothermal)."""
    if v2_bbl <= 0:
        raise ValueError("Volume must be positive")
    return psi_to_psia(p1_psig) * v1_bbl / v2_bbl - 14.7


# --------------------------------------------------------------------------
# Warning signs, for reference
# --------------------------------------------------------------------------

#: Kick indicators while drilling, roughly in the order they usually appear.
DRILLING_KICK_INDICATORS: tuple[str, ...] = (
    "Drilling break -- a sudden increase in rate of penetration",
    "Increase in flow rate out with the pump rate unchanged",
    "Increase in pit volume",
    "Pump pressure drop with a pump stroke increase",
    "Change in cuttings size/shape, or gas-cut mud",
    "Increase in hookload as the mud density in the annulus falls",
    "Well flowing with the pumps off (positive confirmation -- flow check)",
)

#: Kick indicators while tripping.
TRIPPING_KICK_INDICATORS: tuple[str, ...] = (
    "Hole not taking the calculated fill volume when pulling out",
    "Hole giving back more than the calculated volume when running in",
    "Well flowing with the string static (flow check)",
)
