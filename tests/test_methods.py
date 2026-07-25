"""Kill method tests across every well configuration.

The important tests here are the **invariants** -- properties that must hold for
any well and any method, regardless of the numbers:

* Mass is conserved: the fluid zones always fill exactly the annulus.
* Boyle's law holds: the influx's pressure-volume product stays constant.
* Bottomhole pressure is held at the formation pressure throughout.
* Drill pipe pressure starts at ICP and reaches FCP when kill mud hits the bit.

An arithmetic error anywhere in the simulator breaks at least one of these.
"""

import pytest

from wellcontrol import examples
from wellcontrol.methods import (
    METHODS,
    Applicability,
    FluidColumn,
    Zone,
    applicability_matrix,
    get_method,
    list_methods,
    method_keys,
    plan_kill,
    simulate_circulation,
)
from wellcontrol.units import psi_to_psia
from wellcontrol.wellconfig import BOPLocation, Trajectory, WellConfiguration

CONFIGS = WellConfiguration.standard()
CONFIG_IDS = [c.key for c in CONFIGS]
METHOD_KEYS = [m.key for m in METHODS]

SURFACE_VERTICAL = WellConfiguration(BOPLocation.SURFACE, Trajectory.VERTICAL)
SURFACE_HORIZONTAL = WellConfiguration(BOPLocation.SURFACE, Trajectory.HORIZONTAL)
SUBSEA_VERTICAL = WellConfiguration(BOPLocation.SUBSEA, Trajectory.VERTICAL)
SUBSEA_HORIZONTAL = WellConfiguration(BOPLocation.SUBSEA, Trajectory.HORIZONTAL)


# --------------------------------------------------------------------------
# Configuration model
# --------------------------------------------------------------------------

class TestWellConfiguration:
    def test_four_standard_configurations(self):
        assert len(CONFIGS) == 4
        assert {c.key for c in CONFIGS} == {
            "surface_vertical", "surface_horizontal",
            "subsea_vertical", "subsea_horizontal",
        }

    def test_round_trip_through_key(self):
        for config in CONFIGS:
            assert WellConfiguration.from_key(config.key) == config

    def test_migration_is_unreliable_only_when_horizontal(self):
        assert Trajectory.VERTICAL.migration_reliable
        assert Trajectory.DEVIATED.migration_reliable
        assert not Trajectory.HORIZONTAL.migration_reliable

    @pytest.mark.parametrize("config", CONFIGS, ids=CONFIG_IDS)
    def test_every_configuration_has_considerations(self, config):
        assert config.considerations()

    def test_subsea_mentions_choke_line_friction(self):
        text = " ".join(SUBSEA_VERTICAL.considerations()).lower()
        assert "choke line friction" in text

    def test_horizontal_mentions_tvd(self):
        text = " ".join(SURFACE_HORIZONTAL.considerations()).lower()
        assert "tvd" in text


# --------------------------------------------------------------------------
# Fluid column
# --------------------------------------------------------------------------

class TestFluidColumn:
    def test_single_zone_hydrostatic(self):
        """0.052 x 9.6 x 10000 = 4992 psi"""
        _, survey = examples.vertical_land_well()
        column = FluidColumn([Zone(0.0, 10000.0, 9.6, "mud")], survey)
        assert column.total_hydrostatic == pytest.approx(4992.0)

    def test_stacked_zones(self):
        """9000 ft of 9.6 ppg over 1000 ft of 2 ppg = 4492.8 + 104 = 4596.8"""
        _, survey = examples.vertical_land_well()
        column = FluidColumn([
            Zone(0.0, 9000.0, 9.6, "mud"),
            Zone(9000.0, 10000.0, 2.0, "gas"),
        ], survey)
        assert column.total_hydrostatic == pytest.approx(4596.8)

    def test_surface_pressure_for_bottomhole(self):
        _, survey = examples.vertical_land_well()
        column = FluidColumn([Zone(0.0, 10000.0, 9.6, "mud")], survey)
        assert column.surface_pressure_for_bottomhole(5392.0) == pytest.approx(400.0)

    def test_pressure_at_depth_is_consistent(self):
        _, survey = examples.vertical_land_well()
        column = FluidColumn([Zone(0.0, 10000.0, 9.6, "mud")], survey)
        assert column.pressure_at(7000.0, 400.0) == pytest.approx(400.0 + 3494.4)

    def test_lateral_zone_contributes_no_hydrostatic(self):
        """A zone lying in the lateral has measured length but no TVD."""
        _, survey = examples.horizontal_well()
        column = FluidColumn([Zone(11000.0, 12000.0, 9.6, "gas in lateral")], survey)
        assert column.total_hydrostatic == pytest.approx(0.0, abs=1.0)

    def test_zero_length_zones_are_dropped(self):
        _, survey = examples.vertical_land_well()
        column = FluidColumn([
            Zone(0.0, 0.0, 9.6, "empty"),
            Zone(0.0, 10000.0, 9.6, "mud"),
        ], survey)
        assert len(column.zones) == 1


