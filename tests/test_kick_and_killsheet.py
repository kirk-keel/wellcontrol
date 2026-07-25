"""Shut-in analysis and kill sheet tests."""

import pytest

from wellcontrol import examples
from wellcontrol.kick import (
    ShutInAnalysis,
    classify_influx,
    gas_expansion_boyle,
    gas_migration_rate_ft_per_hr,
    pressure_after_expansion,
)
from wellcontrol.killsheet import SlowCirculatingRate


def _vertical_shut_in(**overrides) -> ShutInAnalysis:
    annulus, survey = examples.vertical_land_well()
    kwargs = dict(
        sidpp_psi=400.0,
        sicp_psi=660.0,
        pit_gain_bbl=20.0,
        mud_weight_ppg=9.6,
        annulus=annulus,
        survey=survey,
    )
    kwargs.update(overrides)
    return ShutInAnalysis(**kwargs)


# --------------------------------------------------------------------------
# Shut-in analysis
# --------------------------------------------------------------------------

class TestShutInAnalysis:
    def test_formation_pressure(self):
        """Pf = SIDPP + 0.052 x MW x TVD = 400 + 4992 = 5392 psi"""
        assert _vertical_shut_in().formation_pressure_psi == pytest.approx(5392.0)

    def test_formation_pressure_as_emw(self):
        """5392 / (0.052 x 10000) = 10.369 ppg"""
        assert _vertical_shut_in().formation_pressure_emw_ppg == (
            pytest.approx(10.369, abs=0.001)
        )

    def test_influx_height_spans_the_collar_annulus(self):
        """600 ft of collar annulus holds 17.486 bbl; the remaining 2.514 bbl
        occupies 54.77 ft above. Total 654.77 ft.
        """
        assert _vertical_shut_in().influx_height_md_ft == pytest.approx(
            654.77, abs=0.1
        )

    def test_influx_top(self):
        assert _vertical_shut_in().influx_top_md_ft == pytest.approx(9345.2, abs=0.1)

    def test_influx_gradient(self):
        """0.052 x 9.6 - (660 - 400) / 654.77
        = 0.4992 - 0.39708 = 0.10212 psi/ft
        """
        assert _vertical_shut_in().influx_gradient_psi_per_ft == (
            pytest.approx(0.10212, abs=0.0001)
        )

    def test_influx_density_identifies_gas(self):
        """0.10212 / 0.052 = 1.96 ppg -- gas."""
        analysis = _vertical_shut_in()
        assert analysis.influx_density_ppg == pytest.approx(1.964, abs=0.01)
        assert analysis.influx_type == "gas"

    def test_underbalance_equals_sidpp(self):
        assert _vertical_shut_in().underbalance_psi == pytest.approx(400.0)

    def test_summary_has_no_missing_values(self):
        summary = _vertical_shut_in().summary()
        assert summary["Formation pressure (psi)"] == pytest.approx(5392.0)
        assert summary["Influx type"] == "gas"


class TestShutInValidation:
    def test_clean_readings_pass(self):
        assert _vertical_shut_in().validate() == []

    def test_sicp_below_sidpp_is_flagged(self):
        warnings = _vertical_shut_in(sicp_psi=300.0).validate()
        assert any("below SIDPP" in w for w in warnings)

    def test_pressure_with_no_pit_gain_is_flagged(self):
        warnings = _vertical_shut_in(pit_gain_bbl=0.0).validate()
        assert any("no pit gain" in w for w in warnings)

    def test_negative_pit_gain_is_rejected(self):
        with pytest.raises(ValueError, match="Pit gain cannot be negative"):
            _vertical_shut_in(pit_gain_bbl=-5.0)

    def test_influx_denser_than_mud_is_flagged(self):
        """Casing pressure below drill pipe pressure implies an influx heavier
        than the mud, so both warnings fire together. They are two symptoms of
        the same bad reading.
        """
        warnings = _vertical_shut_in(sicp_psi=300.0).validate()
        assert any("heavier than" in w for w in warnings)
        assert any("below SIDPP" in w for w in warnings)

    def test_influx_spanning_the_collar_annulus_is_reported(self):
        """A 20 bbl influx is taller than the 600 ft collar annulus, so it
        occupies two capacities. Not an error -- but it is why the influx
        height cannot be found with a single capacity.
        """
        assert _vertical_shut_in().spans_annular_geometry_change is True
        assert _vertical_shut_in(pit_gain_bbl=5.0).spans_annular_geometry_change is (
            False
        )


