"""The circulating system as a graph of equipment joined by valves.

Lining the rig up is half of well control practice, and it is the half a
calculation cannot teach. Here the system is a directed graph: equipment are
nodes, valves are edges, and every timestep the engine asks two questions.

* Is there a path from the pump into the well? If not, the pump deadheads.
* Is there a path from the well out to the pits? If not, the system is closed
  and anything pumped in has nowhere to go.

**Wrong lineups are not scored as mistakes; they simply do not work.** A student
who leaves the choke line closed gets no returns and has to work out why, which
is exactly what happens on a rig. Nothing here tells them what they did wrong.

## The rule that matters most

With the BOP **open**, returns take the flowline and there is no pressure
control -- the well is open to atmosphere and the choke is irrelevant. With the
BOP **closed**, returns can only leave through the choke or kill line, and the
choke controls the well.

Students reliably try to circulate a kick with the annular still open. The model
lets them, and nothing happens to the casing pressure, which is the lesson.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from enum import Enum


class Node(str, Enum):
    """A piece of equipment fluid can be in or pass through."""

    PUMP = "mud pump 1"
    PUMP_2 = "mud pump 2"
    STANDPIPE = "standpipe"
    STRING = "drill string"
    BIT = "bit"
    ANNULUS = "annulus"
    BOP = "BOP stack"
    FLOWLINE = "flowline"
    CHOKE_LINE = "choke line"
    KILL_LINE = "kill line"
    CHOKE_MANIFOLD = "choke manifold inlet header"
    CHOKE_1_IN = "choke 1 run (upstream)"
    CHOKE_1_OUT = "choke 1 run (downstream)"
    CHOKE_2_IN = "choke 2 run (upstream)"
    CHOKE_2_OUT = "choke 2 run (downstream)"
    CHOKE_BUFFER = "choke manifold downstream header"
    SEPARATOR = "mud gas separator"
    FLARE = "flare / overboard"
    PITS = "active pits"
    TRIP_TANK = "trip tank"


class ValveState(str, Enum):
    OPEN = "open"
    CLOSED = "closed"


@dataclass
class Valve:
    """A valve, or a BOP element, joining two nodes.

    Attributes:
        name: Key used to operate it.
        label: What it is called on the rig floor.
        frm: Upstream node.
        to: Downstream node.
        state: Open or closed.
        is_bop: True for BOP elements, which seal the annulus when *closed* --
            the opposite sense to every other valve here.
        throttling: True for an adjustable choke, whose opening is a position
            rather than a state.
        bidirectional: True where the line genuinely runs both ways. A gate
            valve does not care which way the flow goes; the kill line takes
            returns during a kill and takes mud *into* the annulus when
            lubricating, and it is the same valve doing both.
    """

    name: str
    label: str
    frm: Node
    to: Node
    state: ValveState = ValveState.CLOSED
    is_bop: bool = False
    throttling: bool = False
    bidirectional: bool = False

    @property
    def is_open(self) -> bool:
        return self.state is ValveState.OPEN


def default_valves() -> list[Valve]:
    """Authentic drilling rig circulating, standpipe, and API 16C choke manifold lineup."""
    return [
        # --- Standpipe Manifold (matching authentic 9-valve rig arrangement) ---
        Valve("pump_discharge", "MP1 discharge valve", Node.PUMP, Node.STANDPIPE,
              state=ValveState.CLOSED),
        Valve("mp2_discharge", "MP2 discharge valve", Node.PUMP_2, Node.STANDPIPE,
              state=ValveState.CLOSED),
        Valve("standpipe_bleed_valve", "Standpipe bleed / fill valve", Node.STANDPIPE, Node.PITS,
              state=ValveState.CLOSED),
        Valve("standpipe_valve", "Main standpipe valve", Node.STANDPIPE, Node.STRING,
              bidirectional=True, state=ValveState.CLOSED),
        Valve("sp_cross_1", "Standpipe cross-over 1 (Tap 1 to Choke)", Node.STANDPIPE, Node.STANDPIPE,
              bidirectional=True, state=ValveState.OPEN),
        Valve("standpipe_to_manifold", "Standpipe to choke line takeoff", Node.STANDPIPE, Node.CHOKE_MANIFOLD,
              bidirectional=True, state=ValveState.CLOSED),
        Valve("sp_cross_2", "Standpipe cross-over 2 (Choke to Tap 2)", Node.STANDPIPE, Node.STANDPIPE,
              bidirectional=True, state=ValveState.OPEN),
        Valve("pump_to_kill_line", "Pump to kill line takeoff", Node.PUMP, Node.KILL_LINE,
              bidirectional=True, state=ValveState.CLOSED),
        Valve("sp_cross_3", "Standpipe cross-over 3 (Tap 2 to MP2)", Node.STANDPIPE, Node.STANDPIPE,
              bidirectional=True, state=ValveState.OPEN),

        # --- Drill String & Downhole ---
        Valve("kelly_cock", "Kelly cock", Node.STRING, Node.BIT,
              state=ValveState.OPEN),
        Valve("bit_nozzles", "Bit nozzles", Node.BIT, Node.ANNULUS,
              state=ValveState.OPEN, bidirectional=True),
        Valve("float_valve", "String float valve", Node.BIT, Node.STRING),

        # --- BOP Elements (Annular & Rams) ---
        Valve("annular", "Annular preventer", Node.ANNULUS, Node.BOP,
              state=ValveState.OPEN, is_bop=True),
        Valve("upper_rams", "Upper pipe rams", Node.ANNULUS, Node.BOP,
              state=ValveState.OPEN, is_bop=True),
        Valve("blind_rams", "Blind / shear rams", Node.ANNULUS, Node.BOP,
              state=ValveState.OPEN, is_bop=True),
        Valve("lower_rams", "Lower pipe rams", Node.ANNULUS, Node.BOP,
              state=ValveState.OPEN, is_bop=True),

        # --- Surface Flowline (BOP Open) ---
        Valve("flowline", "Flowline to shakers", Node.BOP, Node.FLOWLINE,
              state=ValveState.OPEN),
        Valve("shakers_to_pits", "Shakers to pits", Node.FLOWLINE, Node.PITS,
              state=ValveState.OPEN),

        # --- BOP Stack Wing Outlets ---
        Valve("choke_line_valve", "Choke line valve (HCR)", Node.ANNULUS, Node.CHOKE_LINE,
              bidirectional=True, state=ValveState.CLOSED),
        Valve("kill_line_valve", "Kill line valve (HCR)", Node.ANNULUS, Node.KILL_LINE,
              bidirectional=True, state=ValveState.CLOSED),

        # --- Choke & Kill Manifold (API Spec 16C Standard) ---
        Valve("choke_line_to_manifold", "Choke line inlet master", Node.CHOKE_LINE, Node.CHOKE_MANIFOLD,
              bidirectional=True, state=ValveState.OPEN),
        Valve("kill_line_to_manifold", "Kill line inlet master", Node.KILL_LINE, Node.CHOKE_MANIFOLD,
              bidirectional=True, state=ValveState.CLOSED),
        Valve("manifold_crossover", "Kill/Choke manifold cross-over", Node.KILL_LINE, Node.CHOKE_MANIFOLD,
              bidirectional=True, state=ValveState.CLOSED),
        Valve("kill_bleed_valve", "Kill line bleed-off valve", Node.KILL_LINE, Node.PITS,
              state=ValveState.CLOSED),

        # Remote / Hydraulic Choke Leg (Double Isolation)
        Valve("choke_1_upstream", "Auto choke upstream gate valve", Node.CHOKE_MANIFOLD, Node.CHOKE_1_IN,
              state=ValveState.OPEN),
        Valve("choke_1", "Adjustable hydraulic choke 1", Node.CHOKE_1_IN, Node.CHOKE_1_OUT,
              throttling=True, state=ValveState.CLOSED),
        Valve("choke_1_downstream", "Auto choke downstream gate valve", Node.CHOKE_1_OUT, Node.CHOKE_BUFFER,
              state=ValveState.OPEN),

        # Manual Choke Leg (Double Isolation)
        Valve("choke_2_upstream", "Manual choke upstream gate valve", Node.CHOKE_MANIFOLD, Node.CHOKE_2_IN,
              state=ValveState.OPEN),
        Valve("choke_2", "Adjustable manual choke 2", Node.CHOKE_2_IN, Node.CHOKE_2_OUT,
              throttling=True, state=ValveState.CLOSED),
        Valve("choke_2_downstream", "Manual choke downstream gate valve", Node.CHOKE_2_OUT, Node.CHOKE_BUFFER,
              state=ValveState.OPEN),

        # Emergency Straight Bypass (Panic Line)
        Valve("choke_bypass", "Choke manifold emergency bypass", Node.CHOKE_MANIFOLD, Node.CHOKE_BUFFER,
              state=ValveState.CLOSED),

        # Downstream Buffer Header Outlets
        Valve("to_mgs_valve", "Manifold to Mud Gas Separator", Node.CHOKE_BUFFER, Node.SEPARATOR,
              state=ValveState.OPEN),
        Valve("to_shakers_valve", "Manifold direct to shakers", Node.CHOKE_BUFFER, Node.FLOWLINE,
              state=ValveState.CLOSED),
        Valve("to_flare_valve", "Manifold to emergency flare line", Node.CHOKE_BUFFER, Node.FLARE,
              state=ValveState.CLOSED),
        Valve("flare_to_atmosphere", "Flare line overboard discharge", Node.FLARE, Node.PITS,
              state=ValveState.OPEN),

        # Mud Gas Separator U-Tube Drain
        Valve("separator_to_pits", "Separator to pits", Node.SEPARATOR, Node.PITS,
              state=ValveState.OPEN),

        # Auxiliary Lines
        Valve("trip_tank_valve", "Trip tank to annulus", Node.TRIP_TANK, Node.ANNULUS,
              state=ValveState.CLOSED),
    ]


@dataclass
class ReturnRoute:
    """How returns are leaving the well, if they are."""

    open_to_pits: bool
    through_choke: bool
    route: tuple[Node, ...] = ()

    @property
    def description(self) -> str:
        if not self.open_to_pits:
            return "closed in — no return path"
        if self.through_choke:
            return "returns through the choke manifold"
        return "returns up the flowline — no pressure control"


@dataclass
class FlowPath:
    """The lineup, and what it permits."""

    valves: list[Valve] = field(default_factory=default_valves)

    def __post_init__(self) -> None:
        self._by_name = {v.name: v for v in self.valves}

    # -- operating -----------------------------------------------------------

    def valve(self, name: str) -> Valve:
        if name not in self._by_name:
            raise KeyError(
                f"No valve called '{name}'. Available: "
                f"{', '.join(sorted(self._by_name))}"
            )
        return self._by_name[name]

    def set_valve(self, name: str, state: ValveState | str) -> None:
        self.valve(name).state = ValveState(state)

    def open(self, *names: str) -> None:
        for name in names:
            self.set_valve(name, ValveState.OPEN)

    def close(self, *names: str) -> None:
        for name in names:
            self.set_valve(name, ValveState.CLOSED)

    # -- state ---------------------------------------------------------------

    @property
    def bop_elements(self) -> list[Valve]:
        return [v for v in self.valves if v.is_bop]

    @property
    def bop_is_closed(self) -> bool:
        """True when any BOP element is closed, sealing the annulus."""
        return any(not v.is_open for v in self.bop_elements)

    @property
    def closed_bop_elements(self) -> list[str]:
        return [v.label for v in self.bop_elements if not v.is_open]

    # -- path resolution -----------------------------------------------------

    def _edges(self) -> dict[Node, list[Node]]:
        """Adjacency for the currently open valves.

        BOP elements do not appear as ordinary edges, because their sense is
        inverted -- closing one *removes* a route rather than adding one. The
        annulus reaches the BOP outlet, and so the flowline, only while every
        element is open. The choke and kill lines take off from the stack below
        the elements, so they stay available with the stack shut, which is the
        whole point of having them.
        """
        edges: dict[Node, list[Node]] = {}
        for valve in self.valves:
            if valve.is_bop or not valve.is_open:
                continue
            edges.setdefault(valve.frm, []).append(valve.to)
            if valve.bidirectional:
                edges.setdefault(valve.to, []).append(valve.frm)

        if not self.bop_is_closed:
            edges.setdefault(Node.ANNULUS, []).append(Node.BOP)
        return edges

    @staticmethod
    def _reachable(
        edges: dict[Node, list[Node]], start: Node, goal: Node
    ) -> tuple[Node, ...] | None:
        queue: deque[tuple[Node, ...]] = deque([(start,)])
        seen = {start}
        while queue:
            path = queue.popleft()
            if path[-1] is goal:
                return path
            for nxt in edges.get(path[-1], ()):
                if nxt not in seen:
                    seen.add(nxt)
                    queue.append(path + (nxt,))
        return None

    def injection_path(self) -> tuple[Node, ...] | None:
        """Route from the pump into the annulus, or None if the pump is blocked.

        None means the pump is deadheaded: it is running against a closed
        valve, and pressure will build with nowhere to go.
        """
        return self._reachable(
            self._edges(), Node.PUMP, Node.ANNULUS
        )

    @property
    def pump_is_deadheaded(self) -> bool:
        return self.injection_path() is None

    @property
    def injecting_into_the_annulus(self) -> bool:
        """True when the pump reaches the annulus without going down the pipe.

        The difference matters to the engine rather than to the graph. Mud
        pumped down the string comes round the bit and pushes the annulus
        contents *up* from the bottom. Mud pumped into the kill line arrives at
        the *top* and falls through whatever gas is up there to sit beneath it.
        Same pump, same barrels, opposite ends of the well.
        """
        path = self.injection_path()
        if path is None:
            return False
        return Node.STRING not in path

    def return_route(self) -> ReturnRoute:
        """How returns leave the well, given the lineup and the BOP.

        With the stack open, returns take the flowline and there is no pressure
        control however the choke is set. With the stack closed, they can only
        go out the choke or kill line.
        """
        edges = self._edges()

        if not self.bop_is_closed:
            path = self._reachable(edges, Node.ANNULUS, Node.PITS)
            if path is not None and Node.FLOWLINE in path:
                return ReturnRoute(True, False, path)

        # Stack closed: the flowline is sealed off, so only routes through the
        # choke or kill line count -- or, reverse circulating, back through the
        # bit and up the inside of the string.
        #
        # Whatever the pump is coming in through is an inlet, not an outlet.
        # Without that exclusion a line that runs both ways gets picked as the
        # return route it is currently feeding, and the reported path doubles
        # back on itself.
        inlet = self.injection_path() or ()
        for entry in (Node.CHOKE_LINE, Node.KILL_LINE, Node.BIT):
            if entry not in edges.get(Node.ANNULUS, ()) or entry in inlet:
                continue
            path = self._reachable(edges, entry, Node.PITS)
            if path is not None:
                return ReturnRoute(True, True, (Node.ANNULUS,) + path)

        return ReturnRoute(False, False, ())

    @property
    def is_reverse_circulating(self) -> bool:
        """Pumping down the annulus and taking returns up the drill pipe.

        The influx then travels up the *inside of the string*, which is the
        whole attraction: it never passes the casing shoe, and the string holds
        a fraction of the annulus volume so it is out in far fewer strokes.

        Both halves have to be true. Pumping into the annulus with returns
        still coming up the annulus is lubricating, not reverse circulating.
        """
        if not self.injecting_into_the_annulus:
            return False
        route = self.return_route()
        return route.open_to_pits and Node.STRING in route.route

    @property
    def is_closed_in(self) -> bool:
        """True when nothing can leave the well."""
        return not self.return_route().open_to_pits

    def active_chokes(self) -> list[Valve]:
        """Throttling valves on a live return route.

        More than one open choke is a lineup error rather than twice the
        capacity, and the engine treats the total area accordingly.
        """
        route = self.return_route()
        if not route.through_choke:
            return []
        return [
            v for v in self.valves
            if v.throttling and v.is_open
            and self._reachable(
                self._edges(), v.to, Node.PITS
            ) is not None
        ]

    def bypass_is_open(self) -> bool:
        """The bypass defeats the choke: returns go round it, uncontrolled."""
        valve = self.valve("choke_bypass")
        if not valve.is_open:
            return False
        edges = self._edges()
        return self._reachable(edges, valve.to, Node.PITS) is not None

    # -- reporting -----------------------------------------------------------

    def summary(self) -> dict[str, object]:
        route = self.return_route()
        return {
            "BOP": (
                f"closed: {', '.join(self.closed_bop_elements)}"
                if self.bop_is_closed else "open"
            ),
            "Pump path": (
                "blocked — deadheaded" if self.pump_is_deadheaded
                else " → ".join(n.value for n in self.injection_path())
            ),
            "Returns": route.description,
            "Open valves": ", ".join(
                v.label for v in self.valves if v.is_open and not v.is_bop
            ) or "none",
        }