# --------------------------------------------------------------------------
# Well state
# --------------------------------------------------------------------------

class TestWellState:
    def test_formation_pressure(self):
        well = examples.well_state(SURFACE_VERTICAL)
        assert well.formation_pressure_psi == pytest.approx(5392.0)

    def test_kill_mud_weight_uses_tvd(self):
        well = examples.well_state(SURFACE_HORIZONTAL)
        assert well.bit_md_ft == pytest.approx(12000.0)
        assert well.bit_tvd_ft == pytest.approx(5909.86, abs=0.5)
        assert well.kill_mud_weight_exact_ppg == pytest.approx(11.339, abs=0.01)
        assert well.kill_mud_weight_ppg == pytest.approx(11.4)

    def test_influx_density_resolved_when_it_has_height(self):
        well = examples.well_state(SURFACE_VERTICAL)
        gradient, measured = well.influx_gradient_resolved
        assert measured is True
        assert well.influx_density_ppg == pytest.approx(1.96, abs=0.05)

    def test_influx_density_assumed_in_a_lateral(self):
        """No vertical height means the density cannot be recovered."""
        well = examples.well_state(SURFACE_HORIZONTAL)
        gradient, measured = well.influx_gradient_resolved
        assert measured is False
        assert gradient == pytest.approx(0.1)

    def test_choke_line_friction_ignored_on_a_surface_stack(self):
        well = examples.well_state(SURFACE_VERTICAL)
        well.choke_line_friction_psi = 350.0
        assert well.effective_choke_line_friction == 0.0

    def test_choke_line_friction_applied_subsea(self):
        well = examples.well_state(SUBSEA_VERTICAL)
        assert well.effective_choke_line_friction == pytest.approx(350.0)

    def test_maasp_falls_as_mud_weight_rises(self):
        well = examples.well_state(SURFACE_VERTICAL)
        assert well.maasp_psi(well.kill_mud_weight_ppg) < well.maasp_psi()

    def test_annulus_volume_helpers_are_inverses(self):
        well = examples.well_state(SURFACE_VERTICAL)
        total = well.annulus.volume_bbl
        md = well.annulus_md_at_volume_from_bottom(100.0)
        assert well.annulus.volume_between(md, well.hole_md_ft) == pytest.approx(
            100.0, abs=0.1
        )
        assert well.annulus_md_at_volume_from_surface(total) == pytest.approx(
            well.hole_md_ft, abs=1.0
        )

    def test_volume_beyond_the_annulus_clamps_to_surface(self):
        well = examples.well_state(SURFACE_VERTICAL)
        assert well.annulus_md_at_volume_from_bottom(1e6) == 0.0


# --------------------------------------------------------------------------
# Registry
# --------------------------------------------------------------------------

class TestRegistry:
    def test_seven_methods(self):
        assert len(list_methods()) == 7

    def test_keys_are_unique(self):
        assert len(set(method_keys())) == len(method_keys())

    def test_get_method_by_key(self):
        assert get_method("drillers").name == "Driller's Method"

    def test_unknown_key_raises(self):
        with pytest.raises(KeyError, match="Unknown kill method"):
            get_method("magic")

    def test_applicability_matrix_covers_every_method(self):
        well = examples.well_state(SURFACE_VERTICAL)
        matrix = applicability_matrix(well)
        assert set(matrix) == set(method_keys())
        assert all(isinstance(v, Applicability) for v in matrix.values())


