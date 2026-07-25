"""Well control simulator -- a forward model of a rig under a student's hands.

The rest of this package answers "what should the driller hold?". This
subpackage answers the opposite question: **the student set the choke to 35%
and the pump to 30 spm -- what does the well do?** It has to represent failure
as faithfully as success, because failing safely is the point of a trainer.

Usage::

    from wellcontrol import examples
    from wellcontrol.sim import Simulator, ValveState

    sim = Simulator(well=examples.well_state(config))

    sim.flow_path.close("annular")            # shut in
    sim.flow_path.open("choke_line_valve", "choke_line_to_manifold", "choke_1")
    sim.choke.command(30.0)                   # 30% open
    sim.pump.command(30.0)                    # 30 spm

    sim.run(seconds=60)
    print(sim.readout())

See ``docs/simulator-design.md`` for the design and what it deliberately does
not attempt.
"""

from __future__ import annotations

from .engine import MUD_COMPRESSIBILITY, SimState, Simulator
from .equipment import AdjustableChoke, MudPump, PitSystem, TripTank
from .flowpath import FlowPath, Node, ReturnRoute, Valve, ValveState, default_valves

__all__ = [
    "AdjustableChoke",
    "FlowPath",
    "MUD_COMPRESSIBILITY",
    "MudPump",
    "Node",
    "PitSystem",
    "ReturnRoute",
    "SimState",
    "Simulator",
    "TripTank",
    "Valve",
    "ValveState",
    "default_valves",
]
