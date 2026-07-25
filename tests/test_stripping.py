"""Stripping and snubbing tests.

Expected values are worked out in the docstrings so they can be checked without
running the code.
"""

import pytest

from wellcontrol import examples
from wellcontrol.methods import plan_kill
from wellcontrol.stripping import (
    ANNULAR_STRIPPING_LIMIT_PSI,
    StripDirection,
    StripTechnique,
    StrippingOperation,
    balance_point_length_ft,
    buoyancy_factor,
    pipe_weight_in_mud_lbf,
    pressure_rise_if_not_bled,
    snub_force_lbf,
    surge_pressure_estimate,
    upward_force_lbf,
)
from wellcontrol.wellconfig import BOPLocation, Trajectory, WellConfiguration

CONFIGS = WellConfiguration.standard()
CONFIG_IDS = [c.key for c in CONFIGS]
SURFACE_VERTICAL = WellConfiguration(BOPLocation.SURFACE, Trajectory.VERTICAL)
SURFACE_HORIZONTAL = WellConfiguration(BOPLocation.SURFACE, Trajectory.HORIZONTAL)


def _operation(**overrides) -> StrippingOperation:
    kwargs = dict(
        pipe_od_in=5.0,
        pipe_id_in=4.276,
        pipe_weight_lb_per_ft=19.5,
        stand_length_ft=93.0,
        start_depth_md_ft=8500.0,
        target_depth_md_ft=10000.0,
        annular_capacity_bbl_per_ft=0.070186,
        mud_weight_ppg=9.6,
        surface_pressure_psi=400.0,
    )
    kwargs.update(overrides)
    return StrippingOperation(**kwargs)


# --------------------------------------------------------------------------
# Displacement
# --------------------------------------------------------------------------

class TestDisplacement:
    def test_closed_end_is_used_with_a_float(self):
        """5 in OD closed end: 25 / 1029.4 = 0.0242859 bbl/ft"""
        assert _operation().displacement_bbl_per_ft == pytest.approx(
            0.0242859, abs=1e-7
        )

    def test_open_ended_is_much_smaller(self):
        """(25 - 18.284176) / 1029.4 = 6.715824 / 1029.4 = 0.0065240 bbl/ft.

        Against the closed-end 0.0242859, a factor of 3.72.
        """
        operation = _operation()
        assert operation.open_ended_displacement_bbl_per_ft == pytest.approx(
            0.0065240, abs=1e-7
        )
        ratio = (
            operation.displacement_bbl_per_ft
            / operation.open_ended_displacement_bbl_per_ft
        )
        assert ratio == pytest.approx(3.72, abs=0.02)

    def test_without_a_float_the_steel_figure_applies(self):
        operation = _operation(has_float=False)
        assert operation.displacement_bbl_per_ft == pytest.approx(
            0.0065240, abs=1e-7
        )

    def test_volume_per_stand(self):
        """0.0242859 x 93 = 2.2586 bbl"""
        assert _operation().volume_per_stand_bbl == pytest.approx(2.2586, abs=0.001)

    def test_stands_required_rounds_up(self):
        """1500 / 93 = 16.13, so 17 stands."""
        assert _operation().stands_required == 17

    def test_total_displacement(self):
        """0.0242859 x 1500 = 36.43 bbl"""
        assert _operation().total_displacement_bbl == pytest.approx(36.43, abs=0.01)

    def test_larger_pipe_displaces_more(self):
        assert (
            _operation(pipe_od_in=6.5).displacement_bbl_per_ft
            > _operation(pipe_od_in=5.0).displacement_bbl_per_ft
        )


# --------------------------------------------------------------------------
# Migration allowance
# --------------------------------------------------------------------------