# --------------------------------------------------------------------------
# The full matrix
# --------------------------------------------------------------------------

@pytest.mark.parametrize("config", CONFIGS, ids=CONFIG_IDS)
@pytest.mark.parametrize("method_key", METHOD_KEYS)
class TestEveryCombination:
    def test_plans_without_raising(self, config, method_key):
        plan = plan_kill(examples.well_state(config), method_key)
        assert plan.method_key == method_key
        assert plan.configuration == config

    def test_produces_a_trace(self, config, method_key):
        """A usable method must produce something plottable.

        A blocked one may produce only a degenerate point -- Stripping on a
        well whose bit is already on bottom has nothing to trace.
        """
        plan = plan_kill(examples.well_state(config), method_key)
        if plan.applicability.usable:
            assert len(plan.trace) >= 2
        else:
            assert len(plan.trace) >= 1

    def test_produces_stages_with_actions(self, config, method_key):
        plan = plan_kill(examples.well_state(config), method_key)
        assert plan.stages
        assert all(stage.actions for stage in plan.stages)

    def test_produces_a_summary(self, config, method_key):
        plan = plan_kill(examples.well_state(config), method_key)
        assert plan.summary

    def test_carries_configuration_notes(self, config, method_key):
        plan = plan_kill(examples.well_state(config), method_key)
        assert plan.notes

    def test_pressures_are_never_negative(self, config, method_key):
        plan = plan_kill(examples.well_state(config), method_key)
        for point in plan.trace:
            if point.casing_psi is not None:
                assert point.casing_psi >= 0.0
            if point.drill_pipe_psi is not None:
                assert point.drill_pipe_psi >= 0.0


# --------------------------------------------------------------------------
# Applicability behaviour
# --------------------------------------------------------------------------

class TestApplicability:
    @pytest.mark.parametrize("method_key", ["volumetric", "lube_and_bleed"])
    @pytest.mark.parametrize(
        "config", [SURFACE_HORIZONTAL, SUBSEA_HORIZONTAL],
        ids=["surface_horizontal", "subsea_horizontal"],
    )
    def test_migration_methods_blocked_on_horizontal_wells(self, method_key, config):
        """Gas cannot migrate in a lateral, so these methods cannot start."""
        plan = plan_kill(examples.well_state(config), method_key)
        assert not plan.applicability.usable
        assert plan.applicability.blockers

    @pytest.mark.parametrize("method_key", ["volumetric", "lube_and_bleed"])
    def test_migration_methods_allowed_on_vertical_wells(self, method_key):
        plan = plan_kill(examples.well_state(SURFACE_VERTICAL), method_key)
        assert plan.applicability.usable

    @pytest.mark.parametrize("method_key", ["drillers", "wait_and_weight"])
    @pytest.mark.parametrize("config", CONFIGS, ids=CONFIG_IDS)
    def test_circulating_methods_usable_everywhere(self, method_key, config):
        plan = plan_kill(examples.well_state(config), method_key)
        assert plan.applicability.usable, plan.applicability.blockers

    def test_missing_scr_blocks_a_circulating_method(self):
        well = examples.well_state(SURFACE_VERTICAL)
        well.slow_circulating_rate.__class__(spm=30.0, pressure_psi=0.0)
        from wellcontrol.killsheet import SlowCirculatingRate

        well.slow_circulating_rate = SlowCirculatingRate(spm=30.0, pressure_psi=0.0)
        plan = plan_kill(well, "drillers")
        assert not plan.applicability.usable

    def test_subsea_without_choke_line_friction_warns(self):
        well = examples.well_state(SUBSEA_VERTICAL)
        well.choke_line_friction_psi = 0.0
        plan = plan_kill(well, "wait_and_weight")
        assert any("choke line friction" in w.lower()
                   for w in plan.applicability.warnings)

    def test_reverse_circulation_warns_about_the_float(self):
        plan = plan_kill(examples.well_state(SURFACE_VERTICAL), "reverse")
        assert any("float" in w.lower() for w in plan.applicability.warnings)

    def test_bullhead_blocked_when_it_would_fracture_the_shoe(self):
        """A weak shoe makes bullheading impossible, and it must say so."""
        well = examples.well_state(SURFACE_VERTICAL)
        well.frac_gradient_ppg = 10.0
        plan = plan_kill(well, "bullhead")
        assert not plan.applicability.usable
        assert any("fracture" in b.lower() for b in plan.applicability.blockers)


