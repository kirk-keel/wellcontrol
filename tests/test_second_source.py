"""Validation against a second source, including one genuinely published table.

``tests/test_real_files.py`` checks the geometry and the shut-in kill sheet.
This checks the part that had nothing to check it: **the circulating trace**.

Three tiers of evidence, weakest last:

1. **Published.** ``External_Validation`` reproduces a worked example from
   drillingformulas.com -- its inputs and its printed drill pipe pressure table.
   That is the only genuinely external number in the project, and
   :class:`TestPublishedSchedule` is the only test here that can be said to
   check the library against the outside world.
2. **Independent implementation.** ``circulating_profile.csv`` is a second
   model of the same well, written separately. Agreement is a strong
   cross-check; it is not proof, because two implementations can share a
   misunderstanding.
3. **Internal consistency.** Everything else in the suite.

**This is the file that found the gas density bug.** The circulation held the
influx at its shut-in density while letting its volume expand from 22 to 102
bbl, which quietly creates gas mass from nothing. The over-heavy column
supplied hydrostatic that was not there, so casing pressure came out low -- by
182 psi at the peak, in the unsafe direction, at the moment the margin against
MAASP matters most. Nothing in 1,000 internally-consistent tests caught it.
Keep this file pointed at anything that changes the fluid column.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "test_data"
SECOND = DATA / "second_source"
PROFILE = SECOND / "circulating_profile.csv"

pytestmark = pytest.mark.skipif(
    not PROFILE.exists(), reason="test_data/second_source/ is not present"
)

BIT_MD_FT = 12500.0
SHOE_MD_FT = 8200.0


# --------------------------------------------------------------------------
# Tier 1: the published worked example
# --------------------------------------------------------------------------

DEPTH_FT = 9000.0
MUD_WEIGHT_PPG = 9.5
SCR_PSI = 1100.0
STRING_CAPACITY_BBL_PER_FT = 0.0178
PUMP_OUTPUT_BBL_PER_STK = 0.1


def build_uniform_sheet(sidpp_psi: float):
    """The article's well: 9,000 ft vertical, one pipe size, MD equal to TVD."""
    from wellcontrol.geometry import (
        Annulus, DrillString, HoleSection, Pipe, Pump, Wellbore,
    )
    from wellcontrol.killsheet import KillSheet, SlowCirculatingRate
    from wellcontrol.survey import Survey

    # ID that gives the article's stated capacity: ID^2 / 1029.4.
    inner = (STRING_CAPACITY_BBL_PER_FT * 1029.4) ** 0.5
    string = DrillString(
        components=[Pipe(name="drill pipe", od_in=5.0, id_in=inner,
                         length_ft=DEPTH_FT)],
        bit_depth_md=DEPTH_FT,
    )
    wellbore = Wellbore(sections=[
        HoleSection(name="open hole", id_in=8.5, top_md=0.0,
                    bottom_md=DEPTH_FT, is_open_hole=True)
    ])
    # Triplex output = 0.000243 x liner^2 x stroke x efficiency.
    liner = (PUMP_OUTPUT_BBL_PER_STK / (0.000243 * 12.0)) ** 0.5
    return KillSheet(
        sidpp_psi=sidpp_psi, sicp_psi=700.0, pit_gain_bbl=10.0,
        mud_weight_ppg=MUD_WEIGHT_PPG,
        annulus=Annulus(wellbore=wellbore, string=string),
        survey=Survey.vertical(DEPTH_FT),
        pump=Pump(liner_id_in=liner, stroke_length_in=12.0, efficiency=1.0),
        slow_circulating_rate=SlowCirculatingRate(
            spm=30.0, pressure_psi=SCR_PSI
        ),
    )


@pytest.fixture(scope="module")
def sheet():
    return build_uniform_sheet(500.0)


