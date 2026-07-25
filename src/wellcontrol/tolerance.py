"""Formation strength, MAASP and kick tolerance.

A well has two limits. Below, the formation pressure sets how heavy the mud has
to be. Above, the fracture pressure at the casing shoe sets how heavy it can
get before the well breaks down and starts losing mud. The gap between them is
the drilling window, and everything in well control happens inside it.

The shoe is the weak point because it is the shallowest exposed formation --
shallow rock is weaker, and during a kill the pressure applied at surface adds
to the pressure everywhere below it. An underground blowout, where the well
breaks down at the shoe and flows from the kicking formation into the shoe
formation, is a far worse problem than the kick that caused it.

**Kick tolerance** answers: how big a kick can this well survive? It is not one
number but a trade-off between kick *intensity* (how underbalanced the mud is)
and kick *volume* (how much came in). Both are checked before drilling ahead.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import rounding
from .units import PSI_PER_PPG_FT, psi_to_psia


# --------------------------------------------------------------------------
# Formation strength from pressure tests
# --------------------------------------------------------------------------

def frac_gradient_from_leak_off(
    test_mud_weight_ppg: float, leak_off_pressure_psi: float, shoe_tvd_ft: float
) -> float:
    """Fracture gradient from a leak-off test, ppg EMW.

    A leak-off test pumps against a closed well until the formation below the
    shoe starts to take fluid. The surface pressure at that point, converted to
    a mud weight and added to the mud in the hole, is the formation's strength::

        FG = MW_test + LOT / (0.052 x TVD_shoe)

    A formation integrity test (FIT) stops at a predetermined pressure without
    breaking down, so it gives a *lower bound* on strength, not the strength
    itself. Feeding an FIT into this function tells you the well is at least
    that strong.
    """
    if shoe_tvd_ft <= 0:
        raise ValueError("Shoe TVD must be positive")
    return test_mud_weight_ppg + leak_off_pressure_psi / (PSI_PER_PPG_FT * shoe_tvd_ft)


def frac_pressure_at_shoe(frac_gradient_ppg: float, shoe_tvd_ft: float) -> float:
    """Absolute fracture pressure at the shoe, psi."""
    return PSI_PER_PPG_FT * frac_gradient_ppg * shoe_tvd_ft


def max_allowable_mud_weight(frac_gradient_ppg: float) -> float:
    """Maximum Allowable Mud Weight at the shoe, ppg.

    The fracture gradient expressed as the heaviest mud the shoe will stand,
    **rounded down to the nearest tenth**. A fracture gradient of 12.87 ppg
    gives an MAMW of 12.8, not 12.9 -- claiming the extra tenth would be
    claiming strength the formation has not been shown to have.
    """
    return rounding.max_allowable_mud_weight(frac_gradient_ppg)


def maasp(
    frac_gradient_ppg: float, current_mud_weight_ppg: float, shoe_tvd_ft: float
) -> int:
    """Maximum Allowable Annular Surface Pressure, psi.

    **Rounded down to a whole psi**, because it is a limit. 1181.6 is written
    as 1181; rounding up would claim margin the well does not have.

    The most casing pressure the well can be held at before the shoe breaks
    down::

        MAASP = (FG - MW) x 0.052 x TVD_shoe

    Two things about MAASP that catch people out:

    * **It falls as the mud weight rises.** Weighting up to kill a well eats
      into the very margin you need to kill it. Recompute MAASP for the kill
      mud weight, not the original.
    * **It is not a hard stop.** If holding below MAASP means letting the well
      go underbalanced and take a bigger influx, the shoe is not the most
      urgent problem. It is a number to plan around, not a number to obey while
      the well gets away from you.
    """
    delta = frac_gradient_ppg - current_mud_weight_ppg
    return rounding.pressure_limit(PSI_PER_PPG_FT * delta * shoe_tvd_ft)


# --------------------------------------------------------------------------
# Kick tolerance
# --------------------------------------------------------------------------

@dataclass
class KickTolerance:
    """Kick tolerance for a well at a given depth and mud weight.

    Args:
        mud_weight_ppg: Mud currently in the hole.
        frac_gradient_ppg: Formation strength at the shoe, ppg EMW.
        shoe_tvd_ft: Casing shoe, TVD.
        hole_tvd_ft: Total depth, TVD.
        annular_capacity_at_shoe_bbl_per_ft: Annular capacity across the shoe.
        annular_capacity_at_td_bbl_per_ft: Annular capacity at the bottom of
            the hole, where the influx first enters.
        influx_gradient_psi_per_ft: Gradient of the assumed influx. 0.1 psi/ft
            is the usual planning value for gas.
    """

    mud_weight_ppg: float
    frac_gradient_ppg: float
    shoe_tvd_ft: float
    hole_tvd_ft: float
    annular_capacity_at_shoe_bbl_per_ft: float
    annular_capacity_at_td_bbl_per_ft: float
    influx_gradient_psi_per_ft: float = 0.1

    def __post_init__(self) -> None:
        if self.shoe_tvd_ft >= self.hole_tvd_ft:
            raise ValueError("The shoe must be above total depth")
        if self.frac_gradient_ppg <= self.mud_weight_ppg:
            raise ValueError(
                f"Mud weight ({self.mud_weight_ppg:.2f} ppg) already meets or "
                f"exceeds the fracture gradient ({self.frac_gradient_ppg:.2f} "
                "ppg). There is no kick tolerance and the well is losing, or "
                "about to."
            )

    @property
    def frac_pressure_psi(self) -> float:
        return frac_pressure_at_shoe(self.frac_gradient_ppg, self.shoe_tvd_ft)

    @property
    def maasp_psi(self) -> int:
        return maasp(self.frac_gradient_ppg, self.mud_weight_ppg, self.shoe_tvd_ft)

    @property
    def max_allowable_mud_weight_ppg(self) -> float:
        """MAMW at the shoe, ppg, rounded down to a tenth."""
        return max_allowable_mud_weight(self.frac_gradient_ppg)

    @property
    def max_formation_pressure_psi(self) -> float:
        """Highest pore pressure that can be shut in with no influx, psi.

        Assumes the annulus is still full of mud -- the moment of shut-in on a
        kick so small its volume is negligible::

            Pf_max = P_frac + 0.052 x MW x (TVD_hole - TVD_shoe)
        """
        return self.frac_pressure_psi + (
            PSI_PER_PPG_FT * self.mud_weight_ppg * (self.hole_tvd_ft - self.shoe_tvd_ft)
        )

    @property
    def kick_intensity_ppg(self) -> float:
        """Kick tolerance as a pore pressure margin, ppg.

        How much heavier than the current mud the pore pressure can be before
        shutting in would break the shoe. Also read as: how far the mud weight
        could be under-estimated and still be survivable.
        """
        return (
            self.max_formation_pressure_psi / (PSI_PER_PPG_FT * self.hole_tvd_ft)
            - self.mud_weight_ppg
        )

    def max_influx_height_ft(self, formation_pressure_psi: float) -> float:
        """Tallest influx that can sit with its top at the shoe, ft (vertical).

        The critical moment while circulating a gas kick out is when the top of
        the influx arrives at the shoe: everything above is mud, the influx has
        expanded on its way up, and the shoe carries the most pressure it ever
        will.

        Holding bottomhole pressure at the formation pressure::

            P_shoe = Pf - 0.052 x MW x (TVD_hole - TVD_shoe)
                        + h x (0.052 x MW - G_influx)

        Setting ``P_shoe = P_frac`` and solving for ``h``.
        """
        mud_gradient = PSI_PER_PPG_FT * self.mud_weight_ppg
        denominator = mud_gradient - self.influx_gradient_psi_per_ft
        if denominator <= 0:
            raise ValueError(
                "The influx is as dense as the mud, so it displaces no "
                "hydrostatic and imposes no limit by this analysis."
            )
        numerator = (
            self.frac_pressure_psi
            - formation_pressure_psi
            + mud_gradient * (self.hole_tvd_ft - self.shoe_tvd_ft)
        )
        if numerator <= 0:
            raise ValueError(
                f"With a formation pressure of {formation_pressure_psi:.0f} psi "
                "the shoe is already at its fracture pressure with no influx at "
                "all. This well has no kick tolerance at this depth."
            )
        return numerator / denominator

    def max_influx_volume_at_shoe_bbl(self, formation_pressure_psi: float) -> float:
        """Largest influx volume tolerable *at the shoe*, bbl."""
        height = self.max_influx_height_ft(formation_pressure_psi)
        return height * self.annular_capacity_at_shoe_bbl_per_ft

    def max_influx_volume_at_td_bbl(self, formation_pressure_psi: float) -> float:
        """Largest influx volume tolerable *when taken*, bbl.

        This is the number that matters on the rig floor, because it is what
        the pit gain indicator shows. Gas expands as it is circulated up, so
        the volume that is safe at bottom is much smaller than the volume that
        is safe at the shoe -- often by a factor of three or more.

        Works backwards from :meth:`max_influx_volume_at_shoe_bbl` using
        Boyle's law, taking the gas pressure at the shoe as the average over
        the influx height, and its pressure at bottom as the formation
        pressure. Isothermal and ideal-gas, which slightly over-estimates
        expansion and so errs toward caution.
        """
        height = self.max_influx_height_ft(formation_pressure_psi)
        volume_at_shoe = height * self.annular_capacity_at_shoe_bbl_per_ft

        # With the influx top at the shoe and the shoe at its fracture limit,
        # the pressure at the top of the gas is the fracture pressure. Average
        # over the influx height for the bulk gas pressure.
        average_gas_pressure = (
            self.frac_pressure_psi + self.influx_gradient_psi_per_ft * height / 2.0
        )

        p_shoe = psi_to_psia(average_gas_pressure)
        p_bottom = psi_to_psia(formation_pressure_psi)
        return volume_at_shoe * p_shoe / p_bottom

    def max_pit_gain_bbl(self, kick_intensity_ppg: float) -> float:
        """Tolerable pit gain for a stated kick intensity, bbl.

        The practical planning question: "if we take a kick that turns out to
        be N ppg heavier than our mud, how much can we let in before we are in
        trouble?"
        """
        formation_pressure = (
            PSI_PER_PPG_FT
            * (self.mud_weight_ppg + kick_intensity_ppg)
            * self.hole_tvd_ft
        )
        return self.max_influx_volume_at_td_bbl(formation_pressure)

    def summary(self, formation_pressure_psi: float | None = None) -> dict[str, float]:
        """Headline kick tolerance numbers."""
        out = {
            "Mud weight (ppg)": round(self.mud_weight_ppg, 2),
            "Fracture gradient (ppg)": round(self.frac_gradient_ppg, 2),
            "Fracture pressure at shoe (psi)": round(self.frac_pressure_psi, 0),
            "MAASP (psi)": round(self.maasp_psi, 0),
            "Kick intensity tolerance (ppg)": round(self.kick_intensity_ppg, 2),
            "Max formation pressure (psi)": round(self.max_formation_pressure_psi, 0),
        }
        if formation_pressure_psi is not None:
            out["Max influx height at shoe (ft)"] = round(
                self.max_influx_height_ft(formation_pressure_psi), 1
            )
            out["Max influx volume at shoe (bbl)"] = round(
                self.max_influx_volume_at_shoe_bbl(formation_pressure_psi), 1
            )
            out["Max influx volume when taken (bbl)"] = round(
                self.max_influx_volume_at_td_bbl(formation_pressure_psi), 1
            )
        return out
