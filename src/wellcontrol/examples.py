"""Reference wells used throughout the tests and the teaching content.

Three wells, chosen because they fail in different ways:

* :func:`vertical_land_well` -- the textbook case. MD equals TVD, one string
  size, surface stack. Everything reduces to the simple formulas.
* :func:`horizontal_well` -- 12,000 ft MD but only 5,910 ft TVD. Anywhere the
  two are confused, this well produces a badly wrong answer.
* :func:`deepwater_subsea_well` -- 5,000 ft of water. Choke line friction and
  riser margin dominate.

Every number here is illustrative. They are internally consistent and
realistic, but they are not from any real well.
"""

from __future__ import annotations

from .geometry import Annulus, DrillString, HoleSection, Pipe, Pump, Wellbore
from .killsheet import KillSheet, SlowCirculatingRate
from .rheology import BinghamPlastic
from .subsea import SubseaGeometry
from .survey import Survey
from .tolerance import KickTolerance, frac_gradient_from_leak_off
from .wellconfig import BOPLocation, Trajectory, WellConfiguration


# --------------------------------------------------------------------------
# Shared equipment
# --------------------------------------------------------------------------

def standard_pump() -> Pump:
    """A 7-1/2 in stroke triplex with a 6-1/2 in liner at 95% efficiency.

    Output works out at about 0.117 bbl/stroke.
    """
    return Pump(
        liner_id_in=6.5, stroke_length_in=12.0, efficiency=0.95, kind="triplex"
    )


def standard_mud_rheology() -> BinghamPlastic:
    """A typical water-based mud: 20 cP PV, 12 lb/100ft^2 YP."""
    return BinghamPlastic(plastic_viscosity_cp=20.0, yield_point_lb_100ft2=12.0)


def _standard_string(bit_depth_md: float) -> DrillString:
    """6-1/2 in collars over 5 in drill pipe, run to the given bit depth."""
    collars = Pipe(
        name="6-1/2in x 2-13/16in Drill Collars",
        od_in=6.5,
        id_in=2.8125,
        length_ft=600.0,
    )
    drill_pipe = Pipe(
        name="5in 19.5 lb/ft Drill Pipe", od_in=5.0, id_in=4.276, length_ft=0.0
    )
    return DrillString.from_bha([collars], drill_pipe, bit_depth_md)


# --------------------------------------------------------------------------
# Well A -- vertical land well
# --------------------------------------------------------------------------

def vertical_land_well() -> tuple[Annulus, Survey]:
    """10,000 ft vertical land well, 9-5/8 in casing at 7,000 ft.

    Returns ``(annulus, survey)``.
    """
    wellbore = Wellbore([
        HoleSection("9-5/8in Casing", id_in=8.681, top_md=0.0, bottom_md=7000.0),
        HoleSection(
            "8-1/2in Open Hole",
            id_in=8.5,
            top_md=7000.0,
            bottom_md=10000.0,
            is_open_hole=True,
        ),
    ])
    string = _standard_string(10000.0)
    return Annulus(wellbore, string), Survey.vertical(10000.0)


def vertical_land_well_kill_sheet() -> KillSheet:
    """A 20 bbl gas kick on the vertical land well.

    Shut-in readings: SIDPP 400 psi, SICP 660 psi, pit gain 20 bbl, in
    9.6 ppg mud. The influx works out at roughly 2 ppg -- gas.
    """
    annulus, survey = vertical_land_well()
    return KillSheet(
        sidpp_psi=400.0,
        sicp_psi=660.0,
        pit_gain_bbl=20.0,
        mud_weight_ppg=9.6,
        annulus=annulus,
        survey=survey,
        pump=standard_pump(),
        slow_circulating_rate=SlowCirculatingRate(
            spm=30.0, pressure_psi=600.0, pump_label="Pump 1"
        ),
    )


