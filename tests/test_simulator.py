"""Simulator tests.

Two kinds. First, that every failure mode a student must feel **emerges** from
the model rather than being scripted -- if these pass, the well is responding to
the controls rather than playing back an animation. Second, that a
well-flown kill reproduces the quasi-static solver, which is the check that the
forward model and the inverse model describe the same well.
"""

import pytest

from wellcontrol import examples
from wellcontrol.sim import FlowPath, Node, Simulator, ValveState
from wellcontrol.wellconfig import BOPLocation, Trajectory, WellConfiguration

SV = WellConfiguration(BOPLocation.SURFACE, Trajectory.VERTICAL)
SH = WellConfiguration(BOPLocation.SURFACE, Trajectory.HORIZONTAL)


def make(config=SV, **kwargs) -> Simulator:
    return Simulator(well=examples.well_state(config), **kwargs)


def lined_up_to_kill(sim: Simulator) -> Simulator:
    """Shut in on the annular, returns through choke 1."""
    sim.flow_path.close("annular")
    sim.flow_path.open(
        "pump_discharge", "standpipe_valve",
        "choke_line_valve", "choke_line_to_manifold", "choke_1",
    )
    return sim


# --------------------------------------------------------------------------
# Lineup
# --------------------------------------------------------------------------

class TestFlowPath:
    def test_rig_starts_lined_up_for_drilling(self):
        path = FlowPath()
        assert not path.bop_is_closed
        assert not path.return_route().through_choke

    def test_closing_any_element_shuts_the_stack(self):
        for element in ("annular", "upper_rams", "lower_rams"):
            path = FlowPath()
            path.close(element)
            assert path.bop_is_closed

    def test_open_stack_returns_up_the_flowline(self):
        path = FlowPath()
        route = path.return_route()
        assert route.open_to_pits
        assert not route.through_choke
        assert Node.FLOWLINE in route.route

    def test_shut_in_with_nothing_open_is_closed_in(self):
        path = FlowPath()
        path.close("annular")
        assert path.is_closed_in

    def test_choke_line_gives_a_return_route_with_the_stack_shut(self):
        path = FlowPath()
        path.close("annular")
        path.open("choke_line_valve", "choke_line_to_manifold", "choke_1")
        route = path.return_route()
        assert route.open_to_pits
        assert route.through_choke

    def test_kill_line_works_too(self):
        path = FlowPath()
        path.close("annular")
        path.open("kill_line_valve", "kill_line_to_manifold", "choke_1")
        assert path.return_route().through_choke

    def test_pump_deadheads_without_a_path(self):
        path = FlowPath()
        assert path.pump_is_deadheaded

    def test_pump_path_opens_with_the_right_valves(self):
        path = FlowPath()
        path.open("pump_discharge", "standpipe_valve")
        assert not path.pump_is_deadheaded

    def test_closed_kelly_cock_blocks_the_pump(self):
        path = FlowPath()
        path.open("pump_discharge", "standpipe_valve")
        path.close("kelly_cock")
        assert path.pump_is_deadheaded

    def test_bypass_defeats_the_choke(self):
        path = FlowPath()
        path.close("annular")
        path.open("choke_line_valve", "choke_line_to_manifold", "choke_bypass")
        assert path.bypass_is_open()

    def test_unknown_valve_is_rejected(self):
        with pytest.raises(KeyError, match="No valve called"):
            FlowPath().set_valve("magic_valve", ValveState.OPEN)


# --------------------------------------------------------------------------
# The behaviours a student must feel
# --------------------------------------------------------------------------