class TestPublishedSchedule:
    """drillingformulas.com, Wait and Weight drill pipe pressure schedule.

    A 9,000 ft vertical well, so MD equals TVD and the rigorous fluid-column
    model must reduce to the textbook straight line. If it does not, the
    general model is wrong in the one case where the answer is not in doubt.
    """

    DEPTH_FT = 9000.0
    MUD_WEIGHT_PPG = 9.5
    SIDPP_PSI = 500.0
    ICP_PSI = 1600.0
    SCR_PSI = 1100.0                    # ICP - SIDPP
    STRING_CAPACITY_BBL_PER_FT = 0.0178
    PUMP_OUTPUT_BBL_PER_STK = 0.1
    SURFACE_LINE_BBL = 15.0

    #: Strokes -> the article's printed drill pipe pressure, psi.
    PUBLISHED = [
        (150, 1600), (350, 1554), (550, 1506), (750, 1459), (950, 1412),
        (1150, 1365), (1350, 1318), (1550, 1271), (1750, 1227),
    ]

    def test_string_volume(self, sheet):
        assert sheet.string_volume_bbl == pytest.approx(160.2, abs=0.1)

    def test_strokes_to_bit(self, sheet):
        assert sheet.strokes_to_bit == pytest.approx(1602, abs=1)

    def test_kill_mud_weight_matches_the_published_figure(self, sheet):
        """The article prints 10.6, which is 10.5684 rounded up to the tenth."""
        assert sheet.kill_mud_weight_exact_ppg == pytest.approx(10.5684, abs=0.001)
        assert sheet.kill_mud_weight_ppg == pytest.approx(10.6)

    def test_initial_circulating_pressure(self, sheet):
        assert sheet.initial_circulating_pressure_psi == pytest.approx(
            self.ICP_PSI, abs=1.0
        )

    def test_final_circulating_pressure_matches_the_published_figure(self, sheet):
        """1227 psi, and only if FCP is built from the *rounded* kill weight.

        A published source independently doing what the rounding rules here
        require: the rig mixes 10.6 ppg, so the pressure to hold is the one
        that 10.6 ppg produces.
        """
        assert sheet.final_circulating_pressure_psi == pytest.approx(1227, abs=1.0)

    def _front_md(self, sheet, strokes):
        surface_strokes = self.SURFACE_LINE_BBL / self.PUMP_OUTPUT_BBL_PER_STK
        in_string = max(0.0, strokes - surface_strokes)
        return sheet.kill_mud_depth_at_volume(
            in_string * self.PUMP_OUTPUT_BBL_PER_STK
        )

    @pytest.mark.parametrize("strokes,published", PUBLISHED)
    def test_schedule_tracks_the_published_table(self, sheet, strokes, published):
        """Within 15 psi, and the residual is the article's own rounding.

        The article steps its table by a rounded 47 psi per 200 strokes where
        the exact figure is 46.57, so its error accumulates downward. It also
        feeds the rounded 10.6 ppg into 0.052 x 10.6 x 9000 = 4961 psi, which
        overshoots the true bottomhole pressure of 4946 psi by 15 psi.
        """
        mine = sheet.drill_pipe_pressure_at(self._front_md(sheet, strokes))
        assert mine == pytest.approx(published, abs=15.0)

    def test_the_schedule_is_a_straight_line_in_a_uniform_vertical_well(self):
        """The claim the general model has to earn.

        One pipe size, MD equal to TVD: the fluid-column model must collapse to
        the textbook interpolation. Curvature here would mean the machinery
        that produces the *reversal* in a lateral is inventing structure.

        SIDPP is chosen so the kill weight lands exactly on a tenth --
        9.5 + 468/(0.052 x 9000) = 10.5 ppg -- because otherwise the rounding
        up to the mixable weight puts a real bend in the curve, which is the
        next test rather than a failure of this one.
        """
        exact = build_uniform_sheet(468.0)
        assert exact.kill_mud_weight_exact_ppg == pytest.approx(10.5, abs=1e-9)
        assert exact.kill_mud_weight_ppg == pytest.approx(10.5)

        icp = exact.initial_circulating_pressure_psi
        fcp = exact.final_circulating_pressure_psi
        volume = exact.string_volume_bbl
        for fraction in (0.1, 0.25, 0.5, 0.75, 0.9):
            front = exact.kill_mud_depth_at_volume(volume * fraction)
            straight = icp + (fcp - icp) * fraction
            assert exact.drill_pipe_pressure_at(front) == pytest.approx(
                straight, abs=0.01
            )

    def test_rounding_the_kill_weight_up_bends_the_schedule_below_the_line(
        self, sheet
    ):
        """Why the previous test needs an exactly-round kill weight.

        The rig mixes 10.6 ppg, not 10.5684, so the string fills with mud
        slightly heavier than the one that exactly balances the formation. The
        extra hydrostatic arrives progressively as the string fills, so the
        rigorous curve sags below the ICP-to-FCP line and lands lowest near the
        bit. The second source measures the same effect; it is the gap its
        External_Validation sheet calls out between the straight line and the
        rigorous model when both are fed the article's rounded 10.6 ppg.
        """
        icp = sheet.initial_circulating_pressure_psi
        fcp = sheet.final_circulating_pressure_psi
        volume = sheet.string_volume_bbl

        deviations = []
        for fraction in (0.25, 0.5, 0.75, 1.0):
            front = sheet.kill_mud_depth_at_volume(volume * fraction)
            straight = icp + (fcp - icp) * fraction
            deviations.append(sheet.drill_pipe_pressure_at(front) - straight)

        assert all(d < 0 for d in deviations), "rounding up must sag the curve"
        # Bounded by the overbalance the rounding buys, and growing toward the bit.
        assert abs(deviations[-1]) < 20.0
        assert deviations == sorted(deviations, reverse=True)