def vertical_land_well_kick_tolerance() -> KickTolerance:
    """Kick tolerance for the vertical land well.

    Leak-off test at the 7,000 ft shoe: 1,400 psi with 9.0 ppg mud in the
    hole, giving a fracture gradient of about 12.85 ppg.
    """
    annulus, _ = vertical_land_well()
    frac_gradient = frac_gradient_from_leak_off(
        test_mud_weight_ppg=9.0, leak_off_pressure_psi=1400.0, shoe_tvd_ft=7000.0
    )
    return KickTolerance(
        mud_weight_ppg=9.6,
        frac_gradient_ppg=frac_gradient,
        shoe_tvd_ft=7000.0,
        hole_tvd_ft=10000.0,
        annular_capacity_at_shoe_bbl_per_ft=annulus.capacity_at(6900.0),
        annular_capacity_at_td_bbl_per_ft=annulus.capacity_at(9990.0),
        influx_gradient_psi_per_ft=0.1,
    )


# --------------------------------------------------------------------------
# Well B -- horizontal well
# --------------------------------------------------------------------------

def horizontal_survey() -> Survey:
    """Build-and-hold to horizontal: KOP 4,000 ft, 3 deg/100 ft, TD 12,000 ft MD.

    The build finishes at 7,000 ft MD and 5,910 ft TVD, then 5,000 ft of
    lateral adds measured depth without adding a single foot of TVD.
    """
    return Survey.build_and_hold(
        kop_md=4000.0,
        build_rate_deg_per_100ft=3.0,
        final_inclination_deg=90.0,
        total_md=12000.0,
    )


def horizontal_well() -> tuple[Annulus, Survey]:
    """12,000 ft MD / 5,910 ft TVD horizontal well.

    7 in liner to 7,200 ft MD (just past the build), 6 in open hole lateral.
    """
    wellbore = Wellbore([
        HoleSection("9-5/8in Casing", id_in=8.681, top_md=0.0, bottom_md=7200.0),
        HoleSection(
            "6in Open Hole Lateral",
            id_in=6.0,
            top_md=7200.0,
            bottom_md=12000.0,
            is_open_hole=True,
        ),
    ])
    collars = Pipe(
        name="4-3/4in x 2-1/4in Drill Collars", od_in=4.75, id_in=2.25, length_ft=400.0
    )
    drill_pipe = Pipe(
        name="4in 14 lb/ft Drill Pipe", od_in=4.0, id_in=3.34, length_ft=0.0
    )
    string = DrillString.from_bha([collars], drill_pipe, 12000.0)
    return Annulus(wellbore, string), horizontal_survey()


def horizontal_well_kill_sheet() -> KillSheet:
    """A kick on the horizontal well.

    The point of this example is the kill mud weight. SIDPP 350 psi over
    5,910 ft TVD needs a 1.14 ppg increase. Using the 12,000 ft measured depth
    instead would call for 0.56 ppg -- barely half of what the well needs, and
    the well would not die.
    """
    annulus, survey = horizontal_well()
    return KillSheet(
        sidpp_psi=350.0,
        # Influx in the lateral has no vertical height, so it displaces no
        # hydrostatic and the two gauges read the same.
        sicp_psi=350.0,
        pit_gain_bbl=15.0,
        mud_weight_ppg=10.2,
        annulus=annulus,
        survey=survey,
        pump=standard_pump(),
        slow_circulating_rate=SlowCirculatingRate(spm=35.0, pressure_psi=750.0),
    )


# --------------------------------------------------------------------------
# Well C -- deepwater subsea well
# --------------------------------------------------------------------------

def deepwater_geometry() -> SubseaGeometry:
    """75 ft air gap over 5,000 ft of water. Mudline sits 5,075 ft below RKB."""
    return SubseaGeometry(air_gap_ft=75.0, water_depth_ft=5000.0, seawater_ppg=8.55)