class TestMigrationAllowance:
    def test_no_allowance_when_gas_is_not_migrating(self):
        assert _operation().migration_bleed_per_stand_bbl == pytest.approx(0.0)

    def test_migration_distance_per_stand(self):
        """1000 ft/hr for 6 minutes = 100 ft"""
        operation = _operation(migration_rate_ft_per_hr=1000.0, minutes_per_stand=6.0)
        assert operation.migration_per_stand_ft == pytest.approx(100.0)

    def test_migration_bleed_is_the_swept_volume(self):
        """100 ft x 0.070186 bbl/ft = 7.019 bbl.

        The mud weight cancels: the pressure rise from migration is
        0.052 x MW x d, and removing it needs a mud column of the same height,
        which is d x capacity of volume.
        """
        operation = _operation(migration_rate_ft_per_hr=1000.0, minutes_per_stand=6.0)
        assert operation.migration_bleed_per_stand_bbl == pytest.approx(
            7.019, abs=0.01
        )

    def test_migration_can_dominate_the_pipe_displacement(self):
        """At 1000 ft/hr the migration allowance is three times the pipe
        displacement. Bleeding only the displacement would let the well gain
        pressure steadily.
        """
        operation = _operation(migration_rate_ft_per_hr=1000.0, minutes_per_stand=6.0)
        assert operation.migration_bleed_per_stand_bbl > (
            3 * operation.volume_per_stand_bbl
        )

    def test_total_bleed_is_the_sum(self):
        operation = _operation(migration_rate_ft_per_hr=1000.0, minutes_per_stand=6.0)
        assert operation.total_bleed_per_stand_bbl == pytest.approx(
            operation.volume_per_stand_bbl + operation.migration_bleed_per_stand_bbl
        )

    def test_migration_pressure_rise(self):
        """0.052 x 9.6 x 100 = 49.9 psi per stand"""
        operation = _operation(migration_rate_ft_per_hr=1000.0, minutes_per_stand=6.0)
        assert operation.migration_pressure_rise_per_stand_psi == pytest.approx(
            49.92, abs=0.1
        )

    def test_no_migration_allowance_when_stripping_out(self):
        operation = _operation(
            direction=StripDirection.OUT,
            start_depth_md_ft=10000.0,
            target_depth_md_ft=8500.0,
            migration_rate_ft_per_hr=1000.0,
        )
        assert operation.migration_bleed_per_stand_bbl == 0.0


# --------------------------------------------------------------------------
# Forces
# --------------------------------------------------------------------------

class TestForces:
    def test_buoyancy_factor(self):
        """1 - 9.6 / 65.5 = 0.8534"""
        assert buoyancy_factor(9.6) == pytest.approx(0.8534, abs=0.0005)

    def test_heavier_mud_buoys_more(self):
        assert buoyancy_factor(16.0) < buoyancy_factor(9.6)

    def test_mud_heavier_than_steel_is_rejected(self):
        with pytest.raises(ValueError, match="heavier than steel"):
            buoyancy_factor(70.0)

    def test_upward_force(self):
        """400 psi x (pi/4 x 25) = 400 x 19.635 = 7854 lbf"""
        assert upward_force_lbf(400.0, 5.0) == pytest.approx(7854.0, abs=1.0)

    def test_pipe_weight_in_mud(self):
        """1000 ft x 19.5 lb/ft x 0.8534 = 16642 lbf"""
        assert pipe_weight_in_mud_lbf(1000.0, 19.5, 9.6) == pytest.approx(
            16642.0, abs=5.0
        )

    def test_balance_point(self):
        """7854 / (19.5 x 0.8534) = 7854 / 16.642 = 472 ft"""
        assert balance_point_length_ft(400.0, 5.0, 19.5, 9.6) == pytest.approx(
            472.0, abs=1.0
        )

    def test_balance_point_scales_with_pressure(self):
        low = balance_point_length_ft(400.0, 5.0, 19.5, 9.6)
        high = balance_point_length_ft(800.0, 5.0, 19.5, 9.6)
        assert high == pytest.approx(2 * low, rel=0.001)

    def test_snub_force_positive_above_the_balance_point(self):
        """At 300 ft: 7854 - 300 x 16.642 = 2861 lbf still pushing up."""
        force = snub_force_lbf(400.0, 5.0, 300.0, 19.5, 9.6)
        assert force == pytest.approx(2861.0, abs=5.0)
        assert force > 0

    def test_snub_force_negative_below_the_balance_point(self):
        """At 600 ft the pipe outweighs the force and strips in."""
        assert snub_force_lbf(400.0, 5.0, 600.0, 19.5, 9.6) < 0

    def test_snubbing_required_for_a_shallow_bit(self):
        operation = _operation(
            start_depth_md_ft=300.0, target_depth_md_ft=1000.0
        )
        assert operation.snubbing_required

    def test_snubbing_not_required_for_a_deep_bit(self):
        assert not _operation().snubbing_required


