"""Subsea well control: what changes when the BOP is on the seabed.

Three things are different from a surface stack, and each one has caught people
out:

**1. The choke line is long and narrow.** On a surface stack the choke line is
a few tens of feet. On a subsea well it runs the full water depth in a
2-3 inch line. Circulating through it costs real friction pressure -- often
hundreds of psi -- and that friction acts on the annulus, so it lands directly
on the formation. Kill pressures must be corrected for it or the well is
over-pressured for the whole kill.

**2. The reference depth is the seabed, not the rig floor.** The BOP is at the
mudline. Between the mudline and the rig floor there is water and air gap, not
formation. MAASP and shoe calculations reference the true vertical depths of
the wellhead and shoe, and the seawater column above the mudline is part of the
pressure balance.

**3. The riser can be disconnected.** If the riser is disconnected -- or is
lost -- the mud above the mudline is replaced by seawater, which is much
lighter. Hydrostatic at the formation drops instantly. **Riser margin** is the
extra mud weight that keeps the well overbalanced through a disconnect. On many
deepwater wells carrying full riser margin is impossible because it would
fracture the shoe, and the well is drilled knowingly without it.
"""

from __future__ import annotations

from dataclasses import dataclass

from .hydrostatics import hydrostatic_pressure
from .rheology import BinghamPlastic, PowerLaw
from .units import PSI_PER_PPG_FT, SEAWATER_PPG


# --------------------------------------------------------------------------
# Rig and water geometry
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class SubseaGeometry:
    """Vertical arrangement of a floating rig over a subsea wellhead.

    All depths are TVD referenced to the rotary table (RKB).

    Attributes:
        air_gap_ft: RKB down to mean sea level.
        water_depth_ft: Sea level down to the mudline.
        seawater_ppg: Seawater density.
    """

    air_gap_ft: float
    water_depth_ft: float
    seawater_ppg: float = SEAWATER_PPG

    @property
    def mudline_tvd_ft(self) -> float:
        """TVD of the mudline (and so of the BOP stack) below RKB."""
        return self.air_gap_ft + self.water_depth_ft

    @property
    def seawater_hydrostatic_psi(self) -> float:
        """Pressure of the seawater column at the mudline, psi."""
        return hydrostatic_pressure(self.seawater_ppg, self.water_depth_ft)


# --------------------------------------------------------------------------
# Choke line friction
# --------------------------------------------------------------------------

def choke_line_friction_estimate(
    length_ft: float,
    inside_diameter_in: float,
    flow_rate_gpm: float,
    model: BinghamPlastic | PowerLaw,
    mud_weight_ppg: float | None = None,
) -> float:
    """Estimated choke line friction at a given rate, psi.

    The choke line is just a pipe, so this uses the pipe friction correlation.

    **Prefer the measured value.** Choke line friction is obtained by taking a
    slow circulating rate reading through the choke line and comparing it with
    the same rate through the riser; the difference is the friction. That
    measurement is part of the pre-drill BOP test programme on every subsea
    well and is far more trustworthy than any correlation.
    """
    if isinstance(model, BinghamPlastic):
        if mud_weight_ppg is None:
            raise ValueError("The Bingham model needs mud_weight_ppg")
        gradient = model.pipe_gradient_psi_per_ft(
            flow_rate_gpm, inside_diameter_in, mud_weight_ppg
        )
    else:
        gradient = model.pipe_gradient_psi_per_ft(flow_rate_gpm, inside_diameter_in)
    return gradient * length_ft


def choke_line_friction_measured(
    scr_through_riser_psi: float, scr_through_choke_line_psi: float
) -> float:
    """Choke line friction from two slow circulating rate readings, psi.

    Take the same rate through the riser and then through the choke line; the
    increase is the friction in the choke line.
    """
    friction = scr_through_choke_line_psi - scr_through_riser_psi
    if friction < 0:
        raise ValueError(
            "Circulating through the choke line read lower than through the "
            "riser, which is not physical. Check which reading is which."
        )
    return friction


def corrected_initial_circulating_pressure(
    sidpp_psi: float, scr_through_riser_psi: float, choke_line_friction_psi: float
) -> float:
    """ICP for a subsea kill, psi.

    Circulating up the choke line, its friction already presses on the
    formation. Holding the normal ICP on top of that would over-pressure the
    well by the amount of the friction, so the target is reduced::

        ICP_subsea = SIDPP + SCR - CLF

    The alternative, used where reducing the drill pipe target is awkward, is
    to hold the extra pressure off with the choke instead -- but one or the
    other must be done.
    """
    return sidpp_psi + scr_through_riser_psi - choke_line_friction_psi