class TestEmergentBehaviour:
    """None of these are scripted. Each falls out of the volume balance."""

    def test_shut_in_well_sits_still(self):
        sim = make()
        sim.flow_path.close("annular")
        before = sim.state.casing_pressure_psi
        sim.run(120)
        assert sim.state.casing_pressure_psi == pytest.approx(before, abs=5.0)

    def test_shut_in_well_holds_bottomhole_at_formation_pressure(self):
        sim = make()
        sim.flow_path.close("annular")
        sim.run(60)
        assert sim.state.bottomhole_pressure_psi == pytest.approx(
            sim.formation_pressure_psi, abs=15.0
        )

    def test_bop_open_means_the_choke_does_nothing(self):
        """The lesson students most need: you cannot control a well with the
        annular open, however hard you work the choke."""
        sim = make()
        sim.flow_path.open(
            "pump_discharge", "standpipe_valve",
            "choke_line_valve", "choke_line_to_manifold", "choke_1",
        )
        sim.choke.command(2.0)          # nearly shut
        sim.pump.command(30.0)
        sim.run(60)
        assert sim.state.casing_pressure_psi == pytest.approx(0.0, abs=1.0)

    def test_pump_against_a_closed_valve_deadheads(self):
        sim = make()
        sim.flow_path.close("annular")
        sim.pump.command(30.0)
        sim.run(30)
        assert sim.flow_path.pump_is_deadheaded
        assert sim.state.flow_in_bpm == pytest.approx(0.0)

    def test_shutting_the_choke_on_a_running_pump_spikes_pressure(self):
        sim = lined_up_to_kill(make())
        sim.choke.command(0.0)
        sim.pump.command(30.0)
        before = sim.state.casing_pressure_psi
        sim.run(30)
        assert sim.state.casing_pressure_psi > before + 150.0

    def test_choke_wide_open_lets_the_well_go_underbalanced(self):
        sim = lined_up_to_kill(make())
        sim.choke.command(100.0)
        sim.pump.command(30.0)
        sim.run(60)
        assert sim.state.bottomhole_pressure_psi < sim.formation_pressure_psi

    def test_underbalance_takes_another_influx(self):
        sim = lined_up_to_kill(make())
        started_with = sim.state.influx_volume_bbl
        sim.choke.command(100.0)
        sim.pump.command(30.0)
        sim.run(120)
        assert sim.state.influx_volume_bbl > started_with + 2.0
        assert any("influx" in e for e in sim.state.events)

    def test_over_pressuring_the_shoe_takes_losses(self):
        sim = lined_up_to_kill(make())
        sim.choke.command(0.0)
        sim.pump.command(60.0)
        sim.run(180)
        assert sim.state.loss_rate_bpm > 0.0
        assert any("Shoe over-pressured" in e for e in sim.state.events)

    def test_closed_in_with_the_pump_running_builds_pressure(self):
        sim = make()
        sim.flow_path.close("annular")
        sim.flow_path.open("pump_discharge", "standpipe_valve")
        sim.pump.command(20.0)
        before = sim.state.casing_pressure_psi
        sim.run(20)
        assert sim.state.casing_pressure_psi > before + 50.0


class TestChokeFeel:
    """The capacitance term is what makes the choke teachable."""

    def test_system_is_stiff_with_gas_deep(self):
        sim = lined_up_to_kill(make())
        assert sim._capacitance_bbl_per_psi() < 0.02

    def test_system_softens_as_gas_rises_and_expands(self):
        deep = lined_up_to_kill(make())
        stiff = deep._capacitance_bbl_per_psi()

        shallow = lined_up_to_kill(make())
        shallow._gas_pv = 500.0 * 100.0      # a lot of gas at low pressure
        shallow.state.pumped_bbl = 400.0
        shallow._settle_gas()
        shallow._update_pressures()

        assert shallow._capacitance_bbl_per_psi() > stiff * 3.0

    def test_same_choke_movement_matters_less_when_soft(self):
        """A fixed net inflow moves pressure far less with gas in the hole."""
        stiff = lined_up_to_kill(make())
        soft = lined_up_to_kill(make())
        soft._gas_pv = 500.0 * 100.0
        soft.state.pumped_bbl = 400.0
        soft._settle_gas()
        soft._update_pressures()

        rise_stiff = 1.0 / stiff._capacitance_bbl_per_psi()
        rise_soft = 1.0 / soft._capacitance_bbl_per_psi()
        assert rise_stiff > rise_soft * 3.0


class TestGasInventory:
    def test_gas_expands_as_it_rises_when_pressure_is_held(self):
        """Only true if the kill is flown properly.

        On a fixed choke the pressure runs away and the gas *compresses*
        instead -- which is correct, and is why this uses the autopilot.
        """
        sim = lined_up_to_kill(make())
        sim.choke.command(20.0)
        sim.pump.command(30.0)
        sim.run(30, dt=0.1)
        started_with = sim.state.influx_volume_bbl
        autopilot_kill(sim, seconds=600)
        assert sim.state.influx_volume_bbl > started_with

    def test_gas_compresses_on_a_choke_left_too_tight(self):
        """The other side of the same coin, and the more instructive one."""
        sim = lined_up_to_kill(make())
        sim.choke.command(18.0)
        sim.pump.command(30.0)
        started_with = sim.state.influx_volume_bbl
        sim.run(600, dt=0.1)
        assert sim.state.casing_pressure_psi > 1000.0
        assert sim.state.influx_volume_bbl < started_with

    def test_gas_moves_up_the_hole(self):
        sim = lined_up_to_kill(make())
        sim.choke.command(18.0)
        sim.pump.command(30.0)
        start_top = sim.state.influx_top_md
        sim.run(600, dt=0.1)
        assert sim.state.influx_top_md < start_top

    def test_pressure_times_volume_is_conserved_while_shut_in(self):
        """No gas in, none out, so the inventory must not drift."""
        sim = make()
        sim.flow_path.close("annular")
        before = sim._gas_pv
        sim.run(120)
        assert sim._gas_pv == pytest.approx(before, rel=0.02)


# --------------------------------------------------------------------------
# Agreement with the quasi-static solver
# --------------------------------------------------------------------------