# --------------------------------------------------------------------------
# Missing a bleed
# --------------------------------------------------------------------------

class TestPressureRise:
    def test_missing_one_stand(self):
        """P2 = 414.7 x 20 / (20 - 2.2586) - 14.7 = 452.8 psi

        From 400 psi, a single missed stand adds over 50 psi.
        """
        assert pressure_rise_if_not_bled(2.2586, 20.0, 400.0) == pytest.approx(
            452.8, abs=0.5
        )

    def test_rise_grows_as_gas_shrinks(self):
        """The less gas there is to compress, the worse a missed bleed is."""
        big = pressure_rise_if_not_bled(2.0, 40.0, 400.0)
        small = pressure_rise_if_not_bled(2.0, 10.0, 400.0)
        assert small > big

    def test_no_compressible_volume_is_rejected(self):
        with pytest.raises(ValueError, match="nothing compressible"):
            pressure_rise_if_not_bled(20.0, 5.0, 400.0)


# --------------------------------------------------------------------------
# Technique and schedule
# --------------------------------------------------------------------------

class TestTechnique:
    def test_annular_at_low_pressure(self):
        assert _operation(surface_pressure_psi=800.0).recommended_technique is (
            StripTechnique.ANNULAR
        )

    def test_ram_to_ram_above_the_rule_of_thumb(self):
        operation = _operation(
            surface_pressure_psi=ANNULAR_STRIPPING_LIMIT_PSI + 100.0
        )
        assert operation.recommended_technique is StripTechnique.RAM_TO_RAM


class TestSchedule:
    def test_one_row_per_stand(self):
        operation = _operation()
        assert len(operation.schedule()) == operation.stands_required

    def test_reaches_the_target_depth(self):
        operation = _operation()
        assert operation.schedule()[-1].pipe_depth_md_ft == pytest.approx(
            10000.0, abs=1.0
        )

    def test_depth_increases_monotonically(self):
        depths = [s.pipe_depth_md_ft for s in _operation().schedule()]
        assert depths == sorted(depths)

    def test_cumulative_bleed_matches_the_total(self):
        operation = _operation()
        assert operation.schedule()[-1].cumulative_bleed_bbl == pytest.approx(
            operation.total_displacement_bbl, rel=0.01
        )

    def test_stripping_out_moves_upward(self):
        operation = _operation(
            direction=StripDirection.OUT,
            start_depth_md_ft=10000.0,
            target_depth_md_ft=8500.0,
        )
        depths = [s.pipe_depth_md_ft for s in operation.schedule()]
        assert depths == sorted(depths, reverse=True)
        assert depths[-1] == pytest.approx(8500.0, abs=1.0)

    def test_wrong_direction_is_rejected(self):
        with pytest.raises(ValueError, match="not below the current depth"):
            _operation(start_depth_md_ft=10000.0, target_depth_md_ft=8500.0)

    def test_wrong_direction_out_is_rejected(self):
        with pytest.raises(ValueError, match="not above the current depth"):
            _operation(direction=StripDirection.OUT)


