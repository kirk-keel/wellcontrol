"""Well control rounding rules.

Rounding here is directional, not to-nearest, and every direction is the one
that adds margin. These tests pin the direction down, and pin down the float
handling -- a naive ceil on 10.4 gives 10.5, because 10.4 * 10 is
104.00000000000001 in binary.
"""

import pytest

from wellcontrol import examples, rounding
from wellcontrol.methods import plan_kill
from wellcontrol.wellconfig import BOPLocation, Trajectory, WellConfiguration

SV = WellConfiguration(BOPLocation.SURFACE, Trajectory.VERTICAL)


class TestKillMudWeight:
    def test_rounds_up_to_a_tenth(self):
        assert rounding.kill_mud_weight(10.37) == pytest.approx(10.4)

    def test_rounds_up_even_from_just_above(self):
        assert rounding.kill_mud_weight(10.301) == pytest.approx(10.4)

    def test_leaves_an_exact_tenth_alone(self):
        """10.4 * 10 is 104.00000000000001; a naive ceil would give 10.5."""
        assert rounding.kill_mud_weight(10.4) == pytest.approx(10.4)

    @pytest.mark.parametrize("value", [9.0, 9.1, 10.0, 12.5, 16.8, 18.0])
    def test_exact_tenths_are_never_pushed_up(self, value):
        assert rounding.kill_mud_weight(value) == pytest.approx(value)

    def test_never_rounds_down(self):
        for value in (10.31, 10.35, 10.39, 10.399):
            assert rounding.kill_mud_weight(value) >= value


class TestMaxAllowableMudWeight:
    def test_rounds_down_to_a_tenth(self):
        assert rounding.max_allowable_mud_weight(12.87) == pytest.approx(12.8)

    def test_leaves_an_exact_tenth_alone(self):
        assert rounding.max_allowable_mud_weight(12.8) == pytest.approx(12.8)

    def test_never_rounds_up(self):
        for value in (12.81, 12.85, 12.89, 12.899):
            assert rounding.max_allowable_mud_weight(value) <= value

    def test_opposite_direction_from_the_kill_weight(self):
        """One is a target, the other a limit."""
        value = 12.87
        assert rounding.kill_mud_weight(value) > value
        assert rounding.max_allowable_mud_weight(value) < value


class TestPressure:
    def test_limit_rounds_down(self):
        assert rounding.pressure_limit(1181.6) == 1181

    def test_limit_returns_an_int(self):
        assert isinstance(rounding.pressure_limit(1181.6), int)

    def test_limit_never_rounds_up(self):
        for value in (1181.1, 1181.5, 1181.9):
            assert rounding.pressure_limit(value) <= value

    def test_plain_pressure_rounds_to_nearest(self):
        assert rounding.pressure(1000.4) == 1000
        assert rounding.pressure(1000.6) == 1001

    def test_no_decimal_places_anywhere(self):
        assert isinstance(rounding.pressure(1000.4), int)
        assert isinstance(rounding.pressure_step(51.6), int)


class TestPressureStep:
    def test_rounds_down(self):
        """51.6 psi per step is worked as 51."""
        assert rounding.pressure_step(51.6) == 51

    def test_never_rounds_up(self):
        for value in (51.1, 51.5, 51.9):
            assert rounding.pressure_step(value) <= value

    def test_exact_value_is_unchanged(self):
        assert rounding.pressure_step(35.0) == 35

    def test_flooring_leaves_the_schedule_above_fcp(self):
        """Ten floored steps come up short of the full span, which leaves
        slightly more pressure on the well than planned. That is the right way
        for the error to fall.
        """
        sheet = examples.vertical_land_well_kill_sheet()
        span = (
            sheet.initial_circulating_pressure_psi
            - sheet.final_circulating_pressure_psi
        )
        assert sheet.pressure_step_for(10) * 10 <= span


class TestStrokes:
    def test_rounds_up(self):
        assert rounding.strokes(1465.1) == 1466

    def test_whole_number_is_unchanged(self):
        assert rounding.strokes(1466.0) == 1466

    def test_returns_an_int(self):
        assert isinstance(rounding.strokes(1465.1), int)

    def test_never_rounds_down(self):
        for value in (1465.01, 1465.5, 1465.99):
            assert rounding.strokes(value) >= value

    def test_no_fractional_strokes_in_a_schedule(self):
        sheet = examples.vertical_land_well_kill_sheet()
        for step in sheet.schedule_by_depth(steps=10):
            assert step.strokes == int(step.strokes)


class TestAppliedEndToEnd:
    def test_kill_sheet_reports_both_weights(self):
        summary = examples.vertical_land_well_kill_sheet().summary()
        assert summary["Kill mud weight, calculated (ppg)"] == pytest.approx(
            10.369, abs=0.001
        )
        assert summary["Kill mud weight, as mixed (ppg)"] == pytest.approx(10.4)

    def test_plan_summary_uses_whole_psi(self):
        summary = plan_kill(examples.well_state(SV), "wait_and_weight").summary
        for key in ("Formation pressure (psi)", "ICP (psi)", "FCP (psi)"):
            assert isinstance(summary[key], int), key

    def test_plan_summary_uses_whole_strokes(self):
        summary = plan_kill(examples.well_state(SV), "wait_and_weight").summary
        for key in ("Strokes to bit", "Strokes bit to surface"):
            assert isinstance(summary[key], int), key

    def test_maasp_in_summary_is_a_whole_number(self):
        summary = plan_kill(examples.well_state(SV), "drillers").summary
        assert isinstance(summary["MAASP at kill mud weight (psi)"], int)

    def test_mamw_reported(self):
        summary = plan_kill(examples.well_state(SV), "drillers").summary
        assert summary["MAMW at shoe (ppg)"] == pytest.approx(12.8)

    def test_fcp_is_built_from_the_mixed_weight(self):
        """600 x 10.4 / 9.6 = 650, not 600 x 10.3692 / 9.6 = 648."""
        sheet = examples.vertical_land_well_kill_sheet()
        assert sheet.final_circulating_pressure_psi == pytest.approx(650.0)

    def test_rounding_overbalance_is_real_and_positive(self):
        sheet = examples.vertical_land_well_kill_sheet()
        assert sheet.rounding_overbalance_psi == pytest.approx(16.0, abs=0.5)
        assert sheet.balanced_final_pressure_psi < (
            sheet.final_circulating_pressure_psi
        )