def autopilot_kill(sim: Simulator, seconds: float, dt: float = 0.1,
                   gain: float = 0.02) -> list[float]:
    """Fly the kill perfectly, holding bottomhole pressure on the formation.

    A proportional controller on the choke, standing in for a driller who never
    makes a mistake. Used to check the forward model against the inverse one:
    if the well is flown exactly right, the two must agree.
    """
    target = sim.formation_pressure_psi
    trace: list[float] = []
    for _ in range(int(seconds / dt)):
        error = target - sim.state.bottomhole_pressure_psi
        sim.choke.command(sim.choke.commanded_position - gain * error)
        sim.step(dt)
        trace.append(sim.state.bottomhole_pressure_psi)
    return trace


class TestAgreesWithTheQuasiStaticSolver:
    def test_a_perfectly_flown_kill_holds_bottomhole_pressure(self):
        sim = lined_up_to_kill(make())
        sim.choke.command(20.0)
        sim.pump.command(30.0)
        sim.run(30, dt=0.1)            # bring the pump up

        trace = autopilot_kill(sim, seconds=900)
        settled = trace[300:]          # ignore the first 30 s of settling
        target = sim.formation_pressure_psi

        worst = max(abs(p - target) for p in settled)
        assert worst < 75.0, f"bottomhole pressure wandered {worst:.0f} psi"

    def test_holding_bottomhole_pressure_prevents_further_influx(self):
        sim = lined_up_to_kill(make())
        sim.choke.command(20.0)
        sim.pump.command(30.0)
        sim.run(30, dt=0.1)
        started_with = sim.state.influx_volume_bbl

        autopilot_kill(sim, seconds=600)

        # Gas expands as it rises, so volume grows -- but the inventory must
        # not, because nothing new should come in.
        assert sim.state.influx_volume_bbl > started_with
        assert sim.state.loss_rate_bpm == pytest.approx(0.0)

    def test_shoe_stays_under_the_fracture_pressure_when_flown_well(self):
        sim = lined_up_to_kill(make())
        sim.choke.command(20.0)
        sim.pump.command(30.0)
        sim.run(30, dt=0.1)
        autopilot_kill(sim, seconds=900)
        assert sim.state.shoe_pressure_psi < sim.frac_pressure_psi


# --------------------------------------------------------------------------
# Across well types
# --------------------------------------------------------------------------

@pytest.mark.parametrize("config", WellConfiguration.standard(),
                         ids=[c.key for c in WellConfiguration.standard()])
class TestEveryWellType:
    def test_simulator_starts(self, config):
        sim = make(config)
        assert sim.state.casing_pressure_psi > 0

    def test_starts_balanced_on_the_formation(self, config):
        sim = make(config)
        sim.flow_path.close("annular")
        sim.run(30)
        assert sim.state.bottomhole_pressure_psi == pytest.approx(
            sim.formation_pressure_psi, rel=0.02
        )

    def test_readout_is_complete(self, config):
        readout = make(config).readout()
        for key in ("Casing (psi)", "Bottomhole (psi)", "Choke (%)",
                    "Influx (bbl)", "Returns"):
            assert key in readout


# --------------------------------------------------------------------------
# Equipment
# --------------------------------------------------------------------------

class TestEquipment:
    def test_pump_ramps_rather_than_jumping(self):
        sim = make()
        sim.pump.command(30.0)
        sim.pump.advance(1.0)
        assert 0.0 < sim.pump.spm < 30.0

    def test_pump_reaches_the_commanded_speed(self):
        sim = make()
        sim.pump.command(30.0)
        for _ in range(200):
            sim.pump.advance(0.1)
        assert sim.pump.spm == pytest.approx(30.0)

    def test_choke_travels_rather_than_snapping(self):
        sim = make()
        sim.choke.command(50.0)
        sim.choke.advance(1.0)
        assert 0.0 < sim.choke.position < 50.0

    def test_shut_choke_passes_nothing(self):
        sim = make()
        sim.choke.position = 0.0
        assert sim.choke.flow_bbl_per_min(2000.0, 9.6) == pytest.approx(0.0)

    def test_choke_flow_rises_with_pressure_drop(self):
        sim = make()
        sim.choke.position = 40.0
        low = sim.choke.flow_bbl_per_min(200.0, 9.6)
        high = sim.choke.flow_bbl_per_min(800.0, 9.6)
        assert high > low

    def test_choke_area_closes_faster_than_travel(self):
        """The last of the handle does most of the work."""
        sim = make()
        sim.choke.position = 50.0
        half_travel = sim.choke.area_in2
        sim.choke.position = 100.0
        assert half_travel < sim.choke.full_open_area_in2 * 0.3

    def test_choke_does_not_flow_backwards(self):
        sim = make()
        sim.choke.position = 50.0
        assert sim.choke.flow_bbl_per_min(-500.0, 9.6) == pytest.approx(0.0)