class TestSurge:
    def test_surge_rises_with_speed(self):
        mud = examples.standard_mud_rheology()
        slow = surge_pressure_estimate(60.0, 8.5, 5.0, 8000.0, mud, 9.6)
        fast = surge_pressure_estimate(180.0, 8.5, 5.0, 8000.0, mud, 9.6)
        assert 0 < slow < fast

    def test_bingham_needs_a_mud_weight(self):
        mud = examples.standard_mud_rheology()
        with pytest.raises(ValueError, match="needs mud_weight_ppg"):
            surge_pressure_estimate(60.0, 8.5, 5.0, 8000.0, mud)


# --------------------------------------------------------------------------
# Off-bottom pressure model
# --------------------------------------------------------------------------

class TestOffBottomPressures:
    def test_no_hydrostatic_below_a_bit_on_bottom(self):
        well = examples.well_state(SURFACE_VERTICAL)
        assert well.hydrostatic_below_bit_psi == pytest.approx(0.0)

    def test_hydrostatic_below_bit_is_counted_off_bottom(self):
        """The drill pipe gauge reads at the BIT. Off bottom the formation is
        deeper, and what lies between adds pressure the kill sheet would
        otherwise miss.
        """
        well = examples.well_state(SURFACE_VERTICAL, bit_off_bottom_ft=1500.0)
        assert well.hydrostatic_below_bit_psi > 500.0

    def test_formation_pressure_includes_it(self):
        well = examples.well_state(SURFACE_VERTICAL, bit_off_bottom_ft=1500.0)
        naive = well.sidpp_psi + 0.052 * well.mud_weight_ppg * well.bit_tvd_ft
        assert well.formation_pressure_psi > naive
        assert well.formation_pressure_psi == pytest.approx(
            naive + well.hydrostatic_below_bit_psi
        )

    def test_influx_below_the_bit_makes_the_gauges_equal(self):
        """Both gauges read through identical fluid to the bit and through
        identical fluid below it, so they must agree.
        """
        well = examples.well_state(SURFACE_VERTICAL, bit_off_bottom_ft=1500.0)
        assert well.influx_top_md_ft >= well.bit_md_ft
        assert well.sicp_psi == pytest.approx(well.sidpp_psi)

    def test_casing_pressure_is_positive_off_bottom(self):
        """Regression: ignoring the hydrostatic below the bit drove the
        computed casing pressure negative, and it clamped to zero.
        """
        well = examples.well_state(SURFACE_VERTICAL, bit_off_bottom_ft=1500.0)
        plan = plan_kill(well, "stripping")
        assert plan.trace[0].casing_psi > 100.0


# --------------------------------------------------------------------------
# The method
# --------------------------------------------------------------------------

