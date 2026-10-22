"""The scenario library, and the faults an instructor can inject.

Stage 5. A scenario names an exercise: which well, where it starts, what the
student is expected to achieve, and what is going to go wrong part way through.

**Faults are triggers, not scripts.** Each does one thing to one piece of
equipment at one moment -- the pump fails, the choke plugs, the seat is weaker
than the leak-off said. What follows is whatever the well does about it, through
the same volume balance as everything else. A fault cannot make the well behave
in a way it could not have behaved on its own, and these tests exist mostly to
keep it that way.
"""

from __future__ import annotations

import pytest

from wellcontrol.sim import EventKind, Session
from wellcontrol.sim.engine import WEAK_SHOE_MARGIN_PSI, StartState
from wellcontrol.sim.scenario import (
    SCENARIOS,
    Fault,
    FaultKind,
    Scenario,
    custom_scenario_list,
    delete_custom_scenario,
    get_custom_templates,
    get_scenario,
    save_custom_scenario,
    scenario_list,
)


class TestTheLibrary:
    def test_every_scenario_builds_a_session(self):
        for scenario in SCENARIOS:
            session = Session.for_scenario(scenario.key)
            assert session.simulator.state.casing_pressure_psi >= 0

    def test_keys_are_unique(self):
        keys = [s.key for s in SCENARIOS]
        assert len(keys) == len(set(keys))

    def test_every_scenario_says_what_it_wants(self):
        for scenario in SCENARIOS:
            assert scenario.objective
            assert scenario.briefing

    def test_an_unknown_key_names_the_ones_that_exist(self):
        with pytest.raises(KeyError, match="drillers"):
            get_scenario("nonsense")

    def test_the_listing_does_not_give_the_faults_away(self):
        """Knowing the choke plugs at stroke 2,000 is not the exercise."""
        for summary in scenario_list():
            assert "faults" not in summary
            assert isinstance(summary["has_faults"], bool)
        plugged = next(s for s in scenario_list() if s["key"] == "choke_plugs")
        assert plugged["has_faults"] is True


class TestScenariosAreData:
    """An instructor should not have to write Python to add an exercise."""

    def test_a_scenario_round_trips_through_a_dict(self):
        built = Scenario.from_dict({
            "key": "custom",
            "name": "Something an instructor wrote",
            "objective": "Do the thing.",
            "briefing": "Here is the situation.",
            "bop": "subsea",
            "trajectory": "horizontal",
            "start": "drilling",
            "require_kill": True,
            "open_valves": ["choke_1"],
            "faults": [{"kind": "pump_failure", "at_seconds": 60.0,
                        "message": "Pump down."}],
        })
        assert built.key == "custom"
        assert built.start is StartState.DRILLING
        assert built.require_kill is True
        assert built.open_valves == ("choke_1",)
        assert built.faults[0].kind is FaultKind.PUMP_FAILURE
        assert built.faults[0].at_seconds == 60.0

    def test_the_minimum_a_scenario_needs_is_small(self):
        built = Scenario.from_dict(
            {"key": "bare", "name": "Bare", "objective": "Kill it."}
        )
        assert built.bop == "surface"
        assert built.faults == ()


class TestTriggers:
    class _Log:
        def __init__(self, has_it=False):
            self._has = has_it

        def has(self, kind):
            return self._has

    def test_time_fires_it(self):
        fault = Fault(kind=FaultKind.PUMP_FAILURE, at_seconds=30.0)
        assert not fault.is_due(29.0, 0, self._Log())
        assert fault.is_due(30.0, 0, self._Log())

    def test_strokes_fire_it(self):
        fault = Fault(kind=FaultKind.CHOKE_PLUGGED, at_strokes=500.0)
        assert not fault.is_due(9999.0, 499, self._Log())
        assert fault.is_due(0.0, 500, self._Log())

    def test_an_event_fires_it(self):
        """So a fault can hang on something the student caused."""
        fault = Fault(
            kind=FaultKind.CHOKE_WASHOUT, after_event=EventKind.GAS_AT_SURFACE
        )
        assert not fault.is_due(0.0, 0, self._Log(False))
        assert fault.is_due(0.0, 0, self._Log(True))

    def test_a_fault_with_no_trigger_never_fires(self):
        assert not Fault(kind=FaultKind.PUMP_FAILURE).is_due(1e9, 1e9, self._Log())