# --------------------------------------------------------------------------
# Circulation simulator invariants
# --------------------------------------------------------------------------

@pytest.mark.parametrize("config", CONFIGS, ids=CONFIG_IDS)
class TestSimulatorInvariants:
    def _snapshots(self, config):
        well = examples.well_state(config)
        return well, simulate_circulation(
            well,
            use_kill_mud=True,
            influx_volume_bbl=well.pit_gain_bbl,
            total_volume_bbl=(
                well.annulus.string.internal_volume_bbl + well.annulus.volume_bbl
            ),
            steps=40,
        )

    def test_zones_always_fill_exactly_the_annulus(self, config):
        """Mass conservation. The fluid zones must tile the whole annulus with
        no gap and no overlap, at every step.
        """
        well, snapshots = self._snapshots(config)
        total = well.annulus.volume_bbl
        for snapshot in snapshots:
            occupied = sum(
                well.annulus.volume_between(zone.top_md, zone.bottom_md)
                for zone in snapshot.column.zones
            )
            assert occupied == pytest.approx(total, rel=0.02), (
                f"zones cover {occupied:.1f} bbl of a {total:.1f} bbl annulus"
            )

    def test_zones_are_contiguous(self, config):
        _, snapshots = self._snapshots(config)
        for snapshot in snapshots:
            zones = snapshot.column.zones
            for upper, lower in zip(zones, zones[1:]):
                assert upper.bottom_md == pytest.approx(lower.top_md, abs=1.0)

    def test_influx_only_ever_rises(self, config):
        _, snapshots = self._snapshots(config)
        tops = [s.influx_top_md_ft for s in snapshots
                if s.influx_top_md_ft is not None]
        for earlier, later in zip(tops, tops[1:]):
            assert later <= earlier + 1.0

    def test_influx_obeys_boyles_law(self, config):
        """Pressure times volume stays constant as the gas rises."""
        well, snapshots = self._snapshots(config)
        products = []
        for snapshot in snapshots:
            if not snapshot.influx_volume_bbl or snapshot.influx_top_md_ft is None:
                continue
            if snapshot.influx_top_md_ft <= 1.0:
                continue  # venting at surface; volume is clipped by the annulus
            midpoint = (
                snapshot.influx_top_md_ft + snapshot.influx_bottom_md_ft
            ) / 2.0
            pressure = snapshot.column.pressure_at(midpoint, snapshot.casing_psi)
            products.append(psi_to_psia(pressure) * snapshot.influx_volume_bbl)
        assert len(products) > 5
        assert max(products) / min(products) < 1.15

    def test_kill_mud_reaches_the_bit_and_no_further(self, config):
        well, snapshots = self._snapshots(config)
        depths = [s.kill_mud_string_md_ft for s in snapshots]
        assert depths[0] == pytest.approx(0.0)
        assert max(depths) == pytest.approx(well.bit_md_ft, abs=1.0)

    def test_drill_pipe_pressure_starts_at_icp(self, config):
        well, snapshots = self._snapshots(config)
        icp = well.kill_sheet.initial_circulating_pressure_psi
        assert snapshots[0].drill_pipe_psi == pytest.approx(icp, abs=1.0)

    def test_drill_pipe_pressure_reaches_fcp_at_the_bit(self, config):
        """Lands on FCP less the rounding overbalance.

        The simulator holds bottomhole pressure exactly at formation pressure.
        The mud actually mixed is heavier than that requires, because the kill
        weight rounds up, so the pressure needed is lower than the nominal FCP
        by exactly that margin.
        """
        well, snapshots = self._snapshots(config)
        sheet = well.kill_sheet
        target = (
            sheet.final_circulating_pressure_psi - sheet.rounding_overbalance_psi
        )
        string_volume = well.annulus.string.internal_volume_bbl
        at_bit = min(
            snapshots, key=lambda s: abs(s.volume_pumped_bbl - string_volume)
        )
        assert at_bit.drill_pipe_psi == pytest.approx(target, abs=15.0)

    def test_casing_pressure_ends_near_zero(self, config):
        """A complete kill leaves the annulus full of kill mud and dead."""
        _, snapshots = self._snapshots(config)
        assert snapshots[-1].casing_psi == pytest.approx(0.0, abs=20.0)