class TestStrippingMethod:
    def test_blocked_when_the_bit_is_on_bottom(self):
        plan = plan_kill(examples.well_state(SURFACE_VERTICAL), "stripping")
        assert not plan.applicability.usable
        assert any("already on bottom" in b for b in plan.applicability.blockers)

    @pytest.mark.parametrize("config", CONFIGS, ids=CONFIG_IDS)
    def test_usable_off_bottom_on_every_configuration(self, config):
        well = examples.well_state(config, bit_off_bottom_ft=1500.0)
        plan = plan_kill(well, "stripping")
        assert plan.applicability.usable, plan.applicability.blockers

    @pytest.mark.parametrize("config", CONFIGS, ids=CONFIG_IDS)
    def test_always_warns_about_the_float(self, config):
        well = examples.well_state(config, bit_off_bottom_ft=1500.0)
        plan = plan_kill(well, "stripping")
        assert any("float" in w.lower() for w in plan.applicability.warnings)

    def test_bit_reaches_bottom(self):
        well = examples.well_state(SURFACE_VERTICAL, bit_off_bottom_ft=1500.0)
        plan = plan_kill(well, "stripping")
        assert plan.trace[-1].pipe_depth_md_ft == pytest.approx(
            well.hole_md_ft, abs=1.0
        )

    def test_trace_carries_pipe_depth(self):
        well = examples.well_state(SURFACE_VERTICAL, bit_off_bottom_ft=1500.0)
        plan = plan_kill(well, "stripping")
        assert all(p.pipe_depth_md_ft is not None for p in plan.trace)

    def test_surface_pressure_climbs_as_gas_migrates(self):
        well = examples.well_state(SURFACE_VERTICAL, bit_off_bottom_ft=1500.0)
        plan = plan_kill(well, "stripping")
        assert plan.trace[-1].casing_psi > plan.trace[0].casing_psi

    def test_no_migration_means_steady_pressure(self):
        well = examples.well_state(SURFACE_VERTICAL, bit_off_bottom_ft=1500.0)
        well.gas_migration_rate_ft_per_hr = 0.0
        plan = plan_kill(well, "stripping")
        pressures = [p.casing_psi for p in plan.trace]
        assert max(pressures) - min(pressures) < 1.0

    def test_warns_when_no_migration_rate_given_on_a_vertical_well(self):
        well = examples.well_state(SURFACE_VERTICAL, bit_off_bottom_ft=1500.0)
        well.gas_migration_rate_ft_per_hr = 0.0
        plan = plan_kill(well, "stripping")
        assert any("migration rate" in w for w in plan.applicability.warnings)

    def test_horizontal_well_gets_no_migration_rate(self):
        well = examples.well_state(SURFACE_HORIZONTAL, bit_off_bottom_ft=1500.0)
        assert well.gas_migration_rate_ft_per_hr == 0.0

    def test_warns_about_snubbing_when_the_bit_is_shallow(self):
        well = examples.well_state(SURFACE_VERTICAL, bit_off_bottom_ft=9200.0)
        well.sicp_psi = 900.0
        plan = plan_kill(well, "stripping")
        assert any("snubbing unit" in w for w in plan.applicability.warnings)

    def test_blocked_when_already_above_maasp(self):
        well = examples.well_state(SURFACE_VERTICAL, bit_off_bottom_ft=1500.0)
        well.sicp_psi = 5000.0
        plan = plan_kill(well, "stripping")
        assert not plan.applicability.usable
        assert any("MAASP" in b for b in plan.applicability.blockers)

    def test_summary_reports_the_key_numbers(self):
        well = examples.well_state(SURFACE_VERTICAL, bit_off_bottom_ft=1500.0)
        summary = plan_kill(well, "stripping").summary
        for key in (
            "Stands required", "Volume per stand (bbl)", "Balance point (ft)",
            "Snubbing required", "Technique", "Total volume (bbl)",
        ):
            assert key in summary

    def test_four_stages(self):
        well = examples.well_state(SURFACE_VERTICAL, bit_off_bottom_ft=1500.0)
        plan = plan_kill(well, "stripping")
        assert len(plan.stages) == 4
        assert all(stage.actions for stage in plan.stages)

    def test_notes_explain_it_is_not_a_kill(self):
        well = examples.well_state(SURFACE_VERTICAL, bit_off_bottom_ft=1500.0)
        plan = plan_kill(well, "stripping")
        assert any("not a kill" in n for n in plan.notes)


# --------------------------------------------------------------------------
# Interaction with the other methods
# --------------------------------------------------------------------------

class TestSequence:
    def test_circulating_methods_still_plan_off_bottom(self):
        """They are not blocked, but the bit being off bottom is why stripping
        exists -- a real kill would strip to bottom first.
        """
        well = examples.well_state(SURFACE_VERTICAL, bit_off_bottom_ft=1500.0)
        for key in ("drillers", "wait_and_weight"):
            plan = plan_kill(well, key)
            assert plan.trace

    def test_volumetric_is_the_predecessor(self):
        """Volumetric holds the well; stripping restores circulation. Both are
        usable on the same off-bottom vertical well.
        """
        well = examples.well_state(SURFACE_VERTICAL, bit_off_bottom_ft=1500.0)
        assert plan_kill(well, "volumetric").applicability.usable
        assert plan_kill(well, "stripping").applicability.usable

    def test_seven_methods_registered(self):
        from wellcontrol.methods import list_methods

        assert len(list_methods()) == 7
        assert "stripping" in {m.key for m in list_methods()}
