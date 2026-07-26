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
from enum import Enum

from ..hydrostatics import expanded_gas_density
from ..methods.base import FluidColumn, WellState, Zone
from ..units import PSI_PER_PPG_FT, psi_to_psia
from .assessment import (
    Assessment,
    EventKind,
    EventLog,
    Severity,
    Standard,
    TraceSample,
)  # noqa: F401  -- Severity is used throughout the event calls below
from .equipment import AdjustableChoke, MudPump, PitSystem, TripTank
from .flowpath import FlowPath

#: Compressibility of mud, 1/psi. Includes a little for casing expansion.
MUD_COMPRESSIBILITY: float = 3.0e-6

#: Pressure downstream of the choke, psig. Atmospheric via the separator.
DOWNSTREAM_PRESSURE: float = 0.0

#: How much the mud is overbalanced on the zone being drilled, psi, before the
#: well drills into anything it cannot hold. Enough to be comfortably stable,
#: little enough that the kick is not absurd when it comes.
DRILLING_OVERBALANCE_PSI: float = 150.0

#: Productivity index, bbl/min per psi of underbalance, for a shut-in start.
#: The kick is already in the hole there, so this only governs what happens if
#: the student lets the well go underbalanced again.
TIGHT_PRODUCTIVITY_INDEX: float = 0.004

#: Overbalance needed before the formation will take fluid at all, psi.
#:
#: A zone does not start accepting mud the moment it is overbalanced. Filter
#: cake, near-wellbore skin and relative permeability all have to be pushed
#: through first, which is why a well can sit a hundred psi overbalanced all day
#: without losing anything. It also keeps a normal kill -- flown a few tens of
#: psi above pore pressure -- from quietly bleeding into the formation, and it
#: is why bullheading needs real pressure rather than a nudge.
INJECTION_THRESHOLD_PSI: float = 300.0

#: How readily the zone takes fluid once that threshold is passed, bbl/min per
#: psi. Much lower than the productivity index in the other direction: a gas
#: sand gives up gas far more easily than it accepts mud.
INJECTION_INDEX: float = 0.004

#: Representative gas migration rate, ft/hr, where nobody has measured one.
#: Field figures run from a few hundred to a couple of thousand; 1,000 is the
#: number the teaching content works to.
DEFAULT_MIGRATION_FT_PER_HR: float = 1000.0

#: Productivity index for a drilling start. Higher, because the kick has to
#: **develop while the student is watching**. A tight zone bleeding in at a
#: fraction of a barrel a minute is realistic for some wells and useless as an
#: exercise: the pit gain takes an hour to become visible. This is a permeable
#: sand, which is also the case worth training for.
LIVE_PRODUCTIVITY_INDEX: float = 0.02


class StartState(str, Enum):
    """Where a session begins.

    ``SHUT_IN`` hands the student a kick that is already in the hole, sized and
    identified, with the pressures on the gauges. That is an exercise in working
    a choke.

    ``DRILLING`` hands them a well that is behaving. The kick has not happened
    yet; when it does they have to **notice it** -- pit gain, and flow out
    exceeding flow in -- shut in on their own initiative, and read their own
    shut-in pressures off the gauges. Everything the shut-in start gives away is
    something they have to earn.

    The second is the one that makes this a simulator rather than a trainer, and
    it carries a check the first cannot: the shut-in pressures that emerge from
    the volume balance have to agree with what the kill sheet says they should
    be. Nothing tells the engine what SIDPP ought to read.
    """

    SHUT_IN = "shut_in"
    DRILLING = "drilling"