def deepwater_subsea_well() -> tuple[Annulus, Survey]:
    """15,000 ft TVD subsea well in 5,000 ft of water.

    The hole is vertical below the mudline, so MD equals TVD. The interval
    above the mudline is riser, not hole -- it is represented here as a section
    of the flow path so that annular volumes come out right.
    """
    wellbore = Wellbore([
        HoleSection("21in Riser", id_in=19.5, top_md=0.0, bottom_md=5075.0),
        HoleSection(
            "13-3/8in Casing", id_in=12.415, top_md=5075.0, bottom_md=11000.0
        ),
        HoleSection(
            "12-1/4in Open Hole",
            id_in=12.25,
            top_md=11000.0,
            bottom_md=15000.0,
            is_open_hole=True,
        ),
    ])
    collars = Pipe(
        name="8in x 3in Drill Collars", od_in=8.0, id_in=3.0, length_ft=800.0
    )
    drill_pipe = Pipe(
        name="5-1/2in 21.9 lb/ft Drill Pipe", od_in=5.5, id_in=4.778, length_ft=0.0
    )
    string = DrillString.from_bha([collars], drill_pipe, 15000.0)
    return Annulus(wellbore, string), Survey.vertical(15000.0)


def deepwater_horizontal_well() -> tuple[Annulus, Survey]:
    """Subsea horizontal well: 17,000 ft MD / 10,910 ft TVD in 5,000 ft of water.

    Kick-off below the mudline at 9,000 ft, building to horizontal by 12,000 ft
    MD, then a 5,000 ft lateral. The hardest of the four configurations: choke
    line friction, a mudline datum, and an influx that neither migrates nor
    shows itself on the casing gauge.
    """
    survey = Survey.build_and_hold(
        kop_md=9000.0,
        build_rate_deg_per_100ft=3.0,
        final_inclination_deg=90.0,
        total_md=17000.0,
    )
    wellbore = Wellbore([
        HoleSection("21in Riser", id_in=19.5, top_md=0.0, bottom_md=5075.0),
        HoleSection("9-5/8in Casing", id_in=8.681, top_md=5075.0, bottom_md=12200.0),
        HoleSection(
            "6in Open Hole Lateral",
            id_in=6.0,
            top_md=12200.0,
            bottom_md=17000.0,
            is_open_hole=True,
        ),
    ])
    collars = Pipe(
        name="4-3/4in x 2-1/4in Drill Collars", od_in=4.75, id_in=2.25, length_ft=400.0
    )
    drill_pipe = Pipe(
        name="4in 14 lb/ft Drill Pipe", od_in=4.0, id_in=3.34, length_ft=0.0
    )
    string = DrillString.from_bha([collars], drill_pipe, 17000.0)
    return Annulus(wellbore, string), survey


def deepwater_kill_sheet(choke_line_friction_psi: float = 350.0) -> KillSheet:
    """A kick on the deepwater well, with choke line friction applied.

    Set ``choke_line_friction_psi=0`` to see what ignoring it would do: the
    whole kill would run about 350 psi over-pressured on the formation, for
    every stroke of a very long circulation.
    """
    annulus, survey = deepwater_subsea_well()
    return KillSheet(
        sidpp_psi=500.0,
        sicp_psi=664.0,
        pit_gain_bbl=25.0,
        mud_weight_ppg=12.5,
        annulus=annulus,
        survey=survey,
        pump=standard_pump(),
        slow_circulating_rate=SlowCirculatingRate(spm=30.0, pressure_psi=900.0),
        choke_line_friction_psi=choke_line_friction_psi,
    )


# --------------------------------------------------------------------------
# Well states for the four standard configurations
# --------------------------------------------------------------------------

def pull_off_bottom(annulus: Annulus, off_bottom_ft: float) -> Annulus:
    """Rebuild an annulus with the bit pulled up off bottom.

    Stripping only applies when the bit is off bottom, so this makes the
    reference wells usable for it. The BHA is unchanged; the drill pipe is
    shortened.
    """
    if off_bottom_ft <= 0:
        return annulus
    components = annulus.string.components
    new_bit = annulus.string.bit_depth_md - off_bottom_ft
    if new_bit <= sum(c.length_ft for c in components[:-1]):
        raise ValueError(
            f"Pulling {off_bottom_ft:,.0f} ft off bottom would put the bit above "
            "the top of the BHA"
        )
    string = DrillString.from_bha(list(components[:-1]), components[-1], new_bit)
    return Annulus(annulus.wellbore, string)