# --------------------------------------------------------------------------
# Method-specific behaviour
# --------------------------------------------------------------------------

class TestDrillersMethod:
    def test_first_circulation_holds_icp_constant(self):
        well = examples.well_state(SURFACE_VERTICAL)
        snapshots = simulate_circulation(
            well,
            use_kill_mud=False,
            influx_volume_bbl=well.pit_gain_bbl,
            total_volume_bbl=well.annulus.volume_bbl,
            steps=30,
        )
        icp = well.kill_sheet.initial_circulating_pressure_psi
        for snapshot in snapshots:
            assert snapshot.drill_pipe_psi == pytest.approx(icp, abs=1.0)

    def test_two_circulations_cost_more_strokes_than_one(self):
        well = examples.well_state(SURFACE_VERTICAL)
        drillers = plan_kill(well, "drillers")
        wait = plan_kill(well, "wait_and_weight")
        assert drillers.trace[-1].x > wait.trace[-1].x


class TestWaitAndWeight:
    def test_lower_peak_casing_pressure_than_drillers(self):
        """Kill mud entering the annulus behind the influx adds hydrostatic."""
        well = examples.well_state(SURFACE_VERTICAL)
        drillers = plan_kill(well, "drillers")
        wait = plan_kill(well, "wait_and_weight")
        assert wait.peak_casing_pressure_psi < drillers.peak_casing_pressure_psi

    def test_shoe_advantage_is_reported_as_conditional(self):
        """The advantage holds only when the open hole annular volume exceeds
        the drill string volume. On the reference well it does not, and the
        plan must say so rather than repeating the textbook claim.
        """
        well = examples.well_state(SURFACE_VERTICAL)
        note = " ".join(plan_kill(well, "wait_and_weight").notes)
        assert "no shoe-pressure advantage" in note
        assert "Open hole annular volume" in note

    def test_no_shoe_advantage_when_the_string_is_long(self):
        well = examples.well_state(SURFACE_VERTICAL)
        string_volume = well.annulus.string.internal_volume_bbl
        shoe_to_td = well.annulus.volume_between(well.shoe_md, well.hole_md_ft)
        assert string_volume > shoe_to_td - well.pit_gain_bbl

        drillers = plan_kill(well, "drillers")
        wait = plan_kill(well, "wait_and_weight")
        assert wait.peak_shoe_pressure_psi == pytest.approx(
            drillers.peak_shoe_pressure_psi, rel=0.01
        )


class TestVolumetric:
    def test_bleed_volume_matches_the_working_margin(self):
        """The bled volume's hydrostatic must equal the working margin."""
        from wellcontrol.units import PSI_PER_PPG_FT

        well = examples.well_state(SURFACE_VERTICAL)
        plan = plan_kill(well, "volumetric")
        bleed = plan.summary["Bleed volume per cycle (bbl)"]
        capacity = well.annulus.capacity_at(10.0)
        recovered = PSI_PER_PPG_FT * well.mud_weight_ppg * (bleed / capacity)
        assert recovered == pytest.approx(100.0, rel=0.02)

    def test_gas_expands_as_it_rises(self):
        plan = plan_kill(examples.well_state(SURFACE_VERTICAL), "volumetric")
        volumes = [p.influx_volume_bbl for p in plan.trace]
        assert volumes[-1] > volumes[0]

    def test_casing_pressure_climbs_throughout(self):
        plan = plan_kill(examples.well_state(SURFACE_VERTICAL), "volumetric")
        assert plan.trace[-1].casing_psi > plan.trace[0].casing_psi

    def test_warns_when_the_projection_exceeds_maasp(self):
        plan = plan_kill(examples.well_state(SURFACE_VERTICAL), "volumetric")
        assert any("MAASP" in w for w in plan.applicability.warnings)

    def test_x_axis_is_volume_not_strokes(self):
        plan = plan_kill(examples.well_state(SURFACE_VERTICAL), "volumetric")
        assert "bled" in plan.x_label.lower()