# --------------------------------------------------------------------------
# Tier 2: the independent circulating implementation
# --------------------------------------------------------------------------

@pytest.fixture(scope="module")
def profile():
    import csv

    with PROFILE.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))

    def number(text):
        try:
            return float(text)
        except (TypeError, ValueError):
            return None

    return [{k: number(v) for k, v in row.items()} for row in rows]


@pytest.fixture(scope="module")
def well():
    sys.path.insert(0, str(ROOT / "app"))
    import shared
    from wellcontrol.importers import import_survey, import_tally
    from wellcontrol.wellconfig import BOPLocation, WellConfiguration

    survey = import_survey(DATA / "directional_survey.csv").survey
    tally = import_tally(DATA / "pipe_tally.csv", expected_bit_depth_ft=BIT_MD_FT)
    config = WellConfiguration(
        BOPLocation.SURFACE, shared.trajectory_from_survey(survey)
    )
    values = dict(shared.DEFAULTS[config.key])
    values.update(
        total_md=BIT_MD_FT, bit_md=BIT_MD_FT, shoe_md=SHOE_MD_FT,
        mw=12.2, frac=15.8, sidpp=480.0, sicp=776.0, pit_gain=22.0,
        scr_psi=320.0, scr_spm=30.0, hole_id=8.5, casing_id=8.681,
        liner_id=6.5, stroke_len=12.0, pump_eff=0.95, pump_kind="triplex",
        riser_id=19.5, rod_od=0.0, safety=0.0, stand_length=93.0, migration=0.0,
    )
    return shared.build_well(
        config, values, survey_override=survey,
        string_components=tally.components,
    )


@pytest.fixture(scope="module")
def snapshots(well):
    from wellcontrol.methods.circulating import simulate_circulation

    total = well.annulus.string.internal_volume_bbl + well.annulus.volume_bbl
    return simulate_circulation(
        well, use_kill_mud=True, influx_volume_bbl=22.0,
        total_volume_bbl=total, steps=1200,
    )


def _at(snapshots, strokes, attribute):
    """Linear interpolation of a snapshot attribute at a stroke count."""
    points = [
        (s.strokes, getattr(s, attribute)) for s in snapshots
        if getattr(s, attribute) is not None
    ]
    if strokes <= points[0][0]:
        return points[0][1]
    if strokes >= points[-1][0]:
        return points[-1][1]
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if x0 <= strokes <= x1:
            if x1 == x0:
                return y0
            return y0 + (y1 - y0) * (strokes - x0) / (x1 - x0)
    return points[-1][1]