class TestHorizontalShutIn:
    def test_influx_in_the_lateral_has_no_vertical_height(self):
        annulus, survey = examples.horizontal_well()
        analysis = ShutInAnalysis(
            sidpp_psi=350.0,
            sicp_psi=380.0,
            pit_gain_bbl=15.0,
            mud_weight_ppg=10.2,
            annulus=annulus,
            survey=survey,
        )
        assert analysis.influx_height_md_ft > 400.0
        assert analysis.influx_height_tvd_ft == pytest.approx(0.0, abs=1.0)

    def test_density_is_indeterminate_in_a_lateral(self):
        annulus, survey = examples.horizontal_well()
        analysis = ShutInAnalysis(
            sidpp_psi=350.0,
            sicp_psi=380.0,
            pit_gain_bbl=15.0,
            mud_weight_ppg=10.2,
            annulus=annulus,
            survey=survey,
        )
        with pytest.raises(ValueError, match="no vertical height"):
            _ = analysis.influx_gradient_psi_per_ft
        assert analysis.influx_type == "indeterminate (no vertical height)"

    def test_formation_pressure_uses_tvd_not_md(self):
        """350 + 0.052 x 10.2 x 5909.86 = 350 + 3134.6 = 3484.6 psi.
        Using 12000 ft MD would give 6710 psi -- almost double.
        """
        annulus, survey = examples.horizontal_well()
        analysis = ShutInAnalysis(
            350.0, 380.0, 15.0, 10.2, annulus, survey
        )
        assert analysis.formation_pressure_psi == pytest.approx(3484.6, abs=1.0)


# --------------------------------------------------------------------------
# Gas behaviour
# --------------------------------------------------------------------------

class TestGas:
    def test_classification_bands(self):
        assert classify_influx(0.5) == "gas"
        assert classify_influx(2.0) == "gas"
        assert classify_influx(5.5) == "oil or mixed gas/liquid"
        assert classify_influx(8.6) == "salt water"

    def test_migration_rate(self):
        """100 psi/hr of pressure rise in 9.6 ppg mud
        = 100 / (0.052 x 9.6) = 200 ft/hr
        """
        assert gas_migration_rate_ft_per_hr(100.0, 9.6) == pytest.approx(
            200.32, abs=0.1
        )

    def test_boyle_uses_absolute_pressure(self):
        """20 bbl at 5000 psig taken to 1000 psig:
        (5014.7 x 20) / 1014.7 = 98.8 bbl
        """
        assert gas_expansion_boyle(5000.0, 20.0, 1000.0) == pytest.approx(
            98.83, abs=0.1
        )

    def test_expansion_near_surface_is_violent(self):
        """The same bubble taken from 100 psig to 0 psig grows almost 8x --
        which is why the choke is busiest in the last few hundred strokes.
        """
        result = gas_expansion_boyle(100.0, 1.0, 0.0)
        assert result == pytest.approx(7.80, abs=0.05)

    def test_temperature_correction_shrinks_a_cooling_bubble(self):
        hot = gas_expansion_boyle(5000.0, 20.0, 1000.0, t1_f=250.0, t2_f=250.0)
        cooled = gas_expansion_boyle(5000.0, 20.0, 1000.0, t1_f=250.0, t2_f=100.0)
        assert cooled < hot

    def test_pressure_after_expansion_inverts_boyle(self):
        volume = gas_expansion_boyle(5000.0, 20.0, 1000.0)
        assert pressure_after_expansion(5000.0, 20.0, volume) == pytest.approx(
            1000.0, abs=0.1
        )


# --------------------------------------------------------------------------
# Kill sheet
# --------------------------------------------------------------------------