class TestLubeAndBleed:
    def test_pressure_falls_each_cycle(self):
        plan = plan_kill(examples.well_state(SURFACE_VERTICAL), "lube_and_bleed")
        pressures = [p.casing_psi for p in plan.trace]
        assert pressures == sorted(pressures, reverse=True)

    def test_reaches_zero_surface_pressure(self):
        plan = plan_kill(examples.well_state(SURFACE_VERTICAL), "lube_and_bleed")
        assert plan.trace[-1].casing_psi == pytest.approx(0.0, abs=60.0)

    def test_warns_about_waiting_for_separation(self):
        plan = plan_kill(examples.well_state(SURFACE_VERTICAL), "lube_and_bleed")
        assert any("fall through the gas" in w for w in plan.applicability.warnings)


class TestReverseCirculation:
    def test_much_faster_than_circulating_forward(self):
        plan = plan_kill(examples.well_state(SURFACE_VERTICAL), "reverse")
        assert plan.summary["Strokes saved"] > 0
        assert (
            plan.summary["Strokes for influx to surface (reverse)"]
            < plan.summary["Strokes if circulated forward"]
        )

    def test_keeps_the_influx_away_from_the_shoe(self):
        """The headline advantage: gas goes up the string, not past the shoe."""
        well = examples.well_state(SURFACE_VERTICAL)
        reverse = plan_kill(well, "reverse")
        drillers = plan_kill(well, "drillers")
        assert reverse.peak_shoe_pressure_psi < drillers.peak_shoe_pressure_psi

    def test_influx_rises_through_the_string(self):
        plan = plan_kill(examples.well_state(SURFACE_VERTICAL), "reverse")
        tops = [p.influx_top_md_ft for p in plan.trace
                if p.influx_top_md_ft is not None]
        assert tops[0] > tops[-1]


class TestBullhead:
    def test_surface_pressure_falls_as_kill_mud_fills(self):
        plan = plan_kill(examples.well_state(SURFACE_VERTICAL), "bullhead")
        assert plan.trace[-1].casing_psi < plan.trace[0].casing_psi

    def test_hardest_at_the_start(self):
        """Peak shoe pressure occurs at the first stroke, not the last."""
        plan = plan_kill(examples.well_state(SURFACE_VERTICAL), "bullhead")
        shoes = [p.shoe_psi for p in plan.trace if p.shoe_psi is not None]
        assert shoes[0] == max(shoes)

    def test_x_axis_is_volume_pumped(self):
        plan = plan_kill(examples.well_state(SURFACE_VERTICAL), "bullhead")
        assert "pumped" in plan.x_label.lower()

    def test_warns_the_formation_must_accept_fluid(self):
        plan = plan_kill(examples.well_state(SURFACE_VERTICAL), "bullhead")
        assert any("accept fluid" in w for w in plan.applicability.warnings)


# --------------------------------------------------------------------------
# Horizontal-well behaviour
# --------------------------------------------------------------------------

class TestHorizontalWells:
    def test_kill_mud_weight_far_exceeds_the_md_based_answer(self):
        well = examples.well_state(SURFACE_HORIZONTAL)
        wrong = well.mud_weight_ppg + well.sidpp_psi / (0.052 * well.bit_md_ft)
        assert well.kill_mud_weight_ppg - wrong > 0.5

    def test_influx_in_the_lateral_has_no_vertical_height(self):
        well = examples.well_state(SURFACE_HORIZONTAL)
        assert well.influx_height_md_ft > 100.0
        assert well.influx_height_tvd_ft == pytest.approx(0.0, abs=1.0)

    @pytest.mark.parametrize("method_key", ["drillers", "wait_and_weight"])
    def test_circulating_methods_still_work(self, method_key):
        plan = plan_kill(examples.well_state(SURFACE_HORIZONTAL), method_key)
        assert plan.applicability.usable
        assert plan.trace
