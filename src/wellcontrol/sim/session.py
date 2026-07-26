"""A student's session: the engine, a clock, and the controls they can reach.

Stage 3 of the simulator. The engine advances by simulated seconds and knows
nothing about wall time; something has to decide *when* to step it. That is this
module, and it is deliberately kept free of any web framework so the time model
can be tested without the HTTP stack.

## Time advances on demand, not on a background thread

Each call to :meth:`Session.advance` looks at how much wall time has passed
since the last one, multiplies by the speed setting, and steps the engine that
far. No threads, no timers, nothing running when nobody is watching.

Two consequences worth stating:

* **The well only evolves while somebody is looking at it.** For a self-study
  trainer that is right -- a student who walks away has not lost the kick -- and
  it makes every test deterministic.
* **Catch-up is clamped.** Without the clamp, a student who leaves the tab for
  ten minutes at 60x comes back to ten hours of simulated well, all integrated
  in one request. :attr:`MAX_CATCHUP_S` caps how much simulated time a single
  advance can cover.

## Why the clock is injected

``clock`` defaults to :func:`time.monotonic` but tests pass their own, so the
whole time model is exercised without sleeping. Monotonic rather than wall
clock: the simulation must not jump when the machine's clock is adjusted.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Callable

from .. import examples
from ..wellconfig import BOPLocation, Trajectory, WellConfiguration
from .assessment import Assessment, EventKind, Severity, Standard
from .engine import Simulator, StartState
from .flowpath import ValveState

#: Simulated seconds a single advance may cover, however long the gap was.
MAX_CATCHUP_S: float = 30.0

#: Integration step. Small enough for the stiff pressure equation; see engine.
STEP_S: float = 0.05

#: Speeds the student can select. 0 is pause.
SPEEDS: tuple[float, ...] = (0.0, 1.0, 10.0, 60.0)

#: Shown in the API docs. A real kill runs three to five hours, so working one
#: entirely at 1x is not a training exercise anybody completes.
SESSION_SPEEDS_DOC = (
    "Simulated seconds per real second. 0 pauses. A real kill runs three to "
    "five hours, so 10x and 60x exist to skip the long circulating stretches; "
    "drop back to 1x when the gas nears surface and the choke gets violent."
)


@dataclass
class Session:
    """One student, one well, one attempt.

    Args:
        simulator: The engine. Defaults to the reference surface vertical well.
        speed: Simulated seconds per wall-clock second. 0 pauses.
        clock: Source of wall-clock seconds. Injected for testing.
    """

    simulator: Simulator
    speed: float = 0.0
    clock: Callable[[], float] = time.monotonic
    session_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    #: Drop to real time once, when the well first flows. See _should_slow_down.
    auto_slow: bool = True
    #: Wall-clock reading at the last advance.
    _last_tick: float | None = field(default=None, repr=False)
    _auto_slowed: bool = field(default=False, repr=False)

    # -- construction --------------------------------------------------------

    @classmethod
    def for_configuration(
        cls,
        bop: str = "surface",
        trajectory: str = "vertical",
        start: str = "shut_in",
        **kwargs,
    ) -> "Session":
        """Build a session on one of the library's example wells.

        Args:
            bop: ``surface`` or ``subsea``.
            trajectory: ``vertical``, ``deviated`` or ``horizontal``.
            start: ``shut_in`` hands over a kick that is already in the hole,
                sized and identified, with the well closed on it and the choke
                line lined up -- an exercise in working a choke. ``drilling``
                starts on a well that is behaving, lined up for normal drilling
                with returns up the flowline; the kick arrives later and the
                student has to notice it and shut in themselves.
        """
        config = WellConfiguration(BOPLocation(bop), Trajectory(trajectory))
        state = StartState(start)
        session = cls(
            simulator=Simulator(well=examples.well_state(config), start=state),
            **kwargs,
        )
        path = session.simulator.flow_path
        if state is StartState.SHUT_IN:
            path.close("annular")
            path.open("choke_line_valve", "choke_line_to_manifold", "choke_1")
            path.open("pump_discharge", "standpipe_valve")
        else:
            # Lined up to drill: pump through the string, returns up the
            # flowline over the shakers. Nothing on the choke side is open,
            # which is the point -- shutting in is the student's job.
            path.open("pump_discharge", "standpipe_valve")
        return session

    # -- what the student is allowed to see ----------------------------------

    @property
    def downhole_visible(self) -> bool:
        """Whether the downhole truth is on display.

        **Hidden while a drilling kick is developing.** A rig has no bottomhole
        gauge and no pore pressure readout; showing them would turn kick
        detection -- which is the skill being taught -- into reading a number.
        Until the well is shut in the student gets what a driller gets: the pit
        level, the flow line, and the standpipe.

        Once they have shut in, it comes back. At that point it is a teaching
        aid rather than a giveaway: the kick has been taken, and seeing what
        bottomhole pressure does while they work the choke is the whole reason
        this is a simulator and not a rig.
        """
        if self.simulator.start is StartState.SHUT_IN:
            return True
        return self.simulator.state.event_log.has(
            EventKind.WELL_SHUT_IN_BY_STUDENT
        )

    # -- time ----------------------------------------------------------------

    def set_speed(self, speed: float) -> None:
        """Change the speed multiplier, banking the time already run.

        Advancing first matters: without it, time that elapsed at the old speed
        would be integrated at the new one.
        """
        self.advance()
        self.speed = max(0.0, float(speed))

    @property
    def paused(self) -> bool:
        return self.speed <= 0.0

    def advance(self) -> float:
        """Step the engine up to the present. Returns simulated seconds run."""
        now = self.clock()
        if self._last_tick is None:
            self._last_tick = now
            return 0.0

        elapsed_wall = max(0.0, now - self._last_tick)
        self._last_tick = now
        if self.paused:
            return 0.0

        simulated = min(elapsed_wall * self.speed, MAX_CATCHUP_S)
        steps = int(simulated / STEP_S)
        for _ in range(steps):
            self.simulator.step(STEP_S)
            if self._should_slow_down():
                # Stop mid-batch. Running the rest of this batch at the old
                # speed would spend the seconds the slow-down exists to give
                # back.
                break
        return steps * STEP_S

    def _should_slow_down(self) -> bool:
        """Drop to real time the moment the well starts flowing.

        **An undetected kick accelerates.** Gas replacing mud lightens the
        annulus, which deepens the underbalance, which brings in more gas. At
        60x the whole thing is over between two glances at the screen, and the
        student learns nothing except that they lost.

        So the clock drops to 1x by itself at the moment the flow line tells
        them something is wrong. That is not making the exercise easier -- the
        well does exactly what it did before -- it is giving them the seconds a
        driller standing at the panel would actually have.
        """
        if not self.auto_slow or self.speed <= 1.0 or self._auto_slowed:
            return False
        if not self.simulator.state.event_log.is_active(EventKind.FLOW_CHECK):
            return False
        self._auto_slowed = True
        self.speed = 1.0
        self.simulator.state.record(
            EventKind.FLOW_CHECK,
            "Real time from here — the well is flowing.",
            severity=Severity.INFO,
        )
        return True

    # -- controls ------------------------------------------------------------

    def set_choke(self, percent: float) -> None:
        self.advance()
        self.simulator.choke.command(float(percent))

    def set_pump(self, spm: float) -> None:
        self.advance()
        if spm <= 0:
            self.simulator.pump.stop()
        else:
            self.simulator.pump.command(float(spm))

    def set_valve(self, name: str, state: str) -> None:
        """Open or close a valve. Raises KeyError naming the valve if unknown."""
        self.advance()
        self.simulator.flow_path.set_valve(name, ValveState(state))

    # -- readouts ------------------------------------------------------------

    def gauges(self) -> dict:
        """What the choke panel displays.

        The instrument scan a student has to build is drill pipe pressure,
        casing pressure, stroke counter and choke position together, so those
        four come first and everything else is secondary.
        """
        state = self.simulator.state
        route = self.simulator.flow_path.return_route()
        visible = self.downhole_visible

        def downhole(value):
            """None while the student is meant to be detecting, not reading."""
            return None if not visible else value

        return {
            # The rig's own instruments. Always readable, because they are the
            # ones a driller actually has.
            "drill_pipe_psi": round(state.standpipe_pressure_psi),
            "casing_psi": round(state.casing_pressure_psi),
            "strokes": round(state.strokes),
            "choke_percent": round(self.simulator.choke.position, 1),
            "choke_commanded": round(self.simulator.choke.commanded_position, 1),
            "pump_spm": round(self.simulator.pump.spm, 1),
            "pump_commanded": round(self.simulator.pump.commanded_spm, 1),
            "pit_gain_bbl": round(self.simulator.pits.gain_bbl, 1),
            # The instrument the Volumetric method is worked to.
            "bled_bbl": round(state.bled_bbl, 2),
            "flow_in_bpm": round(state.flow_in_bpm, 2),
            "flow_out_bpm": round(state.flow_out_bpm, 2),
            "time_s": round(state.time_s, 1),
            "returns": route.description,
            "well_is_dead": state.well_is_dead,
            "speed": self.speed,

            # Downhole truth. No rig has these; see downhole_visible.
            "downhole_visible": visible,
            "bottomhole_psi": downhole(round(state.bottomhole_pressure_psi)),
            "formation_psi": downhole(
                round(self.simulator.formation_pressure_psi)
            ),
            "overbalance_psi": downhole(round(
                state.bottomhole_pressure_psi
                - self.simulator.formation_pressure_psi
            )),
            "shoe_psi": downhole(round(state.shoe_pressure_psi)),
            "frac_psi": downhole(
                round(self.simulator.frac_pressure_psi)
                if self.simulator.frac_pressure_psi is not None else None
            ),
            "maasp_psi": downhole(
                round(self.simulator.maasp_psi)
                if self.simulator.maasp_psi is not None else None
            ),
            "influx_bbl": downhole(round(state.influx_volume_bbl, 1)),
            "influx_top_md": downhole(round(state.influx_top_md)),
            "gas_at_surface": downhole(state.gas_at_surface),
        }

    def lineup(self) -> list[dict]:
        """Every valve, its label and its state, for the lineup panel."""
        return [
            {
                "name": valve.name,
                "label": valve.label,
                "state": valve.state.value,
                "is_bop": valve.is_bop,
                "throttling": valve.throttling,
                "from": valve.frm.value,
                "to": valve.to.value,
            }
            for valve in self.simulator.flow_path.valves
        ]

    def events_since(self, index: int = 0) -> dict:
        """Event log entries from ``index`` on, so the client can append.

        Returning the next index rather than a timestamp keeps the client
        simple and makes replays idempotent.
        """
        events = self.simulator.state.event_log.events
        start = max(0, min(index, len(events)))
        return {
            "next_index": len(events),
            "events": [
                {
                    "time_s": round(event.time_s, 1),
                    "clock": event.clock,
                    "kind": event.kind.value,
                    "severity": event.severity.value,
                    "message": event.message,
                }
                for event in events[start:]
            ],
        }

    def trace(self, limit: int = 240) -> list[dict]:
        """Recent trace samples for the panel's strip chart.

        Carries the surface pressures always and the downhole ones only when
        they are on display, so a chart cannot leak what the gauges withhold.
        """
        visible = self.downhole_visible
        samples = self.simulator.state.trace[-limit:]
        rows = []
        for sample in samples:
            row = {
                "time_s": round(sample.time_s, 1),
                "casing_psi": round(sample.casing_psi),
                "drill_pipe_psi": round(sample.standpipe_psi),
                "pit_gain_bbl": round(sample.pit_gain_bbl, 1),
                "flow_out_bpm": round(sample.flow_out_bpm, 2),
                "flow_in_bpm": round(sample.flow_in_bpm, 2),
            }
            if visible:
                row["bottomhole_psi"] = round(sample.bottomhole_psi)
                row["shoe_psi"] = round(sample.shoe_psi)
                row["influx_bbl"] = round(sample.influx_bbl, 1)
            rows.append(row)
        return rows

    def snapshot(self, since_event: int = 0, trace_limit: int = 240) -> dict:
        """Everything the panel needs in one poll.

        One round trip rather than four: the gauges, whatever events are new,
        and the strip chart all describe the same instant, and fetching them
        separately would let them disagree.
        """
        self.advance()
        return {
            "session_id": self.session_id,
            "gauges": self.gauges(),
            "events": self.events_since(since_event),
            "trace": self.trace(trace_limit),
        }

    def assess(self, require_kill: bool = False) -> Assessment:
        self.advance()
        return self.simulator.assess(Standard(require_kill=require_kill))

    def debrief(self, require_kill: bool = False) -> dict:
        assessment = self.assess(require_kill)
        return {
            "grade": assessment.grade.value,
            "passed": assessment.passed,
            "killed": assessment.killed,
            "duration_min": round(assessment.duration_min, 1),
            "summary": assessment.summary,
            "metrics": [
                {
                    "name": metric.name,
                    "value": round(metric.value, 1),
                    "limit": None if metric.limit is None else round(metric.limit, 1),
                    "unit": metric.unit,
                    "passed": metric.passed,
                    "critical": metric.critical,
                    "detail": metric.detail,
                }
                for metric in assessment.metrics
            ],
            "events": [
                {
                    "clock": event.clock,
                    "severity": event.severity.value,
                    "message": event.message,
                }
                for event in assessment.events
                if event.severity.rank >= Severity.CAUTION.rank
            ],
            "report": assessment.format_report(),
        }


class SessionStore:
    """In-memory sessions, keyed by id.

    Deliberately not a database. This is a self-study trainer running on one
    machine; persistence is a stage 5 problem alongside the scenario library.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}

    def create(self, **kwargs) -> Session:
        session = Session.for_configuration(**kwargs)
        self._sessions[session.session_id] = session
        return session

    def add(self, session: Session) -> Session:
        self._sessions[session.session_id] = session
        return session

    def get(self, session_id: str) -> Session:
        if session_id not in self._sessions:
            raise KeyError(f"No session '{session_id}'")
        return self._sessions[session_id]

    def drop(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    def __len__(self) -> int:
        return len(self._sessions)

    @property
    def ids(self) -> list[str]:
        return list(self._sessions)
