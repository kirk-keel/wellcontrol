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
from .assessment import Assessment, Severity, Standard
from .engine import Simulator
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
    #: Wall-clock reading at the last advance.
    _last_tick: float | None = field(default=None, repr=False)

    # -- construction --------------------------------------------------------

    @classmethod
    def for_configuration(
        cls,
        bop: str = "surface",
        trajectory: str = "vertical",
        shut_in: bool = True,
        **kwargs,
    ) -> "Session":
        """Build a session on one of the library's example wells.

        Args:
            bop: ``surface`` or ``subsea``.
            trajectory: ``vertical``, ``deviated`` or ``horizontal``.
            shut_in: Start with the well shut in on the annular and the choke
                line lined up, which is where a kill exercise begins. False
                leaves the rig lined up for normal drilling, so the student has
                to shut in themselves.
        """
        config = WellConfiguration(BOPLocation(bop), Trajectory(trajectory))
        session = cls(simulator=Simulator(well=examples.well_state(config)),
                      **kwargs)
        if shut_in:
            session.simulator.flow_path.close("annular")
            session.simulator.flow_path.open(
                "choke_line_valve", "choke_line_to_manifold", "choke_1"
            )
            session.simulator.flow_path.open("pump_discharge", "standpipe_valve")
        return session

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
        return steps * STEP_S

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
        return {
            "drill_pipe_psi": round(state.standpipe_pressure_psi),
            "casing_psi": round(state.casing_pressure_psi),
            "strokes": round(state.strokes),
            "choke_percent": round(self.simulator.choke.position, 1),
            "choke_commanded": round(self.simulator.choke.commanded_position, 1),
            "pump_spm": round(self.simulator.pump.spm, 1),
            "pump_commanded": round(self.simulator.pump.commanded_spm, 1),
            "bottomhole_psi": round(state.bottomhole_pressure_psi),
            "formation_psi": round(self.simulator.formation_pressure_psi),
            "overbalance_psi": round(
                state.bottomhole_pressure_psi - self.simulator.formation_pressure_psi
            ),
            "shoe_psi": round(state.shoe_pressure_psi),
            "frac_psi": (
                round(self.simulator.frac_pressure_psi)
                if self.simulator.frac_pressure_psi is not None else None
            ),
            "maasp_psi": (
                round(self.simulator.maasp_psi)
                if self.simulator.maasp_psi is not None else None
            ),
            "influx_bbl": round(state.influx_volume_bbl, 1),
            "influx_top_md": round(state.influx_top_md),
            "pit_gain_bbl": round(self.simulator.pits.gain_bbl, 1),
            "flow_in_bpm": round(state.flow_in_bpm, 2),
            "flow_out_bpm": round(state.flow_out_bpm, 2),
            "time_s": round(state.time_s, 1),
            "returns": route.description,
            "gas_at_surface": state.gas_at_surface,
            "well_is_dead": state.well_is_dead,
            "speed": self.speed,
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
        """Recent trace samples for the panel's strip chart."""
        samples = self.simulator.state.trace[-limit:]
        return [
            {
                "time_s": round(sample.time_s, 1),
                "casing_psi": round(sample.casing_psi),
                "drill_pipe_psi": round(sample.standpipe_psi),
                "bottomhole_psi": round(sample.bottomhole_psi),
                "shoe_psi": round(sample.shoe_psi),
                "influx_bbl": round(sample.influx_bbl, 1),
            }
            for sample in samples
        ]

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