class TestVerticalKillSheet:
    def test_kill_mud_weight(self):
        """9.6 + 400 / (0.052 x 10000) = 9.6 + 0.7692 = 10.369 ppg"""
        sheet = examples.vertical_land_well_kill_sheet()
        assert sheet.kill_mud_weight_ppg == pytest.approx(10.3692, abs=0.0001)

    def test_icp(self):
        """SIDPP + SCR = 400 + 600 = 1000 psi"""
        sheet = examples.vertical_land_well_kill_sheet()
        assert sheet.initial_circulating_pressure_psi == pytest.approx(1000.0)

    def test_fcp(self):
        """SCR x KMW / OMW = 600 x 10.3692 / 9.6 = 648.08 psi"""
        sheet = examples.vertical_land_well_kill_sheet()
        assert sheet.final_circulating_pressure_psi == pytest.approx(648.08, abs=0.01)

    def test_strokes_to_bit(self):
        """171.573 bbl / 0.1170410 bbl/stk = 1465.9 strokes"""
        sheet = examples.vertical_land_well_kill_sheet()
        assert sheet.strokes_to_bit == pytest.approx(1465.9, abs=0.5)

    def test_strokes_bit_to_surface(self):
        """470.095 bbl / 0.1170410 = 4016.5 strokes"""
        sheet = examples.vertical_land_well_kill_sheet()
        assert sheet.strokes_bit_to_surface == pytest.approx(4016.5, abs=0.5)

    def test_total_strokes_is_the_sum(self):
        sheet = examples.vertical_land_well_kill_sheet()
        assert sheet.total_strokes == pytest.approx(
            sheet.strokes_to_bit + sheet.strokes_bit_to_surface
        )

    def test_time_at_kill_rate(self):
        """5482 strokes at 30 spm = about 183 minutes."""
        sheet = examples.vertical_land_well_kill_sheet()
        assert sheet.total_minutes() == pytest.approx(182.7, abs=1.0)

    def test_safety_factor_raises_kill_mud_weight(self):
        annulus, survey = examples.vertical_land_well()
        from wellcontrol.killsheet import KillSheet

        sheet = KillSheet(
            sidpp_psi=400.0,
            sicp_psi=660.0,
            pit_gain_bbl=20.0,
            mud_weight_ppg=9.6,
            annulus=annulus,
            survey=survey,
            pump=examples.standard_pump(),
            slow_circulating_rate=SlowCirculatingRate(30.0, 600.0),
            safety_factor_ppg=0.3,
        )
        assert sheet.kill_mud_weight_ppg == pytest.approx(10.6692, abs=0.0001)


class TestSchedules:
    def test_linear_schedule_endpoints(self):
        sheet = examples.vertical_land_well_kill_sheet()
        schedule = sheet.schedule_linear(steps=10)
        assert schedule[0].drill_pipe_pressure_psi == pytest.approx(1000.0)
        assert schedule[-1].drill_pipe_pressure_psi == pytest.approx(648.08, abs=0.01)
        assert schedule[-1].strokes == pytest.approx(sheet.strokes_to_bit)

    def test_depth_schedule_matches_at_the_endpoints(self):
        """Both methods must agree at ICP and FCP -- they only differ in
        between.
        """
        sheet = examples.vertical_land_well_kill_sheet()
        linear = sheet.schedule_linear(steps=10)
        by_depth = sheet.schedule_by_depth(steps=10)
        assert by_depth[0].drill_pipe_pressure_psi == pytest.approx(
            linear[0].drill_pipe_pressure_psi, abs=0.01
        )
        assert by_depth[-1].drill_pipe_pressure_psi == pytest.approx(
            linear[-1].drill_pipe_pressure_psi, abs=0.01
        )

    def test_schedules_diverge_in_the_middle(self):
        """The collars hold only 4.6 bbl but span 600 ft, so equal stroke
        increments do not buy equal depth. The straight line is an
        approximation and this shows by how much.
        """
        sheet = examples.vertical_land_well_kill_sheet()
        linear = sheet.schedule_linear(steps=10)
        by_depth = sheet.schedule_by_depth(steps=10)
        differences = [
            abs(a.drill_pipe_pressure_psi - b.drill_pipe_pressure_psi)
            for a, b in zip(linear, by_depth)
        ]
        assert max(differences) > 0.5

    def test_pressure_falls_monotonically(self):
        sheet = examples.vertical_land_well_kill_sheet()
        for schedule in (sheet.schedule_linear(20), sheet.schedule_by_depth(20)):
            pressures = [s.drill_pipe_pressure_psi for s in schedule]
            assert pressures == sorted(pressures, reverse=True)

    def test_kill_mud_reaches_the_bit_at_the_end(self):
        sheet = examples.vertical_land_well_kill_sheet()
        schedule = sheet.schedule_by_depth(steps=10)
        assert schedule[-1].kill_mud_md_ft == pytest.approx(10000.0, abs=1.0)

    def test_zero_steps_is_rejected(self):
        sheet = examples.vertical_land_well_kill_sheet()
        with pytest.raises(ValueError, match="at least one step"):
            sheet.schedule_linear(steps=0)

    def test_format_schedule_renders(self):
        sheet = examples.vertical_land_well_kill_sheet()
        text = sheet.format_schedule(sheet.schedule_by_depth(steps=5))
        assert "Kill mud at the bit" in text
        assert len(text.splitlines()) == 8  # header + rule + 6 rows