# --------------------------------------------------------------------------
# Riser margin
# --------------------------------------------------------------------------

def riser_margin_ppg(
    mud_weight_ppg: float,
    formation_tvd_ft: float,
    geometry: SubseaGeometry,
) -> float:
    """Extra mud weight needed to survive a riser disconnect, ppg.

    With the riser connected, the formation sees a full mud column from RKB::

        P = 0.052 x MW x TVD

    After a disconnect, mud only fills the hole from the mudline down, and
    seawater sits above it::

        P = 0.052 x MW_new x (TVD - air gap - water depth)
          + 0.052 x SW x water depth

    Setting those equal and solving for the mud weight difference gives the
    riser margin.

    On a deepwater well with a shallow shoe this number is often larger than
    the drilling window allows, which is why many deepwater wells run without
    full riser margin and rely on keeping the riser connected instead.
    """
    below_mudline = formation_tvd_ft - geometry.mudline_tvd_ft
    if below_mudline <= 0:
        raise ValueError(
            f"The formation TVD ({formation_tvd_ft:.0f} ft) is at or above the "
            f"mudline ({geometry.mudline_tvd_ft:.0f} ft)"
        )
    required = (
        mud_weight_ppg * formation_tvd_ft
        - geometry.seawater_ppg * geometry.water_depth_ft
    ) / below_mudline
    return required - mud_weight_ppg


def hydrostatic_loss_on_disconnect(
    mud_weight_ppg: float,
    formation_tvd_ft: float,
    geometry: SubseaGeometry,
) -> float:
    """Bottomhole pressure lost when the riser is disconnected, psi.

    If this exceeds the overbalance the well was carrying, disconnecting puts
    the well underbalanced and it will flow.
    """
    connected = hydrostatic_pressure(mud_weight_ppg, formation_tvd_ft)
    below_mudline = formation_tvd_ft - geometry.mudline_tvd_ft
    disconnected = (
        hydrostatic_pressure(mud_weight_ppg, below_mudline)
        + geometry.seawater_hydrostatic_psi
    )
    return connected - disconnected


# --------------------------------------------------------------------------
# Subsea MAASP
# --------------------------------------------------------------------------

def subsea_maasp(
    frac_gradient_ppg: float,
    mud_weight_ppg: float,
    shoe_tvd_ft: float,
) -> float:
    """MAASP for a subsea well, psi, read at the rig floor gauge.

    Identical in form to the surface case as long as every depth is a true
    vertical depth below the rotary table and the annulus above the shoe is
    full of mud::

        MAASP = (FG - MW) x 0.052 x TVD_shoe

    The subsea complication is not this formula -- it is that the gauge is at
    the rig floor while the BOP is at the mudline, so the pressure at the stack
    differs from the gauge reading by the hydrostatic of everything in between.
    Use :func:`pressure_at_wellhead` for the stack pressure.
    """
    return PSI_PER_PPG_FT * (frac_gradient_ppg - mud_weight_ppg) * shoe_tvd_ft


def pressure_at_wellhead(
    surface_gauge_psi: float,
    mud_weight_ppg: float,
    geometry: SubseaGeometry,
) -> float:
    """Pressure at the subsea BOP given the rig floor gauge reading, psi.

    Assumes the choke line (or riser annulus) between the gauge and the stack
    is full of mud. Wellhead equipment ratings are quoted at the stack, so this
    is the conversion needed to check them.
    """
    return surface_gauge_psi + hydrostatic_pressure(
        mud_weight_ppg, geometry.mudline_tvd_ft
    )


@dataclass
class SubseaKillCorrections:
    """The corrections a subsea kill sheet needs on top of a surface one."""

    geometry: SubseaGeometry
    choke_line_friction_psi: float
    mud_weight_ppg: float

    def summary(self) -> dict[str, float]:
        return {
            "Air gap (ft)": round(self.geometry.air_gap_ft, 0),
            "Water depth (ft)": round(self.geometry.water_depth_ft, 0),
            "Mudline TVD below RKB (ft)": round(self.geometry.mudline_tvd_ft, 0),
            "Seawater hydrostatic at mudline (psi)": round(
                self.geometry.seawater_hydrostatic_psi, 0
            ),
            "Choke line friction at kill rate (psi)": round(
                self.choke_line_friction_psi, 0
            ),
        }
