"""The forward engine: what the well does, given what the student does.

Everywhere else in this package the question is "what pressure must be held to
keep bottomhole pressure constant?" Here it is the opposite: the student has set
a choke position and a pump speed, and the well responds -- correctly if they
got it right, and badly if they did not.

## The equation the whole thing turns on

Surface pressure is not commanded. It emerges from a volume balance::

    dP/dt = (Q_in + q_influx - Q_out - q_loss) / capacitance

where ``capacitance`` is how many barrels the closed system swallows per psi::

    capacitance = V_mud x c_mud + V_gas / P_gas_absolute

That second term is the one that teaches. Mud is nearly incompressible, so with
little gas in the hole the capacitance is tiny, the system is **stiff**, and a
small choke movement swings casing pressure hundreds of psi. As gas rises and
expands at falling pressure, ``V_gas / P`` grows by orders of magnitude, the
system goes **soft**, and the same choke movement does almost nothing --
until the gas is at surface and it goes violent again.

Nothing about that is scripted. A student who learns to anticipate it has
learned to work a choke.

## What emerges rather than being coded

* Choke too open  -> BHP falls below pore pressure -> another influx (step 6)
* Choke too shut  -> shoe over-pressured -> losses, then breakdown (step 7)
* Choke shut with the pump running -> pressure spike (small capacitance)
* Pump started against a closed valve -> deadhead (no injection path)
* BOP left open -> returns up the flowline, casing pressure stays at zero, and
  the choke does nothing at all

## Deliberate simplifications

Single gas bubble, ideal and isothermal. Annular friction scaled from the
measured slow circulating rate by the square of pump speed. No gas going into
solution in oil-based mud. These are the same simplifications the rest of the
library makes, and they are documented rather than hidden.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..methods.base import FluidColumn, WellState, Zone
from ..units import PSI_PER_PPG_FT, psi_to_psia
from .equipment import AdjustableChoke, MudPump, PitSystem, TripTank
from .flowpath import FlowPath

#: Compressibility of mud, 1/psi. Includes a little for casing expansion.
MUD_COMPRESSIBILITY: float = 3.0e-6

#: Pressure downstream of the choke, psig. Atmospheric via the separator.
DOWNSTREAM_PRESSURE: float = 0.0


@dataclass
class SimState:
    """Everything that changes as the simulation runs."""

    time_s: float = 0.0
    casing_pressure_psi: float = 0.0
    standpipe_pressure_psi: float = 0.0
    #: Cumulative volume pumped into the string, which is what advances the
    #: annulus contents.
    pumped_bbl: float = 0.0
    strokes: float = 0.0
    influx_volume_bbl: float = 0.0
    influx_bottom_md: float = 0.0
    influx_top_md: float = 0.0
    bottomhole_pressure_psi: float = 0.0
    shoe_pressure_psi: float = 0.0
    flow_in_bpm: float = 0.0
    flow_out_bpm: float = 0.0
    influx_rate_bpm: float = 0.0
    loss_rate_bpm: float = 0.0
    kill_mud_pumped_bbl: float = 0.0
    gas_at_surface: bool = False
    well_is_dead: bool = False
    events: list[str] = field(default_factory=list)

    def log(self, message: str) -> None:
        minutes, seconds = divmod(int(self.time_s), 60)
        hours, minutes = divmod(minutes, 60)
        self.events.append(f"[{hours:02d}:{minutes:02d}:{seconds:02d}] {message}")


@dataclass
class Simulator:
    """A well, a rig, and a student's hands on the controls.

    Args:
        well: The well and the kick, reusing the library's model.
        flow_path: The lineup. Defaults to a rig lined up for normal drilling.
        pump: The mud pump.
        choke: The adjustable choke the student works.
        productivity_index: How hard the formation flows when underbalanced,
            bbl/min per psi of underbalance. Higher makes a well less
            forgiving.
        loss_index: How readily the shoe takes fluid once fractured, bbl/min
            per psi over the fracture pressure.
        kill_mud_weight_ppg: What is in the pits. Set to the original mud
            weight for a Driller's first circulation.
    """

    well: WellState
    flow_path: FlowPath = field(default_factory=FlowPath)
    pump: MudPump | None = None
    choke: AdjustableChoke = field(default_factory=AdjustableChoke)
    pits: PitSystem = field(default_factory=PitSystem)
    trip_tank: TripTank = field(default_factory=TripTank)
    productivity_index: float = 0.004
    loss_index: float = 0.01
    kill_mud_weight_ppg: float | None = None
    state: SimState = field(default_factory=SimState)

    def __post_init__(self) -> None:
        if self.pump is None:
            self.pump = MudPump(pump=self.well.pump)
        if self.kill_mud_weight_ppg is None:
            self.kill_mud_weight_ppg = self.well.mud_weight_ppg

        self.formation_pressure_psi = self.well.formation_pressure_psi
        self.frac_pressure_psi = self.well.frac_pressure_psi
        self._reset_geometry()

        # Start shut in on the recorded kick, so the student begins where the
        # kill sheet begins.
        self.state.influx_volume_bbl = self.well.pit_gain_bbl
        self._place_influx()
        self.state.casing_pressure_psi = self.well.sicp_psi
        self._gas_pv = self._gas_pressure_psia() * self.well.pit_gain_bbl
        self._update_pressures()
        self.state.log(
            f"Shut in. SIDPP {self.well.sidpp_psi:.0f} psi, "
            f"SICP {self.well.sicp_psi:.0f} psi, "
            f"pit gain {self.well.pit_gain_bbl:.1f} bbl."
        )

    # -- geometry ------------------------------------------------------------

    def _reset_geometry(self) -> None:
        self.annulus_volume_bbl = self.well.annulus.volume_bbl
        self.string_volume_bbl = self.well.annulus.string.internal_volume_bbl
        self.hole_md = self.well.hole_md_ft
        self.shoe_md = self.well.shoe_md
        self.influx_density_ppg = self.well.influx_density_ppg
        self.influx_gradient = self.well.influx_gradient_psi_per_ft

    def _place_influx(self) -> None:
        """Put the influx where the pumped volume and its own size say it is."""
        state = self.state
        below = min(state.pumped_bbl, self.annulus_volume_bbl)
        state.influx_bottom_md = self.well.annulus_md_at_volume_from_bottom(below)
        capacity_above = self.annulus_volume_bbl - below
        volume = max(0.0, min(state.influx_volume_bbl, capacity_above))
        state.influx_top_md = self.well.annulus_md_at_volume_from_bottom(
            below + volume
        )
        state.gas_at_surface = volume > 0 and state.influx_top_md <= 1.0

    def _annulus_column(self) -> FluidColumn:
        """The annulus as it currently stands, bottom to top."""
        state = self.state
        kill_in_annulus = max(0.0, state.pumped_bbl - self.string_volume_bbl)
        kill_in_annulus = min(kill_in_annulus, self.annulus_volume_bbl)
        kill_top_md = self.well.annulus_md_at_volume_from_bottom(kill_in_annulus)

        zones: list[Zone] = []
        if kill_in_annulus > 0:
            zones.append(
                Zone(kill_top_md, self.hole_md, self.kill_mud_weight_ppg,
                     "kill mud")
            )
        if state.influx_bottom_md < kill_top_md:
            zones.append(
                Zone(state.influx_bottom_md, kill_top_md,
                     self.well.mud_weight_ppg, "mud behind influx")
            )
        if state.influx_volume_bbl > 0 and state.influx_top_md < state.influx_bottom_md:
            zones.append(
                Zone(state.influx_top_md, state.influx_bottom_md,
                     self.influx_density_ppg, "influx")
            )
        if state.influx_top_md > 0:
            zones.append(
                Zone(0.0, state.influx_top_md, self.well.mud_weight_ppg,
                     "original mud")
            )
        return FluidColumn(zones, self.well.survey)

    # -- pressures -----------------------------------------------------------

    @property
    def _kill_rate_spm(self) -> float:
        return max(1.0, self.well.slow_circulating_rate.spm)

    def _annular_friction_psi(self) -> float:
        """Annular friction at the current pump speed.

        Taken as a fixed fraction of the measured slow circulating rate --
        annular loss is a small part of total system friction at kill rates --
        and scaled by the square of pump speed.
        """
        if not self.pump.running:
            return 0.0
        ratio = (self.pump.spm / self._kill_rate_spm) ** 2
        return 0.15 * self.well.slow_circulating_rate.pressure_psi * ratio

    def _update_pressures(self) -> None:
        state = self.state
        column = self._annulus_column()

        state.bottomhole_pressure_psi = (
            state.casing_pressure_psi
            + column.total_hydrostatic
            + self._annular_friction_psi()
        )
        state.shoe_pressure_psi = (
            column.pressure_at(self.shoe_md, state.casing_pressure_psi)
            if self.shoe_md is not None else 0.0
        )

        # Standpipe pressure reads back down the string from the bit.
        kill_in_string = min(state.pumped_bbl, self.string_volume_bbl)
        front_md = self.well.kill_sheet.kill_mud_depth_at_volume(kill_in_string)
        front_tvd = self.well.survey.tvd_at(front_md)
        string_hydrostatic = (
            PSI_PER_PPG_FT * self.kill_mud_weight_ppg * front_tvd
            + PSI_PER_PPG_FT * self.well.mud_weight_ppg
            * (self.well.bit_tvd_ft - front_tvd)
        )
        friction = 0.0
        if self.pump.running:
            ratio = (self.pump.spm / self._kill_rate_spm) ** 2
            friction = self.well.slow_circulating_rate.pressure_psi * ratio
        state.standpipe_pressure_psi = max(
            0.0,
            state.bottomhole_pressure_psi - string_hydrostatic + friction,
        )

    # -- capacitance ---------------------------------------------------------

    def _capacitance_bbl_per_psi(self) -> float:
        """How many barrels the closed system absorbs per psi.

        The single most important number in the model. Mud contributes almost
        nothing; free gas contributes ``V/P`` and dominates once there is any.
        """
        state = self.state
        gas = state.influx_volume_bbl
        mud = max(0.0, self.annulus_volume_bbl + self.string_volume_bbl - gas)

        capacitance = mud * MUD_COMPRESSIBILITY
        if gas > 0:
            column = self._annulus_column()
            midpoint = (state.influx_top_md + state.influx_bottom_md) / 2.0
            gas_pressure = column.pressure_at(midpoint, state.casing_pressure_psi)
            capacitance += gas / max(psi_to_psia(gas_pressure), 20.0)
        # Never zero: a perfectly incompressible closed system would divide by
        # zero and is not physical anyway.
        return max(capacitance, 1e-6)

    # -- the step ------------------------------------------------------------

    def step(self, dt: float = 0.05) -> SimState:
        """Advance the simulation by ``dt`` seconds."""
        state = self.state
        minutes = dt / 60.0

        self.pump.advance(dt)
        self.choke.advance(dt)

        route = self.flow_path.return_route()
        deadheaded = self.flow_path.pump_is_deadheaded

        # -- flow in ---------------------------------------------------------
        flow_in = 0.0 if deadheaded else self.pump.flow_bbl_per_min
        state.flow_in_bpm = flow_in
        if deadheaded and self.pump.running and "deadhead" not in " ".join(
            state.events[-3:]
        ):
            state.log("Pump running against a closed valve — deadheaded.")

        # -- flow out --------------------------------------------------------
        returns_density = (
            self.influx_density_ppg if state.gas_at_surface
            else self.well.mud_weight_ppg
        )
        if not route.open_to_pits:
            flow_out = 0.0
        elif not route.through_choke:
            # Flowline: the well is open to atmosphere. Whatever goes in comes
            # out and there is no pressure control at all.
            flow_out = flow_in + state.influx_rate_bpm
            state.casing_pressure_psi = 0.0
        elif self.flow_path.bypass_is_open():
            flow_out = flow_in + state.influx_rate_bpm
            state.casing_pressure_psi = max(0.0, state.casing_pressure_psi - 50.0 * dt)
        else:
            chokes = self.flow_path.active_chokes()
            drop = state.casing_pressure_psi - DOWNSTREAM_PRESSURE
            flow_out = (
                self.choke.flow_bbl_per_min(drop, returns_density)
                if chokes else 0.0
            )
        state.flow_out_bpm = flow_out

        # -- the formation's response ----------------------------------------
        underbalance = self.formation_pressure_psi - state.bottomhole_pressure_psi
        influx_rate = self.productivity_index * underbalance if underbalance > 0 else 0.0
        state.influx_rate_bpm = influx_rate

        loss_rate = 0.0
        if self.frac_pressure_psi is not None:
            over = state.shoe_pressure_psi - self.frac_pressure_psi
            if over > 0:
                loss_rate = self.loss_index * over
                if not any("break" in e for e in state.events[-5:]):
                    state.log(
                        f"Shoe over-pressured by {over:.0f} psi — taking losses."
                    )
        state.loss_rate_bpm = loss_rate

        # -- volume balance drives surface pressure --------------------------
        if route.open_to_pits and not route.through_choke:
            pass  # open hole to atmosphere; casing pressure pinned at zero
        else:
            net = (flow_in + influx_rate - flow_out - loss_rate) * minutes
            state.casing_pressure_psi = max(
                0.0,
                state.casing_pressure_psi + net / self._capacitance_bbl_per_psi(),
            )

        # -- advance the well ------------------------------------------------
        state.pumped_bbl += flow_in * minutes
        state.strokes += self.pump.strokes_in(dt)
        if self.kill_mud_weight_ppg != self.well.mud_weight_ppg:
            state.kill_mud_pumped_bbl = min(state.pumped_bbl, self.string_volume_bbl)

        # New gas enters at bottomhole pressure and joins the inventory.
        if influx_rate > 0:
            self._gas_pv += psi_to_psia(state.bottomhole_pressure_psi) * (
                influx_rate * minutes
            )
            if not any("influx" in e for e in state.events[-4:]):
                state.log(
                    f"Underbalanced by {underbalance:.0f} psi — taking an influx."
                )

        # Gas reaching surface leaves with the returns.
        if state.gas_at_surface and flow_out > 0 and route.through_choke:
            if state.influx_volume_bbl > 0:
                fraction = min(
                    1.0, (flow_out * minutes) / state.influx_volume_bbl
                )
                self._gas_pv *= 1.0 - fraction

        self._settle_gas()

        # -- pits ------------------------------------------------------------
        self.pits.active_bbl += (flow_out - flow_in) * minutes

        state.time_s += dt
        self._update_pressures()
        self._check_dead()
        return state

    def _gas_pressure_psia(self) -> float:
        """Pressure at the middle of the gas, absolute."""
        state = self.state
        column = self._annulus_column()
        midpoint = (state.influx_top_md + state.influx_bottom_md) / 2.0
        return max(
            psi_to_psia(
                column.pressure_at(midpoint, state.casing_pressure_psi)
            ),
            20.0,
        )

    def _settle_gas(self) -> None:
        """Resolve gas volume and position together.

        The inventory ``self._gas_pv`` is the conserved quantity -- pressure
        times volume, which stands in for moles. Volume follows from it at
        whatever pressure the gas currently sits at.

        Volume and pressure are mutually dependent: a taller gas column changes
        the hydrostatic above it, which changes its pressure, which changes its
        volume. Two passes settle it to well inside the resolution of anything
        the student can read off a gauge.
        """
        state = self.state
        if self._gas_pv <= 0.0:
            state.influx_volume_bbl = 0.0
            self._place_influx()
            return

        for _ in range(2):
            state.influx_volume_bbl = self._gas_pv / self._gas_pressure_psia()
            self._place_influx()

    def _check_dead(self) -> None:
        state = self.state
        if state.well_is_dead:
            return
        killed = (
            state.influx_volume_bbl < 0.5
            and state.casing_pressure_psi < 25.0
            and state.bottomhole_pressure_psi >= self.formation_pressure_psi
        )
        if killed and state.pumped_bbl > self.string_volume_bbl:
            state.well_is_dead = True
            state.log("Well is dead — no influx, no surface pressure.")

    # -- convenience ---------------------------------------------------------

    def run(self, seconds: float, dt: float = 0.05) -> SimState:
        """Advance by a stretch of time, holding the current settings."""
        steps = max(1, int(round(seconds / dt)))
        for _ in range(steps):
            self.step(dt)
        return self.state

    def readout(self) -> dict[str, object]:
        """What the gauges say, for a panel or a debrief."""
        state = self.state
        return {
            "Time (min)": round(state.time_s / 60.0, 1),
            "Pump (spm)": round(self.pump.spm, 1),
            "Choke (%)": round(self.choke.position, 1),
            "Standpipe (psi)": round(state.standpipe_pressure_psi),
            "Casing (psi)": round(state.casing_pressure_psi),
            "Bottomhole (psi)": round(state.bottomhole_pressure_psi),
            "Formation (psi)": round(self.formation_pressure_psi),
            "Overbalance (psi)": round(
                state.bottomhole_pressure_psi - self.formation_pressure_psi
            ),
            "Shoe (psi)": round(state.shoe_pressure_psi),
            "Strokes": round(state.strokes),
            "Influx (bbl)": round(state.influx_volume_bbl, 1),
            "Influx top (ft MD)": round(state.influx_top_md),
            "Flow in (bpm)": round(state.flow_in_bpm, 2),
            "Flow out (bpm)": round(state.flow_out_bpm, 2),
            "Pit gain (bbl)": round(self.pits.gain_bbl, 1),
            "Returns": self.flow_path.return_route().description,
        }