class TestAgainstTheIndependentProfile:
    """The reason this file exists: nothing else checks the circulating trace."""

    #: Kill mud here is the rounded 13.1 ppg where the second source uses the
    #: exact 13.0558. Over the annulus that is 0.052 x 0.0442 x 10786.6 = 25 psi
    #: of extra hydrostatic, so this library reads that much lower once kill mud
    #: is around. It is deliberate margin, not error -- see rounding_overbalance.
    ROUNDING_OFFSET_PSI = 25.0

    def test_starts_from_the_same_shut_in_state(self, snapshots, profile):
        first = profile[0]
        assert snapshots[0].casing_psi == pytest.approx(
            first["Choke_Pressure_psi"], abs=2.0
        )
        assert snapshots[0].influx_volume_bbl == pytest.approx(
            first["Gas_Volume_bbl"], abs=0.1
        )

    def test_casing_pressure_tracks_through_the_expansion_phase(
        self, snapshots, profile
    ):
        """The phase the density bug corrupted: gas rising and expanding.

        Before the fix this drifted to 101 psi by 3,742 strokes. The tolerance
        here is deliberately tight -- it is the regression guard.
        """
        worst = 0.0
        for row in profile:
            if row["Strokes"] > 3800 or row["Gas_Volume_bbl"] <= 0:
                continue
            mine = _at(snapshots, row["Strokes"], "casing_psi")
            worst = max(worst, abs(mine - row["Choke_Pressure_psi"]))
        assert worst < 12.0, f"worst casing deviation {worst:.1f} psi"

    def test_shoe_pressure_tracks_throughout(self, snapshots, profile):
        worst = 0.0
        for row in profile:
            mine = _at(snapshots, row["Strokes"], "shoe_psi")
            worst = max(worst, abs(mine - row["Shoe_Pressure_psi"]))
        assert worst < self.ROUNDING_OFFSET_PSI + 5.0

    def test_gas_volume_tracks_throughout(self, snapshots, profile):
        worst = 0.0
        for row in profile:
            mine = _at(snapshots, row["Strokes"], "influx_volume_bbl")
            worst = max(worst, abs(mine - row["Gas_Volume_bbl"]))
        assert worst < 3.0, f"worst gas volume deviation {worst:.1f} bbl"

    def test_peak_casing_pressure(self, snapshots, profile):
        """1,526 psi as the gas top reaches surface."""
        theirs = max(row["Choke_Pressure_psi"] for row in profile)
        mine = max(s.casing_psi for s in snapshots)
        assert mine == pytest.approx(theirs, abs=10.0)

    def test_peak_gas_volume(self, snapshots, profile):
        theirs = max(row["Gas_Volume_bbl"] for row in profile)
        mine = max(s.influx_volume_bbl for s in snapshots)
        assert mine == pytest.approx(theirs, abs=2.0)

    def test_peak_shoe_pressure_is_at_shut_in(self, snapshots):
        """Not while circulating -- the textbook expects otherwise.

        Independently confirmed by the second source's own key, which records
        the peak at zero strokes.
        """
        peak = max(s.shoe_psi for s in snapshots)
        assert snapshots[0].shoe_psi == pytest.approx(peak, abs=1.0)

    def test_casing_pressure_ends_near_zero(self, snapshots):
        assert snapshots[-1].casing_psi == pytest.approx(0.0, abs=5.0)


class TestTheTrap:
    """The second source plants a deliberate trap; the library must survive it."""

    def test_peak_casing_pressure_exceeds_maasp_without_breaking_the_shoe(
        self, snapshots, well
    ):
        """Peak choke 1,526 psi against MAASP 1,357 -- and the shoe is fine.

        MAASP is computed for the *original* mud. By the time the gas is at
        surface the annulus holds a long light gas column, so the same surface
        pressure puts far less on the shoe than MAASP assumes. Reading MAASP as
        a hard ceiling at that moment would have the driller bleeding the well
        down and taking another influx.
        """
        peak_casing = max(s.casing_psi for s in snapshots)
        peak_shoe = max(s.shoe_psi for s in snapshots)
        assert peak_casing > well.maasp_psi()
        assert peak_shoe < well.frac_pressure_psi


# --------------------------------------------------------------------------
# The physics the bug turned on
# --------------------------------------------------------------------------

class TestExpandedGasDensity:
    def test_gas_lightens_in_proportion_to_expansion(self):
        from wellcontrol.hydrostatics import expanded_gas_density

        assert expanded_gas_density(2.0, 22.0, 44.0) == pytest.approx(1.0)
        assert expanded_gas_density(0.12, 22.0, 102.0) == pytest.approx(
            0.12 * 22.0 / 102.0
        )

    def test_unexpanded_gas_is_unchanged(self):
        from wellcontrol.hydrostatics import expanded_gas_density

        assert expanded_gas_density(2.29, 22.0, 22.0) == pytest.approx(2.29)

    def test_no_gas_falls_back_to_the_reference(self):
        from wellcontrol.hydrostatics import expanded_gas_density

        assert expanded_gas_density(2.29, 22.0, 0.0) == pytest.approx(2.29)
        assert expanded_gas_density(2.29, 0.0, 10.0) == pytest.approx(2.29)

    def test_the_influx_zone_lightens_as_it_rises(self, snapshots):
        """The regression guard, stated as a property of the trace.

        Densities are not on the snapshot, so read them off the fluid column
        the snapshot carries.
        """
        def influx_density(snapshot):
            for zone in snapshot.column.zones:
                if zone.label == "influx":
                    return zone.density_ppg
            return None

        with_gas = [
            (s.influx_volume_bbl, influx_density(s)) for s in snapshots
            if influx_density(s) is not None
        ]
        assert len(with_gas) > 10

        smallest = min(with_gas, key=lambda pair: pair[0])
        largest = max(with_gas, key=lambda pair: pair[0])
        assert largest[1] < smallest[1], "gas must lighten as it expands"
        # Mass conservation: density x volume is the same gas either end.
        assert largest[0] * largest[1] == pytest.approx(
            smallest[0] * smallest[1], rel=0.02
        )