@dataclass
class SimState:
    """Everything that changes as the simulation runs."""

    time_s: float = 0.0
    casing_pressure_psi: float = 0.0
    standpipe_pressure_psi: float = 0.0
    #: Cumulative volume pumped into the string, which is what advances the
    #: annulus contents.
    pumped_bbl: float = 0.0
    #: Annular volume the influx has climbed past under its own buoyancy,
    #: as distinct from what the pump has displaced beneath it.
    migrated_bbl: float = 0.0
    strokes: float = 0.0
    influx_volume_bbl: float = 0.0
    influx_bottom_md: float = 0.0
    influx_top_md: float = 0.0
    bottomhole_pressure_psi: float = 0.0
    shoe_pressure_psi: float = 0.0
    flow_in_bpm: float = 0.0
    flow_out_bpm: float = 0.0
    influx_rate_bpm: float = 0.0
    #: Fluid going back into the kicking zone, bbl/min. Bullheading is the
    #: deliberate case; it is also what a badly over-pressured well does.
    injection_rate_bpm: float = 0.0
    #: Cumulative volume squeezed back into the formation, bbl.
    injected_bbl: float = 0.0
    loss_rate_bpm: float = 0.0
    kill_mud_pumped_bbl: float = 0.0
    #: Volume taken out through the choke with the pump off. The Volumetric
    #: method is executed by bleeding *measured* increments, so this is the
    #: instrument the whole method is worked to, not a diagnostic.
    bled_bbl: float = 0.0
    gas_at_surface: bool = False
    well_is_dead: bool = False

    # -- recorded for the debrief -------------------------------------------
    #: Structured log. Prefer this to :attr:`events`, which is the same thing
    #: flattened to strings.
    event_log: EventLog = field(default_factory=EventLog)
    trace: list[TraceSample] = field(default_factory=list)

    #: Time integrals. Only the engine sees every timestep, so it accumulates
    #: these rather than letting the assessor sample them off the trace and
    #: miss short excursions between samples.
    seconds_outside_band: float = 0.0
    influx_taken_bbl: float = 0.0
    lost_bbl: float = 0.0

    #: Running extremes, for the same reason.
    max_bhp_excursion_psi: float = 0.0
    peak_casing_pressure_psi: float = 0.0
    peak_shoe_pressure_psi: float = 0.0

    @property
    def events(self) -> list[str]:
        """The log as printable lines."""
        return self.event_log.messages

    def record(self, kind: EventKind, message: str, **kwargs) -> None:
        self.event_log.record(kind, message, time_s=self.time_s, **kwargs)

    def set_condition(self, kind: EventKind, active: bool, **kwargs) -> None:
        self.event_log.set_condition(kind, active, time_s=self.time_s, **kwargs)

    def set_level(self, kind: EventKind, value: float, **kwargs) -> None:
        self.event_log.set_level(kind, value, time_s=self.time_s, **kwargs)


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
    #: bbl/min per psi of underbalance. None picks a default from the start
    #: state: a drilling kick has to develop while the student watches, where a
    #: shut-in start only needs this if they lose control again.
    productivity_index: float | None = None
    #: bbl/min per psi of overbalance beyond INJECTION_THRESHOLD_PSI.
    injection_index: float = INJECTION_INDEX
    loss_index: float = 0.01
    kill_mud_weight_ppg: float | None = None
    #: How fast gas climbs through the mud, ft/hr. None takes the well's own
    #: figure, which is zero where migration is not reliable.
    migration_rate_ft_per_hr: float | None = None
    #: Where the session begins. See :class:`StartState`.
    start: StartState = StartState.SHUT_IN
    #: Seconds of *circulating* before the bit drills into the kicking zone.
    #: Only used from a drilling start. None leaves the kick to be triggered by
    #: hand, which is how an instructor injects it.
    kick_after_s: float | None = 120.0
    #: Bottomhole pressure counts as on target within this much of formation
    #: pressure. The engine needs it because time-off-target is a time integral.
    bhp_band_psi: float = 50.0
    #: How often the trace is sampled, in simulated seconds.
    trace_interval_s: float = 10.0
    state: SimState = field(default_factory=SimState)

    def __post_init__(self) -> None:
        if self.pump is None:
            self.pump = MudPump(pump=self.well.pump)
        if self.kill_mud_weight_ppg is None:
            self.kill_mud_weight_ppg = self.well.mud_weight_ppg
        if self.productivity_index is None:
            self.productivity_index = (
                LIVE_PRODUCTIVITY_INDEX if self.start is StartState.DRILLING
                else TIGHT_PRODUCTIVITY_INDEX
            )

        self.formation_pressure_psi = self.well.formation_pressure_psi
        self.frac_pressure_psi = self.well.frac_pressure_psi
        self._reset_geometry()

        # Set before the first column is built, because the density of the gas
        # is measured against them. At shut-in the gas is at its reference
        # state, so the fallback in _influx_density_ppg is the right answer
        # until these are filled in below.
        self._initial_gas_pv = 0.0
        self._initial_gas_volume_bbl = self.well.pit_gain_bbl

        #: Pore pressure once the kicking zone is drilled. Held aside from
        #: ``formation_pressure_psi`` so a drilling start can raise it later.
        self.kick_pressure_psi = self.well.formation_pressure_psi
        self.kick_taken = self.start is StartState.SHUT_IN
        self._circulating_s = 0.0

        if self.start is StartState.SHUT_IN:
            self._begin_shut_in()
        else:
            self._begin_drilling()

        self._next_sample_s = 0.0
        self._record_sample()

    def _begin_shut_in(self) -> None:
        """The kick is already in the hole and the well is closed on it."""
        self.state.influx_volume_bbl = self.well.pit_gain_bbl
        self._place_influx()
        self.state.casing_pressure_psi = self.well.sicp_psi
        self._gas_pv = self._gas_pressure_psia() * self.well.pit_gain_bbl
        self._initial_gas_pv = self._gas_pv
        self._update_pressures()
        self.state.record(
            EventKind.SHUT_IN,
            f"Shut in. SIDPP {self.well.sidpp_psi:.0f} psi, "
            f"SICP {self.well.sicp_psi:.0f} psi, "
            f"pit gain {self.well.pit_gain_bbl:.1f} bbl.",
            sidpp_psi=self.well.sidpp_psi,
            sicp_psi=self.well.sicp_psi,
            pit_gain_bbl=self.well.pit_gain_bbl,
        )

    def _begin_drilling(self) -> None:
        """A well that is behaving, on a zone the mud can hold.

        Pore pressure starts below the static mud column by
        :data:`DRILLING_OVERBALANCE_PSI`, so nothing flows until the bit reaches
        the zone the mud weight cannot hold. Nothing is placed in the annulus
        and no surface pressure is set: whatever the student ends up reading,
        they made happen.
        """
        self.state.influx_volume_bbl = 0.0
        self.state.casing_pressure_psi = 0.0
        self._gas_pv = 0.0
        self._initial_gas_pv = 0.0
        self._initial_gas_volume_bbl = 0.0
        self._place_influx()

        hydrostatic = self._annulus_column().total_hydrostatic
        self.formation_pressure_psi = hydrostatic - DRILLING_OVERBALANCE_PSI
        self._update_pressures()

        self.state.record(
            EventKind.DRILLING,
            f"Drilling ahead at {self.well.bit_md_ft:,.0f} ft. Mud "
            f"{self.well.mud_weight_ppg:.1f} ppg, "
            f"{DRILLING_OVERBALANCE_PSI:.0f} psi overbalanced. "
            "Watch the pit level and the flow line.",
            bit_md_ft=self.well.bit_md_ft,
        )

    def trigger_kick(self) -> None:
        """Drill into the zone the mud weight cannot hold.

        Pore pressure steps up to what the kill sheet was built on, which is how
        a kick actually arrives -- the mud was adequate, and then it was not.
        Nothing else is done to the well: the influx enters through the same
        productivity-index response as any other underbalance, so the pit gain
        and the flow-out excess the student is watching for are consequences,
        not a script.
        """
        if self.kick_taken:
            return
        self.kick_taken = True
        self.formation_pressure_psi = self.kick_pressure_psi
        self.state.record(
            EventKind.KICK_ZONE_DRILLED,
            "Drilled into a higher pressure zone.",
            severity=Severity.INFO,
            pore_pressure_psi=self.kick_pressure_psi,
        )

    # -- geometry ------------------------------------------------------------

    def _reset_geometry(self) -> None:
        self.annulus_volume_bbl = self.well.annulus.volume_bbl
        self.string_volume_bbl = self.well.annulus.string.internal_volume_bbl
        self.hole_md = self.well.hole_md_ft
        self.shoe_md = self.well.shoe_md
        self.influx_density_ppg = self.well.influx_density_ppg
        self.influx_gradient = self.well.influx_gradient_psi_per_ft
        if self.migration_rate_ft_per_hr is None:
            self.migration_rate_ft_per_hr = self._default_migration_rate()

    def _place_influx(self) -> None:
        """Put the influx where the mud beneath it says it is.

        Two things put mud under the influx: what the pump has displaced round
        the bit, and what the gas has climbed past under its own buoyancy.
        """
        state = self.state
        below = min(
            state.pumped_bbl + state.migrated_bbl, self.annulus_volume_bbl
        )
        state.influx_bottom_md = self.well.annulus_md_at_volume_from_bottom(below)
        capacity_above = self.annulus_volume_bbl - below
        volume = max(0.0, min(state.influx_volume_bbl, capacity_above))
        state.influx_top_md = self.well.annulus_md_at_volume_from_bottom(
            below + volume
        )
        state.gas_at_surface = volume > 0 and state.influx_top_md <= 1.0

    def _influx_density_ppg(self) -> float:
        """Density of the gas as it currently stands, ppg.

        A fixed mass of gas in a bigger volume is lighter, so density falls as
        the bubble expands on its way up. Holding the shut-in density would
        create gas mass from nothing, and the resulting excess hydrostatic
        under-states casing pressure -- by 182 psi at the peak on the reference
        well, which is the wrong direction to be wrong in.

        Unlike the planner's one-way circulation, the simulator can take *more*
        gas when the student lets the well go underbalanced, so this scales by
        mass as well as by volume. ``_gas_pv`` stands in for the mass: at fixed
        temperature ``PV`` is proportional to how many moles are down there.
        """
        state = self.state
        if state.influx_volume_bbl <= 0.0 or self._initial_gas_pv <= 0.0:
            return self.influx_density_ppg
        mass_ratio = self._gas_pv / self._initial_gas_pv
        return mass_ratio * expanded_gas_density(
            self.influx_density_ppg,
            self._initial_gas_volume_bbl,
            state.influx_volume_bbl,
        )

    def _default_migration_rate(self) -> float:
        """How fast gas climbs, ft/hr, when nobody has measured it.

        **The planner and the simulator mean different things by zero.**
        ``WellState.gas_migration_rate_ft_per_hr`` is a *measured* rate, and
        zero there means "do not assume the gas is migrating" -- the right
        conservative default when planning, because a method that depends on
        migration should not be recommended on an assumption.

        A simulator cannot take that view. The well does what it does, and gas
        in a vertical hole rises whether or not anybody put a number on it. So
        a measured rate wins where there is one, and otherwise the gas migrates
        at a representative rate wherever the trajectory gives it an up to go
        in. In a lateral it stays where it is, which is the whole reason
        Volumetric is blocked on horizontal wells.
        """
        measured = self.well.gas_migration_rate_ft_per_hr
        if measured > 0.0:
            return measured
        if self.well.configuration.trajectory.migration_reliable:
            return DEFAULT_MIGRATION_FT_PER_HR
        return 0.0

    def _migrate_gas(self, dt: float) -> float:
        """Let the influx climb, and return the expansion it wants, bbl.

        **Gas migrating in a shut-in well takes its pressure with it.** It
        cannot expand -- the well is closed and mud is nearly incompressible --
        so a bubble that rises 1,000 ft arrives still carrying the pressure it
        had 1,000 ft lower. The mud now beneath it adds its own hydrostatic on
        top, and bottomhole pressure climbs. Left alone it will break the shoe;
        bleeding it off in controlled steps is the Volumetric method, and this
        is the physics that method exists to answer.

        Rather than special-case the pressure rise, this returns the volume the
        gas *would* take up at its new depth if it were free to expand, and the
        caller feeds that into the same volume balance as everything else. In a
        closed system the balance turns it into pressure, and the arithmetic
        comes out at the textbook answer::

            dP = (dV_wanted) / capacitance
               = (V (rho dh) / P) / (V / P)
               = rho dh

        -- the mud gradient times the distance climbed, which is exactly what a
        gauge on a shut-in well does. Getting that for free is the reason for
        expressing it this way rather than adding a rule.

        Gas that has reached surface has nowhere further to go, and gas in a
        lateral has no "up" to go in, so both return zero.
        """
        state = self.state
        if state.influx_volume_bbl <= 0.0 or self.migration_rate_ft_per_hr <= 0.0:
            return 0.0
        if state.influx_top_md <= 1.0:
            return 0.0

        feet = self.migration_rate_ft_per_hr * dt / 3600.0
        if feet <= 0.0:
            return 0.0

        # A lateral has no vertical component for buoyancy to act on, and the
        # survey is what says so.
        climb = self.well.survey.vertical_height_of(
            max(0.0, state.influx_top_md - feet), state.influx_top_md
        )
        if climb <= 1e-6:
            return 0.0

        before_psia = self._gas_pressure_psia()
        # Measured at the influx *top*, because the position is parameterised
        # by the volume beneath the bubble and the top is the leading edge --
        # it is what decides when gas reaches the casing shoe and then surface.
        # Taking it at the bottom instead made the bubble climb at two thirds
        # of the stated rate wherever the annulus widened above it. The bottom
        # then rises faster than the top, which is correct: a fixed volume
        # moving into a wider annulus gets shorter.
        capacity = self.well.annulus.capacity_at(state.influx_top_md)
        state.migrated_bbl = min(
            state.migrated_bbl + capacity * feet, self.annulus_volume_bbl
        )
        self._place_influx()
        after_psia = self._gas_pressure_psia()

        if after_psia >= before_psia:
            return 0.0
        return self._gas_pv / after_psia - self._gas_pv / before_psia

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
                     self._influx_density_ppg(), "influx")
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

        # Drilling only makes hole while the pump is actually turning, so the
        # kick arrives after a stretch of circulating rather than after a
        # stretch of wall-clock time. A student who never starts the pump never
        # drills into anything.
        if not self.kick_taken and self.kick_after_s is not None:
            if self.pump.running and not deadheaded:
                self._circulating_s += dt
                if self._circulating_s >= self.kick_after_s:
                    self.trigger_kick()

        # -- flow in ---------------------------------------------------------
        flow_in = 0.0 if deadheaded else self.pump.flow_bbl_per_min
        state.flow_in_bpm = flow_in
        state.set_condition(
            EventKind.PUMP_DEADHEADED,
            deadheaded and self.pump.running,
            message="Pump running against a closed valve — deadheaded.",
            severity=Severity.WARNING,
            cleared_message="Injection path restored — the pump is delivering.",
        )

        # -- flow out --------------------------------------------------------
        returns_density = (
            self._influx_density_ppg() if state.gas_at_surface
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
        # It works both ways. Underbalanced it gives up gas; pushed hard enough
        # it takes fluid back, which is the whole of bullheading. The threshold
        # between them is not zero -- see INJECTION_THRESHOLD_PSI.
        underbalance = self.formation_pressure_psi - state.bottomhole_pressure_psi
        influx_rate = self.productivity_index * underbalance if underbalance > 0 else 0.0
        state.influx_rate_bpm = influx_rate

        squeeze = -underbalance - INJECTION_THRESHOLD_PSI
        injection_rate = self.injection_index * squeeze if squeeze > 0 else 0.0
        state.injection_rate_bpm = injection_rate

        loss_rate = 0.0
        over = 0.0
        if self.frac_pressure_psi is not None:
            over = state.shoe_pressure_psi - self.frac_pressure_psi
            if over > 0:
                loss_rate = self.loss_index * over
        state.loss_rate_bpm = loss_rate
        state.set_level(
            EventKind.LOSSES,
            over,
            rises_above=5.0,
            falls_below=1.0,
            message=f"Shoe over-pressured by {over:.0f} psi — taking losses.",
            severity=Severity.CRITICAL,
            cleared_message="Shoe pressure back below fracture — losses stopped.",
            over_psi=over,
        )

        # -- the influx climbs under its own buoyancy ------------------------
        # Returns the expansion it wants at its new depth. Closed in, there is
        # nowhere to put that volume and it becomes pressure instead.
        migration_bbl = self._migrate_gas(dt)

        # -- volume balance drives surface pressure --------------------------
        if route.open_to_pits and not route.through_choke:
            pass  # open hole to atmosphere; casing pressure pinned at zero
        else:
            net = (
                (
                    flow_in + influx_rate
                    - flow_out - loss_rate - injection_rate
                ) * minutes
                + migration_bbl
            )
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
            if self._initial_gas_pv <= 0.0:
                # First gas of a drilling start. Fix the reference state here:
                # it came in at formation pressure, where its density is the
                # influx density the well reports. Everything after this is
                # measured against it, and because the ratio works out to
                # P / P_reference it stays right however much more comes in.
                self._initial_gas_pv = self._gas_pv
                self._initial_gas_volume_bbl = self._gas_pv / psi_to_psia(
                    self.formation_pressure_psi
                )
        # Logged on a meaningful underbalance rather than on any at all: a
        # well held within a psi or two of balance drifts either side of it
        # constantly, and "taking an influx" is the wrong thing to tell a
        # student who is flying it correctly. The volume taken is still
        # integrated in full, however small the rate.
        state.set_level(
            EventKind.INFLUX_TAKEN,
            underbalance,
            rises_above=10.0,
            falls_below=2.0,
            message=f"Underbalanced by {underbalance:.0f} psi — taking an influx.",
            severity=Severity.CRITICAL,
            cleared_message="Back overbalanced — the influx has stopped.",
            underbalance_psi=underbalance,
        )

        # Fluid squeezed back into the zone takes the influx with it. The gas
        # sits against the formation it came from, so it is what goes back
        # first -- which is the assumption bullheading is built on, and the
        # reason the method is unreliable once the influx has risen away from
        # the zone.
        if injection_rate > 0:
            pushed_back = injection_rate * minutes
            state.injected_bbl += pushed_back
            if state.influx_volume_bbl > 1e-9:
                fraction = min(1.0, pushed_back / state.influx_volume_bbl)
                self._gas_pv *= 1.0 - fraction

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

        # -- what the run will be judged on ----------------------------------
        state.influx_taken_bbl += influx_rate * minutes
        state.lost_bbl += loss_rate * minutes

        # Bleeding is what comes out with nothing going in. With the pump
        # running this is circulating returns and means something else.
        if not self.pump.running and route.through_choke:
            state.bled_bbl += flow_out * minutes

        state.time_s += dt
        self._update_pressures()
        self._check_dead()
        self._accumulate(dt, route)
        self._sample_if_due()
        return state

    # -- recording -----------------------------------------------------------

    def _accumulate(self, dt: float, route) -> None:
        """Running totals and conditions, evaluated once pressures are current.

        Time off target has to be integrated here rather than sampled off the
        trace: a student can swing 300 psi and recover between two samples, and
        that must not vanish from the debrief.
        """
        state = self.state

        excursion = abs(
            state.bottomhole_pressure_psi - self.formation_pressure_psi
        )
        # Only meaningful once there is a kick to hold. Drilling ahead is
        # deliberately overbalanced, so measuring that against pore pressure
        # would score correct practice as an excursion.
        killing = self.kick_taken
        if killing and excursion > self.bhp_band_psi:
            state.seconds_outside_band += dt
        state.max_bhp_excursion_psi = max(state.max_bhp_excursion_psi, excursion)
        state.peak_casing_pressure_psi = max(
            state.peak_casing_pressure_psi, state.casing_pressure_psi
        )
        state.peak_shoe_pressure_psi = max(
            state.peak_shoe_pressure_psi, state.shoe_pressure_psi
        )

        state.set_level(
            EventKind.BHP_EXCURSION,
            excursion if killing else 0.0,
            rises_above=self.bhp_band_psi,
            falls_below=0.6 * self.bhp_band_psi,
            message=(
                f"Bottomhole pressure {excursion:.0f} psi off formation "
                f"pressure."
            ),
            severity=Severity.CAUTION,
            cleared_message="Bottomhole pressure back on target.",
        )

        # Circulating with the stack open is the lesson students most need: the
        # choke does nothing and the well is not under control at all.
        state.set_condition(
            EventKind.WELL_OPEN_TO_FLOWLINE,
            self.pump.running and route.open_to_pits and not route.through_choke,
            message=(
                "Circulating with the BOP open — returns are going up the "
                "flowline and the choke has no effect."
            ),
            severity=Severity.CRITICAL,
        )
        state.set_condition(
            EventKind.NO_RETURNS,
            self.pump.running and not route.open_to_pits,
            message="Pumping into a closed system — no returns route.",
            severity=Severity.WARNING,
            cleared_message="Returns route open.",
        )

        # -- the two things a driller watches to catch a kick ----------------
        # Flow out exceeding flow in comes first and is the more sensitive of
        # the two; the pit gain follows once enough has come in to see. Both
        # are consequences of the volume balance, so a student who is watching
        # gets the same warning a real one does, at the same point.
        state.set_level(
            EventKind.FLOW_CHECK,
            state.flow_out_bpm - state.flow_in_bpm,
            rises_above=0.4,
            falls_below=0.1,
            message="Flow out is greater than flow in — the well is flowing.",
            severity=Severity.CRITICAL,
            cleared_message="Flow out back in balance with flow in.",
        )
        state.set_level(
            EventKind.PIT_GAIN,
            self.pits.gain_bbl,
            rises_above=5.0,
            falls_below=2.0,
            message=(
                f"Pit gain {self.pits.gain_bbl:.1f} bbl and rising."
            ),
            severity=Severity.CRITICAL,
            cleared_message="Pit level back to baseline.",
        )

        # The moment of truth on a drilling start. Two events, not one: the
        # well being closed in, and -- later -- the pressures having settled.
        # Quoting the gauges at the instant of shut-in would report numbers
        # still climbing through the influx, which is exactly the mistake the
        # message is warning against.
        closed_in = (
            self.flow_path.bop_is_closed
            and not self.pump.running
            and state.influx_volume_bbl > 0
        )
        if closed_in:
            state.record(
                EventKind.WELL_SHUT_IN_BY_STUDENT,
                "Well shut in. Let the pressures stabilise before reading them.",
                severity=Severity.INFO,
                once=True,
            )
        # "Stable" means the influx condition has cleared, not that the rate is
        # exactly zero: as the well comes back into balance the underbalance
        # hovers a psi or two above nothing, so a literal zero never arrives.
        # Reusing the hysteresis keeps the log and the gauges telling the same
        # story.
        if (
            closed_in
            and not state.event_log.is_active(EventKind.INFLUX_TAKEN)
            and state.event_log.has(EventKind.WELL_SHUT_IN_BY_STUDENT)
        ):
            state.record(
                EventKind.SHUT_IN,
                f"Pressures stable. SIDPP {state.standpipe_pressure_psi:.0f} psi, "
                f"SICP {state.casing_pressure_psi:.0f} psi, "
                f"pit gain {self.pits.gain_bbl:.1f} bbl. "
                "Build the kill sheet from these.",
                severity=Severity.INFO,
                once=True,
            )

        maasp = self.maasp_psi
        if maasp is not None:
            state.set_level(
                EventKind.MAASP_EXCEEDED,
                state.casing_pressure_psi,
                rises_above=maasp,
                falls_below=maasp - 25.0,
                message=(
                    f"Casing pressure {state.casing_pressure_psi:.0f} psi is "
                    f"above MAASP ({maasp:.0f} psi)."
                ),
                severity=Severity.WARNING,
                cleared_message="Casing pressure back below MAASP.",
            )

        # Shut in, not circulating, and the pressure climbing anyway: the well
        # is telling the student the gas is migrating and that doing nothing is
        # not an option. This is the cue the Volumetric method answers.
        state.set_condition(
            EventKind.GAS_MIGRATING,
            (
                self.flow_path.bop_is_closed
                and not self.pump.running
                and state.influx_volume_bbl > 0
                and self.migration_rate_ft_per_hr > 0
                and not state.gas_at_surface
            ),
            message=(
                "Shut in and the gas is migrating — surface pressure will keep "
                "climbing on its own. Bleed in measured steps to hold "
                "bottomhole pressure, or the shoe takes it."
            ),
            severity=Severity.CAUTION,
            cleared_message="Migration no longer driving the pressure.",
        )

        if state.gas_at_surface:
            state.record(
                EventKind.GAS_AT_SURFACE,
                "Gas at surface — expect the choke to go violent.",
                severity=Severity.CAUTION,
                once=True,
            )
        if (
            self.kill_mud_weight_ppg != self.well.mud_weight_ppg
            and state.pumped_bbl >= self.string_volume_bbl
        ):
            state.record(
                EventKind.KILL_MUD_AT_BIT,
                "Kill mud at the bit — hold final circulating pressure from here.",
                severity=Severity.INFO,
                once=True,
            )

        state.set_condition(
            EventKind.PUMP_STARTED,
            self.pump.running,
            # The commanded speed, not the instantaneous one: the pump ramps,
            # so at the moment it starts turning it is still doing 0 spm and
            # logging that reads as a fault rather than an action.
            message=f"Pump running up to {self.pump.commanded_spm:.0f} spm.",
            severity=Severity.INFO,
            cleared_message="Pump stopped.",
        )

    def _record_sample(self) -> None:
        state = self.state
        state.trace.append(
            TraceSample(
                time_s=state.time_s,
                strokes=state.strokes,
                pumped_bbl=state.pumped_bbl,
                bottomhole_psi=state.bottomhole_pressure_psi,
                casing_psi=state.casing_pressure_psi,
                standpipe_psi=state.standpipe_pressure_psi,
                shoe_psi=state.shoe_pressure_psi,
                influx_bbl=state.influx_volume_bbl,
                influx_top_md=state.influx_top_md,
                choke_percent=self.choke.position,
                pump_spm=self.pump.spm,
                flow_in_bpm=state.flow_in_bpm,
                flow_out_bpm=state.flow_out_bpm,
                pit_gain_bbl=self.pits.gain_bbl,
            )
        )

    def _sample_if_due(self) -> None:
        if self.state.time_s + 1e-9 >= self._next_sample_s + self.trace_interval_s:
            self._next_sample_s = self.state.time_s
            self._record_sample()

    def assess(self, standard: Standard | None = None) -> Assessment:
        """Grade the run so far. See :mod:`wellcontrol.sim.assessment`."""
        from .assessment import assess

        return assess(self, standard)

    @property
    def maasp_psi(self) -> float | None:
        """Maximum allowable annular surface pressure for the mud in the hole.

        Reported in the debrief because it is the number the student was
        watching. The hard limit is the shoe pressure the engine computes
        directly.
        """
        try:
            return self.well.maasp_psi()
        except (TypeError, ValueError):
            return None

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
            state.record(
                EventKind.WELL_DEAD,
                "Well is dead — no influx, no surface pressure.",
                severity=Severity.INFO,
                once=True,
            )

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