def well_state(configuration: WellConfiguration, bit_off_bottom_ft: float = 0.0):
    """A ready-made :class:`~wellcontrol.methods.base.WellState` for a config.

    Gives every kill method a realistic well of the requested type to work on.
    Imported lazily so that ``wellcontrol.examples`` stays importable from
    inside the methods package.

    Args:
        configuration: Which of the four standard well types.
        bit_off_bottom_ft: Pull the bit up by this much. Needed for the
            Stripping method, which only applies off bottom.
    """
    from .methods.base import WellState

    state = _well_state(configuration)
    if bit_off_bottom_ft > 0:
        state.annulus = pull_off_bottom(state.annulus, bit_off_bottom_ft)
        # With the bit off bottom and the influx below it, both gauges read
        # through the same clean mud to the bit and through the same fluids
        # below it, so the two shut-in pressures are equal. A difference
        # between them would mean the influx had risen above the bit.
        if state.influx_top_md_ft >= state.bit_md_ft:
            state.sicp_psi = state.sidpp_psi
        # Off bottom and shut in, gas migrates unless the hole is horizontal.
        if configuration.trajectory.migration_reliable:
            state.gas_migration_rate_ft_per_hr = 1000.0
    return state


def _well_state(configuration: WellConfiguration):
    from .methods.base import WellState

    if configuration.is_subsea and configuration.is_horizontal:
        annulus, survey = deepwater_horizontal_well()
        return WellState(
            annulus=annulus,
            survey=survey,
            pump=standard_pump(),
            mud_weight_ppg=12.5,
            slow_circulating_rate=SlowCirculatingRate(spm=30.0, pressure_psi=950.0),
            configuration=configuration,
            sidpp_psi=450.0,
            # The influx lies in the lateral, so it has no vertical height and
            # displaces no hydrostatic. Both gauges read through the same mud
            # to the same TVD, so SICP equals SIDPP. A difference would mean
            # the influx had reached the build section.
            sicp_psi=450.0,
            pit_gain_bbl=20.0,
            frac_gradient_ppg=14.2,
            shoe_md_ft=12200.0,
            subsea=deepwater_geometry(),
            choke_line_friction_psi=350.0,
        )

    if configuration.is_subsea:
        annulus, survey = deepwater_subsea_well()
        return WellState(
            annulus=annulus,
            survey=survey,
            pump=standard_pump(),
            mud_weight_ppg=12.5,
            slow_circulating_rate=SlowCirculatingRate(spm=30.0, pressure_psi=900.0),
            configuration=configuration,
            sidpp_psi=500.0,
            # A 25 bbl gas influx stands 299 ft tall in the collar annulus, so
            # SICP - SIDPP = (0.650 - 0.100) x 299 = 165 psi.
            sicp_psi=664.0,
            pit_gain_bbl=25.0,
            frac_gradient_ppg=13.8,
            shoe_md_ft=11000.0,
            subsea=deepwater_geometry(),
            choke_line_friction_psi=350.0,
        )

    if configuration.is_horizontal:
        annulus, survey = horizontal_well()
        return WellState(
            annulus=annulus,
            survey=survey,
            pump=standard_pump(),
            mud_weight_ppg=10.2,
            slow_circulating_rate=SlowCirculatingRate(spm=35.0, pressure_psi=750.0),
            configuration=configuration,
            sidpp_psi=350.0,
            # Influx in the lateral: no vertical height, no hydrostatic
            # displaced, so SICP equals SIDPP.
            sicp_psi=350.0,
            pit_gain_bbl=15.0,
            frac_gradient_ppg=13.5,
            shoe_md_ft=7200.0,
        )

    annulus, survey = vertical_land_well()
    return WellState(
        annulus=annulus,
        survey=survey,
        pump=standard_pump(),
        mud_weight_ppg=9.6,
        slow_circulating_rate=SlowCirculatingRate(spm=30.0, pressure_psi=600.0),
        configuration=configuration,
        sidpp_psi=400.0,
        sicp_psi=660.0,
        pit_gain_bbl=20.0,
        frac_gradient_ppg=12.85,
        shoe_md_ft=7000.0,
    )


def all_well_states() -> dict[str, object]:
    """One well state per standard configuration, keyed by configuration key."""
    return {config.key: well_state(config) for config in WellConfiguration.standard()}