class TestMethods:
    def test_wait_and_weight_is_one_circulation(self):
        sheet = examples.vertical_land_well_kill_sheet()
        stages = sheet.wait_and_weight()
        circulating = sum(s.strokes for s in stages)
        assert circulating == pytest.approx(sheet.total_strokes, abs=1.0)

    def test_drillers_is_two_circulations(self):
        """One circulation to remove the influx, then a full circulation to
        displace to kill mud: roughly twice the pumping.
        """
        sheet = examples.vertical_land_well_kill_sheet()
        stages = sheet.drillers_method()
        total = sum(s.strokes for s in stages)
        assert total == pytest.approx(
            sheet.total_strokes + sheet.strokes_bit_to_surface, abs=1.0
        )
        assert total > sheet.total_strokes

    def test_drillers_first_circulation_holds_icp(self):
        sheet = examples.vertical_land_well_kill_sheet()
        first = sheet.drillers_method()[0]
        assert "1000" in first.description

    def test_both_methods_reach_the_same_kill_mud_weight(self):
        sheet = examples.vertical_land_well_kill_sheet()
        assert "10.4" in sheet.wait_and_weight()[0].description
        assert "10.4" in sheet.drillers_method()[1].description


class TestHorizontalKillSheet:
    def test_kill_mud_weight_uses_tvd(self):
        """350 psi over 5909.86 ft TVD needs 1.139 ppg, giving 11.34 ppg.
        Using the 12000 ft MD would give only 10.76 ppg and the well would
        stay alive.
        """
        sheet = examples.horizontal_well_kill_sheet()
        assert sheet.kill_mud_weight_ppg == pytest.approx(11.339, abs=0.005)

        wrong = 10.2 + 350.0 / (0.052 * 12000.0)
        assert wrong == pytest.approx(10.761, abs=0.005)
        assert sheet.kill_mud_weight_ppg - wrong > 0.5

    def test_bit_tvd_is_far_above_bit_md(self):
        sheet = examples.horizontal_well_kill_sheet()
        assert sheet.bit_md_ft == pytest.approx(12000.0)
        assert sheet.bit_tvd_ft == pytest.approx(5909.86, abs=0.5)


class TestSlowCirculatingRate:
    def test_scaling_is_quadratic(self):
        """600 psi at 30 spm scaled to 60 spm: 600 x 2^2 = 2400 psi"""
        scr = SlowCirculatingRate(spm=30.0, pressure_psi=600.0)
        assert scr.scaled_to(60.0) == pytest.approx(2400.0)

    def test_scaling_down(self):
        scr = SlowCirculatingRate(spm=60.0, pressure_psi=2400.0)
        assert scr.scaled_to(30.0) == pytest.approx(600.0)

    def test_zero_reference_spm_is_rejected(self):
        with pytest.raises(ValueError, match="must be positive"):
            SlowCirculatingRate(spm=0.0, pressure_psi=600.0).scaled_to(30.0)