class TestFaultsDoOneThing:
    def test_the_pump_dies_and_stays_dead(self):
        session = Session.for_scenario("volumetric")
        session.simulator.pump.command(30.0)
        session.simulator.run(30, dt=0.1)
        assert session.simulator.pump.spm == pytest.approx(0.0)
        assert session.simulator.state.flow_in_bpm == pytest.approx(0.0)

    def test_the_failure_is_logged_as_the_rig_would_report_it(self):
        session = Session.for_scenario("volumetric")
        session.simulator.run(1, dt=0.1)
        log = session.simulator.state.event_log
        assert log.has(EventKind.EQUIPMENT_FAILURE)
        assert "pump" in log.first(EventKind.EQUIPMENT_FAILURE).message.lower()

    def test_a_dead_pump_still_leaves_volumetric_available(self):
        """Which is the point of the exercise: bleed, because you cannot pump."""
        session = Session.for_scenario("volumetric")
        sim = session.simulator
        before = sim.state.casing_pressure_psi
        sim.run(600, dt=0.2)
        assert sim.state.casing_pressure_psi > before, "gas should still migrate"
        sim.choke.command(20.0)
        sim.run(120, dt=0.1)
        assert sim.state.bled_bbl > 0.0

    def test_the_choke_plugs_part_way_through(self):
        session = Session.for_scenario("choke_plugs")
        sim = session.simulator
        sim.choke.command(20.0)
        sim.pump.command(30.0)
        area = sim.choke.full_open_area_in2
        for _ in range(200):
            sim.run(20, dt=0.1)
            if sim.choke.full_open_area_in2 < area:
                break
        assert sim.choke.full_open_area_in2 < area
        assert sim.state.strokes >= 900

    def test_a_plugged_choke_still_moves_but_passes_nothing(self):
        """The handle works. That is what makes it confusing on the rig."""
        session = Session.for_scenario("choke_plugs")
        sim = session.simulator
        sim._break_equipment(Fault(kind=FaultKind.CHOKE_PLUGGED))
        sim.choke.command(60.0)
        sim.run(20, dt=0.1)
        assert sim.choke.position > 20.0
        assert sim.choke.flow_bbl_per_min(800.0, 9.6) < 0.05

    def test_the_weak_shoe_leaves_a_window_to_fly_in(self):
        """Halving the wrong margin made the exercise unwinnable from step one."""
        session = Session.for_scenario("weak_shoe")
        sim = session.simulator
        sim.run(1, dt=0.1)
        assert sim.frac_pressure_psi > sim.state.shoe_pressure_psi
        assert sim.frac_pressure_psi - sim.state.shoe_pressure_psi == (
            pytest.approx(WEAK_SHOE_MARGIN_PSI, abs=30.0)
        )

    def test_the_weak_shoe_is_genuinely_tighter_than_the_kill_sheet_says(self):
        weak = Session.for_scenario("weak_shoe")
        normal = Session.for_scenario("drillers")
        weak.simulator.run(1, dt=0.1)
        normal.simulator.run(1, dt=0.1)
        assert weak.simulator.frac_pressure_psi < normal.simulator.frac_pressure_psi

    def test_a_fault_fires_once(self):
        session = Session.for_scenario("volumetric")
        session.simulator.run(120, dt=0.1)
        fired = session.simulator.state.event_log.of_kind(
            EventKind.EQUIPMENT_FAILURE
        )
        assert len(fired) == 1

    def test_a_scenario_without_faults_has_nothing_fire(self):
        session = Session.for_scenario("drillers")
        session.simulator.run(120, dt=0.1)
        assert not session.simulator.state.event_log.has(
            EventKind.EQUIPMENT_FAILURE
        )


