"""Regression tests against a real-shaped survey and pipe tally.

Every other test in this suite builds its inputs in Python, which means they
all share the assumptions of the code they test. These do not. They read the
files in ``test_data/`` -- a directional survey and a 405-component pipe tally
in the layout a rig actually produces -- and check the results against an
independently computed answer key.

The answer key is the ``Well_Data`` sheet of ``well_control_test_data.xlsx``,
which carries the expected kill sheet for the same well. The numbers below are
transcribed from it. **They were not produced by this library**, so when one of
these fails the library is wrong until proven otherwise.

Three real-file behaviours are pinned here because each one was a live bug:

* The survey stops at 12,460 ft MD while the bit is at 12,500 ft. Surveys are
  taken behind the bit, so this is the normal case, not a malformed file.
* The tally's ``Item_No`` column is a row index, not a joint count. Reading it
  as a count multiplied the string length by 200.
* The trajectory is *deviated*, holding 35 degrees. It is neither vertical nor
  horizontal, which is what most real wells look like.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from wellcontrol.importers import import_survey, import_tally

DATA = Path(__file__).resolve().parent.parent / "test_data"

pytestmark = pytest.mark.skipif(
    not DATA.exists(), reason="test_data/ is not present"
)

BIT_MD_FT = 12500.0
SHOE_MD_FT = 8200.0
MUD_WEIGHT_PPG = 12.2
FRAC_PPG = 15.8
SIDPP_PSI = 480.0
SCR_PSI = 320.0

# --- transcribed from the Well_Data sheet ---------------------------------
EXPECTED_LAST_STATION_MD = 12460.0
EXPECTED_LAST_STATION_TVD = 10753.6544938653
EXPECTED_BIT_TVD = 10786.5720180065
EXPECTED_SHOE_TVD = 7250.70446958426
EXPECTED_STRING_VOLUME_BBL = 211.354611618924
EXPECTED_ANNULUS_VOLUME_BBL = 588.463012021566
EXPECTED_HYDROSTATIC_PSI = 6843.00128822332
EXPECTED_BHP_PSI = 7323.00128822332
EXPECTED_KMW_EXACT_PPG = 13.0557648542428
EXPECTED_FCP_EXACT_PSI = 342.446291258829
EXPECTED_MAASP_CURRENT_PSI = 1357.33187670617
EXPECTED_STROKES_TO_BIT = 1805.81763578409
EXPECTED_STROKES_BIT_TO_SURFACE = 5027.83864981928

# The survey file carries TVD rounded to 4 decimals, so results derived from it
# land a few thousandths of a foot off the workbook's full-precision figures.
TVD_TOLERANCE_FT = 0.02


@pytest.fixture(scope="module")
def survey():
    return import_survey(DATA / "directional_survey.csv").survey


@pytest.fixture(scope="module")
def tally():
    return import_tally(DATA / "pipe_tally.csv", expected_bit_depth_ft=BIT_MD_FT)


@pytest.fixture(scope="module")
def bit_tvd(survey):
    return survey.extended_to(BIT_MD_FT).tvd_at(BIT_MD_FT)


@pytest.fixture(scope="module")
def shoe_tvd(survey):
    return survey.extended_to(BIT_MD_FT).tvd_at(SHOE_MD_FT)


class TestSurveyImport:
    def test_reads_every_station(self, survey):
        assert len(survey.stations) == 157

    def test_takes_tvd_from_the_file_rather_than_recomputing(self):
        outcome = import_survey(DATA / "directional_survey.csv")
        assert not outcome.tvd_was_computed

    def test_underscored_headers_resolve(self):
        """``MD_ft`` must match ``md`` without ``OD_in`` matching it too."""
        outcome = import_survey(DATA / "directional_survey.csv")
        assert outcome.columns_used["md"] == "MD_ft"
        assert outcome.columns_used["tvd"] == "TVD_ft"
        assert outcome.columns_used["inclination"] == "Inclination_deg"

    def test_ends_behind_the_bit(self, survey):
        """The premise of the extension test below."""
        assert survey.total_md == pytest.approx(EXPECTED_LAST_STATION_MD)
        assert survey.total_tvd == pytest.approx(
            EXPECTED_LAST_STATION_TVD, abs=TVD_TOLERANCE_FT
        )

    def test_is_deviated_not_horizontal(self, survey):
        assert 30.0 < survey.max_inclination_deg < 40.0

    def test_doglegs_are_plausible(self, survey):
        """A units error in the survey shows up here first."""
        assert survey.max_dogleg_severity < 5.0

    def test_shoe_tvd(self, survey):
        assert survey.tvd_at(SHOE_MD_FT) == pytest.approx(
            EXPECTED_SHOE_TVD, abs=TVD_TOLERANCE_FT
        )


class TestSurveyExtension:
    def test_projects_to_bit_depth(self, survey):
        extended = survey.extended_to(BIT_MD_FT)
        assert extended.total_md == pytest.approx(BIT_MD_FT)
        assert extended.tvd_at(BIT_MD_FT) == pytest.approx(
            EXPECTED_BIT_TVD, abs=TVD_TOLERANCE_FT
        )

    def test_holds_the_last_inclination(self, survey):
        extended = survey.extended_to(BIT_MD_FT)
        assert extended.stations[-1].inclination_deg == pytest.approx(
            survey.stations[-1].inclination_deg
        )

    def test_tvd_gained_matches_the_tangent(self, survey):
        """The whole basis of the projection, checked by hand."""
        extended = survey.extended_to(BIT_MD_FT)
        last = survey.stations[-1]
        span = BIT_MD_FT - last.md
        expected = last.tvd + span * math.cos(math.radians(last.inclination_deg))
        assert extended.tvd_at(BIT_MD_FT) == pytest.approx(expected)

    def test_does_not_disturb_the_surveyed_interval(self, survey):
        extended = survey.extended_to(BIT_MD_FT)
        for depth in (0.0, 2000.0, SHOE_MD_FT, 12000.0, EXPECTED_LAST_STATION_MD):
            assert extended.tvd_at(depth) == pytest.approx(survey.tvd_at(depth))

    def test_shallower_target_is_a_no_op(self, survey):
        assert survey.extended_to(5000.0) is survey

    def test_refuses_to_guess_across_a_large_gap(self, survey):
        with pytest.raises(ValueError, match="unsurveyed hole"):
            survey.extended_to(BIT_MD_FT + 1000.0)


class TestTallyImport:
    def test_total_length_matches_the_bit_depth(self, tally):
        """The Item_No regression: this read 2,554,260 ft when it was broken."""
        assert tally.total_length_ft == pytest.approx(BIT_MD_FT, abs=0.5)

    def test_reads_every_component(self, tally):
        assert len(tally.components) == 405

    def test_does_not_mistake_a_row_index_for_a_joint_count(self, tally):
        assert "count" not in tally.columns_used

    def test_cross_checks_against_the_cumulative_column(self, tally):
        assert tally.columns_used["cumulative check"] == "Cum_Length_ft"

    def test_internal_volume(self, tally):
        assert tally.internal_volume_bbl == pytest.approx(
            EXPECTED_STRING_VOLUME_BBL, abs=0.1
        )

    def test_bottom_up_order_puts_the_bit_first(self, tally):
        assert "bit" in tally.components[0].name.lower()

    def test_the_tally_is_joint_by_joint(self, tally):
        """405 rows for 12,500 ft means individual joints, not aggregated runs."""
        longest = max(tally.components, key=lambda c: c.length_ft)
        assert longest.length_ft < 50.0

    def test_drill_pipe_is_the_bulk_of_the_string(self, tally):
        drill_pipe_ft = sum(
            c.length_ft for c in tally.components if "drill pipe" in c.name.lower()
        )
        assert drill_pipe_ft > 0.5 * BIT_MD_FT


class TestKillSheetAgainstTheAnswerKey:
    """The physics, checked against numbers this library did not produce."""

    def test_hydrostatic_at_the_bit(self, bit_tvd):
        from wellcontrol.hydrostatics import hydrostatic_pressure

        assert hydrostatic_pressure(MUD_WEIGHT_PPG, bit_tvd) == pytest.approx(
            EXPECTED_HYDROSTATIC_PSI, abs=0.05
        )

    def test_bottomhole_pressure(self, bit_tvd):
        from wellcontrol.hydrostatics import hydrostatic_pressure

        bhp = hydrostatic_pressure(MUD_WEIGHT_PPG, bit_tvd) + SIDPP_PSI
        assert bhp == pytest.approx(EXPECTED_BHP_PSI, abs=0.05)

    def test_kill_mud_weight_before_rounding(self, bit_tvd):
        from wellcontrol.hydrostatics import hydrostatic_pressure

        bhp = hydrostatic_pressure(MUD_WEIGHT_PPG, bit_tvd) + SIDPP_PSI
        assert bhp / (0.052 * bit_tvd) == pytest.approx(
            EXPECTED_KMW_EXACT_PPG, abs=0.0005
        )

    def test_kill_mud_weight_rounds_up_to_the_tenth(self, bit_tvd):
        """13.0558 is 13.1 on a kill sheet, never 13.0."""
        from wellcontrol import rounding

        assert rounding.kill_mud_weight(EXPECTED_KMW_EXACT_PPG) == pytest.approx(13.1)

    def test_final_circulating_pressure(self):
        exact = SCR_PSI * EXPECTED_KMW_EXACT_PPG / MUD_WEIGHT_PPG
        assert exact == pytest.approx(EXPECTED_FCP_EXACT_PSI, abs=0.05)

    def test_maasp_at_current_mud_weight(self, shoe_tvd):
        maasp = (FRAC_PPG - MUD_WEIGHT_PPG) * 0.052 * shoe_tvd
        assert maasp == pytest.approx(EXPECTED_MAASP_CURRENT_PSI, abs=0.05)


class TestFullPipeline:
    """Survey plus tally through build_well and out the other side as a plan."""

    @pytest.fixture(scope="module")
    def well(self, survey, tally):
        import sys

        app_dir = Path(__file__).resolve().parent.parent / "app"
        if str(app_dir) not in sys.path:
            sys.path.insert(0, str(app_dir))
        import shared
        from wellcontrol.wellconfig import BOPLocation, WellConfiguration

        trajectory = shared.trajectory_from_survey(survey)
        config = WellConfiguration(BOPLocation.SURFACE, trajectory)
        values = dict(shared.DEFAULTS[config.key])
        values.update(
            total_md=BIT_MD_FT, bit_md=BIT_MD_FT, shoe_md=SHOE_MD_FT,
            mw=MUD_WEIGHT_PPG, frac=FRAC_PPG,
            sidpp=SIDPP_PSI, sicp=776.0, pit_gain=22.0,
            scr_psi=SCR_PSI, scr_spm=30.0,
            hole_id=8.5, casing_id=8.681,
            liner_id=6.5, stroke_len=12.0, pump_eff=0.95, pump_kind="triplex",
            riser_id=19.5, rod_od=0.0, safety=0.0, stand_length=93.0,
            migration=0.0,
        )
        return shared.build_well(
            config, values,
            survey_override=survey,
            string_components=tally.components,
        )

    def test_the_survey_is_classified_as_deviated(self, survey):
        import sys

        app_dir = Path(__file__).resolve().parent.parent / "app"
        if str(app_dir) not in sys.path:
            sys.path.insert(0, str(app_dir))
        import shared
        from wellcontrol.wellconfig import Trajectory

        assert shared.trajectory_from_survey(survey) is Trajectory.DEVIATED

    def test_defaults_exist_for_every_trajectory(self):
        """A survey can classify a well into any of the three."""
        import sys

        app_dir = Path(__file__).resolve().parent.parent / "app"
        if str(app_dir) not in sys.path:
            sys.path.insert(0, str(app_dir))
        import shared
        from wellcontrol.wellconfig import BOPLocation, Trajectory, WellConfiguration

        for bop in BOPLocation:
            for trajectory in Trajectory:
                config = WellConfiguration(bop, trajectory)
                assert config.key in shared.DEFAULTS

    def test_survey_is_extended_to_the_bit(self, well):
        assert well.survey.total_md == pytest.approx(BIT_MD_FT)
        assert well.bit_tvd_ft == pytest.approx(
            EXPECTED_BIT_TVD, abs=TVD_TOLERANCE_FT
        )

    def test_annulus_volume(self, well):
        assert well.annulus.volume_bbl == pytest.approx(
            EXPECTED_ANNULUS_VOLUME_BBL, abs=0.5
        )

    def test_formation_pressure(self, well):
        assert well.formation_pressure_psi == pytest.approx(
            EXPECTED_BHP_PSI, abs=1.0
        )

    def test_kill_mud_weight(self, well):
        assert well.kill_mud_weight_exact_ppg == pytest.approx(
            EXPECTED_KMW_EXACT_PPG, abs=0.001
        )
        assert well.kill_mud_weight_ppg == pytest.approx(13.1)

    def test_drillers_method_plans_without_error(self, well):
        from wellcontrol.methods import get_method

        plan = get_method("drillers").plan(well)
        assert plan.stages
        assert plan.peak_shoe_pressure_psi < plan.shoe_frac_pressure_psi

    def test_stroke_counts_match_the_answer_key(self, well):
        from wellcontrol.methods import get_method

        summary = get_method("drillers").plan(well).summary
        # Strokes round up -- you cannot pump a fraction of one.
        assert summary["Strokes to bit"] == math.ceil(EXPECTED_STROKES_TO_BIT)
        assert summary["Strokes bit to surface"] == math.ceil(
            EXPECTED_STROKES_BIT_TO_SURFACE
        )

    def test_every_method_reports_applicability(self, well):
        from wellcontrol.methods import METHODS

        for method in METHODS:
            applicability = method.applicability(well)
            if not applicability.usable:
                assert applicability.blockers, method.name

    def test_bit_on_bottom_blocks_stripping(self, well):
        from wellcontrol.methods import get_method

        applicability = get_method("stripping").applicability(well)
        assert not applicability.usable