class TestScenariosSetUpTheirExercise:
    def test_stripping_starts_off_bottom(self):
        session = Session.for_scenario("stripping")
        assert session.simulator.state.bit_md_ft < session.simulator.hole_md

    def test_reverse_starts_lined_up_to_reverse(self):
        session = Session.for_scenario("reverse")
        assert session.simulator.flow_path.is_reverse_circulating

    def test_lube_and_bleed_starts_lined_up_to_lubricate(self):
        session = Session.for_scenario("lube_and_bleed")
        assert session.simulator.flow_path.injecting_into_the_annulus

    def test_find_the_kick_starts_drilling_and_hides_the_downhole(self):
        session = Session.for_scenario("find_the_kick")
        assert not session.downhole_visible
        assert session.gauges()["bottomhole_psi"] is None

    def test_the_horizontal_well_does_not_migrate(self):
        session = Session.for_scenario("horizontal")
        assert session.simulator.migration_rate_ft_per_hr == 0.0

    def test_the_subsea_well_carries_choke_line_friction(self):
        session = Session.for_scenario("subsea")
        assert session.simulator.well.choke_line_friction_psi > 0

    def test_trapped_gas_subsea_starts_with_subsea_stack(self):
        session = Session.for_scenario("trapped_gas_subsea")
        assert session.simulator.well.configuration.is_subsea
        assert session.simulator.flow_path.bop_is_closed

    def test_snubbing_starts_deeply_off_bottom(self):
        session = Session.for_scenario("snubbing")
        assert session.simulator.hole_md - session.simulator.state.bit_md_ft == pytest.approx(9200.0)
        assert session.simulator.hookload_lbf < 1000.0

    def test_wait_and_weight_starts_with_kill_mud_in_pits(self):
        session = Session.for_scenario("wait_and_weight")
        assert session.simulator.kill_mud_weight_ppg == pytest.approx(
            session.simulator.well.kill_mud_weight_ppg
        )
        assert session.simulator.kill_mud_weight_ppg > session.simulator.well.mud_weight_ppg

    def test_bullhead_starts_closed_in_with_kill_mud(self):
        session = Session.for_scenario("bullhead")
        assert session.simulator.flow_path.is_closed_in
        assert not session.simulator.flow_path.valve("choke_line_valve").is_open
        assert session.simulator.kill_mud_weight_ppg == pytest.approx(
            session.simulator.well.kill_mud_weight_ppg
        )
        assert session.simulator.migration_rate_ft_per_hr == 0.0

    def test_bullhead_squeezes_influx_into_formation(self):
        session = Session.for_scenario("bullhead")
        sim = session.simulator
        initial_gas = sim.state.influx_volume_bbl
        assert initial_gas > 0
        sim.pump.command(25.0)
        # Pump to squeeze influx into zone
        for _ in range(150):
            sim.run(10, dt=0.2)
            if sim.state.influx_volume_bbl < 0.5:
                break
        assert sim.state.influx_volume_bbl < 0.5
        assert sim.state.injected_bbl > 0
        sim.pump.command(0.0)
        for _ in range(10):
            sim.run(5, dt=0.2)
            if not sim.pump.running:
                break
        assert not sim.pump.running
        assert sim.state.well_is_dead


class TestTheScenarioSetsTheStandard:
    def test_the_debrief_uses_the_scenarios_own_standard(self):
        session = Session.for_scenario("drillers")
        report = session.debrief()
        assert report["scenario"]["key"] == "drillers"
        # This exercise does not require a dead well, so a live one is not a fail.
        assert "not killed" not in report["summary"]

    def test_an_explicit_override_still_wins(self):
        session = Session.for_scenario("drillers")
        assert session.debrief(require_kill=True)["grade"] == "fail"

    def test_a_session_without_a_scenario_still_works(self):
        session = Session.for_configuration()
        assert session.debrief()["scenario"] is None


class TestCustomScenarios:
    def test_custom_templates_exist(self):
        tmpls = get_custom_templates()
        assert len(tmpls) >= 3
        keys = [t["key"] for t in tmpls]
        assert "deepwater_gas_washout" in keys
        assert "narrow_margin_losses" in keys

    def test_save_and_retrieve_custom_scenario(self):
        key = "test_custom_deepwater_influx"
        delete_custom_scenario(key)
        data = {
            "key": key,
            "name": "Custom Deepwater Test",
            "objective": "Test custom scenario persistence and execution",
            "briefing": "Testing custom briefing text",
            "bop": "subsea",
            "trajectory": "vertical",
            "start": "shut_in",
            "mud_weight_ppg": 13.5,
            "sidpp_psi": 550.0,
            "sicp_psi": 800.0,
            "pit_gain_bbl": 32.0,
            "shoe_md_ft": 9500.0,
            "frac_gradient_ppg": 15.5,
            "require_kill": True,
            "faults": [
                {
                    "kind": "choke_plugged",
                    "at_strokes": 500,
                    "message": "Choke plugged with shale",
                    "severity": "critical",
                }
            ],
        }
        scen = save_custom_scenario(data)
        assert scen.key == key
        assert scen.is_custom

        retrieved = get_scenario(key)
        assert retrieved.name == "Custom Deepwater Test"
        assert retrieved.mud_weight_ppg == 13.5
        assert retrieved.sidpp_psi == 550.0

        # Create session from custom scenario
        session = Session.for_scenario(key)
        assert session.scenario.key == key
        assert session.simulator.well.mud_weight_ppg == 13.5
        assert session.simulator.well.sidpp_psi == 550.0
        assert session.simulator.well.sicp_psi == 800.0

        # Check listed in scenario_list and custom_scenario_list
        all_scens = scenario_list()
        assert any(s["key"] == key and s["is_custom"] for s in all_scens)
        custom_scens = custom_scenario_list()
        assert any(s["key"] == key for s in custom_scens)

        # Cleanup
        deleted = delete_custom_scenario(key)
        assert deleted
        with pytest.raises(KeyError):
            get_scenario(key)

    def test_conflict_with_builtin_scenario_rejected(self):
        with pytest.raises(ValueError, match="conflicts with a built-in standard scenario"):
            save_custom_scenario({
                "key": "drillers",
                "name": "Invalid Override",
                "objective": "Should fail",
            })
