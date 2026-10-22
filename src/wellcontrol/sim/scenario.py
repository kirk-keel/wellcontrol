"""Scenarios, and the faults an instructor can inject into them.

Stage 5. Until now a session was "the reference vertical well, shut in or
drilling". A scenario names an exercise: which well, where it starts, what the
student is expected to achieve, and what -- if anything -- is going to go wrong
part way through.

**Scenarios are data.** Everything here is a plain dataclass built from
primitives, and :meth:`Scenario.from_dict` takes the same shape as JSON, so an
instructor can add an exercise without touching Python. The built-in library in
:data:`SCENARIOS` is the same structure, written out longhand.

## Faults are triggers, not scripts

A fault does one thing to one piece of equipment at one moment: the pump fails,
the choke plugs, the accumulator leaks. What follows is whatever the well does
about it, through the same volume balance as everything else. Nothing here
knows what a kick is or how a kill should go, and a fault cannot make the well
behave in a way it could not have behaved on its own.

That distinction is worth keeping. A scripted "and now the pressure spikes"
teaches a student to recognise a scripted spike. A choke that plugs while they
are holding 400 psi on it teaches them what a plugged choke feels like.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from .assessment import EventKind, Severity, Standard
from .engine import StartState


class FaultKind(str, Enum):
    """What can be made to go wrong.

    Each acts on one piece of equipment. The consequences are the model's.
    """

    PUMP_FAILURE = "pump_failure"
    CHOKE_PLUGGED = "choke_plugged"
    CHOKE_WASHOUT = "choke_washout"
    ACCUMULATOR_LEAK = "accumulator_leak"
    WEAK_SHOE = "weak_shoe"
    MUD_WEIGHT_DROP = "mud_weight_drop"

    @property
    def label(self) -> str:
        return self.value.replace("_", " ").capitalize()


@dataclass(frozen=True)
class Fault:
    """One thing going wrong, at one moment.

    Args:
        kind: What breaks.
        at_seconds: Simulated time to fire at.
        at_strokes: Stroke count to fire at. Used instead of, or as well as,
            the time -- whichever comes first.
        after_event: Fire once this has appeared in the log. Lets a fault be
            hung on something the *student* caused, such as gas reaching
            surface, rather than on the clock.
        message: What the log says. Written as the rig would report it, not as
            an explanation -- the student has to work out what it means.
        severity: How it is logged.
    """

    kind: FaultKind
    at_seconds: float | None = None
    at_strokes: float | None = None
    after_event: EventKind | None = None
    message: str = ""
    severity: Severity = Severity.CRITICAL

    def is_due(self, time_s: float, strokes: float, log) -> bool:
        """Whether this should fire now. Any one trigger is enough."""
        if self.at_seconds is not None and time_s >= self.at_seconds:
            return True
        if self.at_strokes is not None and strokes >= self.at_strokes:
            return True
        if self.after_event is not None and log.has(self.after_event):
            return True
        return False

    @classmethod
    def from_dict(cls, data: dict) -> "Fault":
        return cls(
            kind=FaultKind(data["kind"]),
            at_seconds=data.get("at_seconds"),
            at_strokes=data.get("at_strokes"),
            after_event=(
                EventKind(data["after_event"]) if data.get("after_event") else None
            ),
            message=data.get("message", ""),
            severity=Severity(data.get("severity", "critical")),
        )


@dataclass(frozen=True)
class Scenario:
    """One exercise.

    Args:
        key: Stable identifier, used in URLs.
        name: What the student sees in the picker.
        objective: What they are being asked to do, in a sentence.
        briefing: The rest of what they are told before starting. Deliberately
            does not include anything they should be reading off the gauges.
        bop: ``surface`` or ``subsea``.
        trajectory: ``vertical``, ``deviated`` or ``horizontal``.
        start: Where it begins -- see :class:`~wellcontrol.sim.engine.StartState`.
        bit_off_bottom_ft: Pull the bit up, for stripping exercises.
        open_valves: Valves to open beyond the start state's own lineup.
        closed_valves: Valves to shut.
        faults: What is going to go wrong, if anything.
        require_kill: Whether the exercise is only complete with a dead well.
        migration_rate_ft_per_hr: Override the well's own figure.
    """

    key: str
    name: str
    objective: str
    briefing: str = ""
    bop: str = "surface"
    trajectory: str = "vertical"
    start: StartState = StartState.SHUT_IN
    bit_off_bottom_ft: float = 0.0
    open_valves: tuple[str, ...] = ()
    closed_valves: tuple[str, ...] = ()
    faults: tuple[Fault, ...] = ()
    require_kill: bool = False
    migration_rate_ft_per_hr: float | None = None
    mud_weight_ppg: float | None = None
    sidpp_psi: float | None = None
    sicp_psi: float | None = None
    pit_gain_bbl: float | None = None
    frac_gradient_ppg: float | None = None
    shoe_md_ft: float | None = None
    kick_after_s: float | None = None
    is_obm: bool = False
    bubble_point_psi: float | None = 1500.0
    is_custom: bool = False

    @property
    def standard(self) -> Standard:
        return Standard(require_kill=self.require_kill)

    def summary(self) -> dict:
        """What the picker and the briefing panel show."""
        return {
            "key": self.key,
            "name": self.name,
            "objective": self.objective,
            "briefing": self.briefing,
            "bop": self.bop,
            "trajectory": self.trajectory,
            "start": self.start.value,
            "require_kill": self.require_kill,
            # Named, but not when or what they do. A student who knows the
            # choke is going to plug at stroke 2,000 is not being tested on
            # noticing that the choke has plugged.
            "has_faults": bool(self.faults),
            "mud_weight_ppg": self.mud_weight_ppg,
            "sidpp_psi": self.sidpp_psi,
            "sicp_psi": self.sicp_psi,
            "pit_gain_bbl": self.pit_gain_bbl,
            "frac_gradient_ppg": self.frac_gradient_ppg,
            "shoe_md_ft": self.shoe_md_ft,
            "bit_off_bottom_ft": self.bit_off_bottom_ft,
            "kick_after_s": self.kick_after_s,
            "is_obm": self.is_obm,
            "bubble_point_psi": self.bubble_point_psi,
            "is_custom": self.is_custom,
        }

    def detailed_dict(self) -> dict:
        """Full specification including faults for instructors and storage."""
        d = self.summary()
        d["faults"] = [
            {
                "kind": f.kind.value,
                "at_seconds": f.at_seconds,
                "at_strokes": f.at_strokes,
                "after_event": f.after_event.value if f.after_event else None,
                "message": f.message,
                "severity": f.severity.value,
            }
            for f in self.faults
        ]
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "Scenario":
        """Build from the same shape as JSON, so exercises can live in a file."""
        return cls(
            key=data["key"],
            name=data["name"],
            objective=data["objective"],
            briefing=data.get("briefing", ""),
            bop=data.get("bop", "surface"),
            trajectory=data.get("trajectory", "vertical"),
            start=StartState(data.get("start", "shut_in")),
            bit_off_bottom_ft=float(data.get("bit_off_bottom_ft", 0.0)),
            open_valves=tuple(data.get("open_valves", ())),
            closed_valves=tuple(data.get("closed_valves", ())),
            faults=tuple(Fault.from_dict(f) for f in data.get("faults", ())),
            require_kill=bool(data.get("require_kill", False)),
            migration_rate_ft_per_hr=(
                float(data["migration_rate_ft_per_hr"])
                if data.get("migration_rate_ft_per_hr") is not None
                else None
            ),
            mud_weight_ppg=(
                float(data["mud_weight_ppg"])
                if data.get("mud_weight_ppg") is not None
                else None
            ),
            sidpp_psi=(
                float(data["sidpp_psi"])
                if data.get("sidpp_psi") is not None
                else None
            ),
            sicp_psi=(
                float(data["sicp_psi"])
                if data.get("sicp_psi") is not None
                else None
            ),
            pit_gain_bbl=(
                float(data["pit_gain_bbl"])
                if data.get("pit_gain_bbl") is not None
                else None
            ),
            frac_gradient_ppg=(
                float(data["frac_gradient_ppg"])
                if data.get("frac_gradient_ppg") is not None
                else None
            ),
            shoe_md_ft=(
                float(data["shoe_md_ft"])
                if data.get("shoe_md_ft") is not None
                else None
            ),
            kick_after_s=(
                float(data["kick_after_s"])
                if data.get("kick_after_s") is not None
                else None
            ),
            is_obm=bool(data.get("is_obm", False)),
            bubble_point_psi=(
                float(data["bubble_point_psi"])
                if data.get("bubble_point_psi") is not None
                else 1500.0
            ),
            is_custom=bool(data.get("is_custom", False)),
        )


# --------------------------------------------------------------------------
# The built-in library
# --------------------------------------------------------------------------

#: Lineups the scenarios build on, named so the intent is readable.
_REVERSE = (
    "pump_to_kill_line", "kill_line_valve",
    "float_valve", "standpipe_valve", "standpipe_to_manifold", "choke_1",
)
_LUBRICATE = ("pump_to_kill_line", "kill_line_valve")


SCENARIOS: tuple[Scenario, ...] = (
    Scenario(
        key="drillers",
        name="Driller's Method — shut in on a kick",
        objective="Circulate the influx out at constant bottomhole pressure.",
        briefing=(
            "The well is shut in on a kick taken while drilling. The pressures "
            "have stabilised and the choke line is lined up. Bring the pump to "
            "kill rate and hold bottomhole pressure on the formation."
        ),
        require_kill=False,
    ),
    Scenario(
        key="wait_and_weight",
        name="Wait and Weight — one circulation kill",
        objective="Kill the well in a single circulation using weighted kill mud.",
        briefing=(
            "The well is shut in on a kick and kill mud has been weighted up in "
            "the pits. Bring the pump up to kill rate while holding casing pressure "
            "constant, follow the drill pipe step-down schedule from ICP to FCP as "
            "kill mud moves to the bit, then maintain constant FCP until kill mud "
            "reaches surface."
        ),
        require_kill=True,
    ),
    Scenario(
        key="find_the_kick",
        name="Drilling ahead — find the kick",
        objective="Spot the kick, shut in, and read your own shut-in pressures.",
        briefing=(
            "Drilling ahead, everything normal. There is no bottomhole gauge on "
            "a rig: watch the pit level and the flow line. When you are sure "
            "the well is flowing, shut in and let the pressures stabilise."
        ),
        start=StartState.DRILLING,
    ),
    Scenario(
        key="volumetric",
        name="Volumetric — the pump is down",
        objective=(
            "Hold bottomhole pressure by bleeding alone, with no circulation."
        ),
        briefing=(
            "Shut in on a kick, and the mud pump will not run. The gas is "
            "migrating and surface pressure will climb on its own. Let it rise "
            "in controlled steps and bleed mud back to hold bottomhole "
            "pressure. Doing nothing is not a neutral choice."
        ),
        faults=(
            Fault(
                kind=FaultKind.PUMP_FAILURE,
                at_seconds=0.0,
                message="Mud pump will not run — fluid end failure.",
            ),
        ),
    ),
    Scenario(
        key="bullhead",
        name="Bullheading — force influx into formation",
        objective="Force the influx back into the formation without circulating.",
        briefing=(
            "Circulation is impossible or unacceptable. The choke is closed. "
            "Pump mud down the hole to squeeze the influx back into the formation "
            "it came from. Monitor standpipe pressure and stop pumping once the "
            "influx is displaced."
        ),
        closed_valves=("choke_line_valve", "choke_1", "choke_bypass"),
        migration_rate_ft_per_hr=0.0,
        require_kill=True,
    ),
    Scenario(
        key="lube_and_bleed",
        name="Lube and Bleed — gas at surface",
        objective="Replace the gas cap with mud, a slug at a time.",
        briefing=(
            "The gas has migrated to surface and the well is shut in. Line the "
            "pump up to the kill line, lubricate mud in on top of the gas, let "
            "it fall through, then bleed the gas off. Repeat."
        ),
        open_valves=_LUBRICATE,
    ),
    Scenario(
        key="stripping",
        name="Stripping back to bottom",
        objective="Run the bit back to bottom through a closed BOP.",
        briefing=(
            "A kick was taken with the bit off bottom, and the well is shut in. "
            "Strip the pipe back down, bleeding the steel it displaces to hold "
            "bottomhole pressure. Watch the hookload as well as the gauges."
        ),
        bit_off_bottom_ft=1000.0,
    ),
    Scenario(
        key="reverse",
        name="Reverse circulation — float ported",
        objective="Bring the influx up the drill pipe instead of the annulus.",
        briefing=(
            "The float has been ported, so returns can come back up the string. "
            "Pump down the annulus through the kill line and take returns up "
            "the pipe to the choke. The influx never passes the shoe."
        ),
        open_valves=_REVERSE,
        closed_valves=("pump_discharge", "choke_line_valve"),
    ),
    Scenario(
        key="choke_plugs",
        name="The choke plugs",
        objective="Circulate the influx out, and deal with what happens.",
        briefing=(
            "A routine Driller's Method circulation. Hold bottomhole pressure "
            "on the formation and get the influx out."
        ),
        faults=(
            Fault(
                kind=FaultKind.CHOKE_PLUGGED,
                at_strokes=900.0,
                message=(
                    "Choke 1 is not responding — pressure climbing with the "
                    "handle where it is."
                ),
            ),
        ),
    ),
    Scenario(
        key="horizontal",
        name="Horizontal well — Driller's preferred",
        objective="Circulate out a kick in a lateral.",
        briefing=(
            "A horizontal well. The influx sits in the lateral, where it has no "
            "vertical height, so it barely shows on the shut-in pressures and "
            "it will not migrate. Wait and Weight would need a separate drill "
            "pipe schedule for every section."
        ),
        trajectory="horizontal",
    ),
    Scenario(
        key="subsea",
        name="Subsea BOP — choke line friction",
        objective="Circulate out with the stack on the seabed.",
        briefing=(
            "A subsea stack. Choke line friction acts on the formation, and the "
            "gauge is at the rig floor while the BOP is at the mudline. Both "
            "have to be allowed for."
        ),
        bop="subsea",
    ),
    Scenario(
        key="weak_shoe",
        name="Weak casing seat",
        objective="Get the influx out without breaking down the shoe.",
        briefing=(
            "The casing seat on this well is not what the leak-off test said. "
            "There is less margin than the kill sheet suggests."
        ),
        faults=(
            Fault(
                kind=FaultKind.WEAK_SHOE,
                at_seconds=0.0,
                message="Formation integrity below the recorded leak-off.",
                severity=Severity.WARNING,
            ),
        ),
    ),
    Scenario(
        key="trapped_gas_subsea",
        name="Subsea — trapped gas below BOP",
        objective="Circulate trapped gas from beneath the subsea stack before opening BOP.",
        briefing=(
            "The kick was circulated, but an expansion pocket of gas remains "
            "trapped below the subsea annular preventer. Opening the stack "
            "without clearing it would unload the marine riser! Line up the kill "
            "line down to the BOP and bleed the trapped gas across the choke "
            "manifold under backpressure before clearing the riser."
        ),
        bop="subsea",
        start=StartState.SHUT_IN,
    ),
    Scenario(
        key="snubbing",
        name="Snubbing — pipe light under pressure",
        objective="Safely strip in hole under pipe-light conditions where well pressure exceeds string weight.",
        briefing=(
            "A kick was shut in while tripping out with the bit 9,200 ft off bottom "
            "(only 800 ft of pipe in the hole) and surface pressure is high. "
            "Upward well pressure nearly balances the buoyed string weight — the hookload "
            "is barely above zero! As gas migrates or pipe is run, hookload drops below zero (pipe light). "
            "Manage pressure and snub the pipe safely back to bottom."
        ),
        bit_off_bottom_ft=9200.0,
        start=StartState.SHUT_IN,
    ),
    Scenario(
        key="obm_kick",
        name="Oil-Based Mud (OBM) — Gas Solubility & Surface Breakout",
        objective="Manage rapid gas flash breakout near surface without unloading the well or exceeding shoe pressure.",
        briefing=(
            "Drilling in synthetic oil-based mud (OBM). Gas influx dissolves directly "
            "into the base oil downhole with minimal initial pit gain. As the kick ascends above "
            "the 1,500 psi bubble point, methane flashes rapidly out of solution. Anticipate "
            "the violent breakout, feather the choke, and catch the pressure surge."
        ),
        bop="surface",
        trajectory="vertical",
        start=StartState.SHUT_IN,
        mud_weight_ppg=12.0,
        shoe_md_ft=8000.0,
        frac_gradient_ppg=14.5,
        sidpp_psi=420.0,
        sicp_psi=580.0,
        pit_gain_bbl=20.0,
        is_obm=True,
        bubble_point_psi=1500.0,
        require_kill=True,
    ),
)

_BY_KEY = {s.key: s for s in SCENARIOS}
_CUSTOM_SCENARIOS: dict[str, Scenario] = {}

#: Dedicated storage location for custom scenario JSON files
CUSTOM_DIR = (
    Path(__file__).resolve().parent.parent.parent.parent
    / "data"
    / "custom_scenarios"
)


def _load_custom_scenarios_from_disk() -> None:
    """Load previously saved custom scenario definitions from disk."""
    if not CUSTOM_DIR.exists():
        return
    for path in CUSTOM_DIR.glob("*.json"):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            data["is_custom"] = True
            scen = Scenario.from_dict(data)
            _CUSTOM_SCENARIOS[scen.key] = scen
        except Exception:
            pass


_load_custom_scenarios_from_disk()


def save_custom_scenario(data: dict) -> Scenario:
    """Create or update a custom well control scenario and persist to disk."""
    raw_key = str(data.get("key", "")).strip().lower().replace(" ", "_")
    key = "".join(c for c in raw_key if c.isalnum() or c in ("_", "-"))
    if not key:
        raise ValueError("Scenario 'key' cannot be empty.")
    if key in _BY_KEY:
        raise ValueError(
            f"Scenario key '{key}' conflicts with a built-in standard scenario."
        )

    data_copy = dict(data)
    data_copy["key"] = key
    data_copy["is_custom"] = True
    scen = Scenario.from_dict(data_copy)

    CUSTOM_DIR.mkdir(parents=True, exist_ok=True)
    file_path = CUSTOM_DIR / f"{key}.json"
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(scen.detailed_dict(), f, indent=2)

    _CUSTOM_SCENARIOS[key] = scen
    return scen


def delete_custom_scenario(key: str) -> bool:
    """Remove a custom scenario from active registry and delete from disk."""
    if key not in _CUSTOM_SCENARIOS:
        return False
    _CUSTOM_SCENARIOS.pop(key, None)
    file_path = CUSTOM_DIR / f"{key}.json"
    if file_path.exists():
        try:
            file_path.unlink()
        except OSError:
            pass
    return True


def get_custom_templates() -> list[dict]:
    """Pre-engineered scenario templates ready for instructor customization."""
    return [
        {
            "key": "deepwater_gas_washout",
            "name": "Deepwater HPHT Gas Kick with Choke Washout",
            "objective": "Circulate out high-pressure deepwater gas while diagnosing severe choke orifice erosion.",
            "briefing": "Drilling with 13.0 ppg mud at 12,500 ft TVD subsea. A 30 bbl gas kick is shut in. At stroke 800, tungsten carbide choke beans suffer erosive washout from abrasive sand. Switch to standby choke and maintain constant BHP.",
            "bop": "subsea",
            "trajectory": "deviated",
            "start": "shut_in",
            "mud_weight_ppg": 13.0,
            "shoe_md_ft": 9800.0,
            "frac_gradient_ppg": 15.2,
            "sidpp_psi": 520.0,
            "sicp_psi": 780.0,
            "pit_gain_bbl": 30.0,
            "require_kill": True,
            "faults": [
                {
                    "kind": "choke_washout",
                    "at_strokes": 800,
                    "message": "Choke valve orifice severe erosion/washout detected — casing pressure dropping rapidly!",
                    "severity": "critical",
                }
            ],
        },
        {
            "key": "narrow_margin_losses",
            "name": "Narrow Margin Depleted Sand — Weak Shoe Breakdown",
            "objective": "Kill the well with less than 150 psi margin before exceeding shoe fracture pressure.",
            "briefing": "Operating through a depleted formation with high pore pressure below. Shoe fracture margin is extremely narrow (13.8 ppg LOT vs 12.8 ppg influx EMW). At stroke 1,200, shoe breaks down. Control backpressure to avoid total losses.",
            "bop": "surface",
            "trajectory": "vertical",
            "start": "shut_in",
            "mud_weight_ppg": 12.0,
            "shoe_md_ft": 8200.0,
            "frac_gradient_ppg": 13.8,
            "sidpp_psi": 420.0,
            "sicp_psi": 610.0,
            "pit_gain_bbl": 20.0,
            "require_kill": True,
            "faults": [
                {
                    "kind": "weak_shoe",
                    "at_strokes": 1200,
                    "message": "Casing shoe integrity compromised — micro-fracturing detected in permeable sand.",
                    "severity": "critical",
                }
            ],
        },
        {
            "key": "horizontal_detection_drill",
            "name": "Horizontal Lateral — Active Drilling Kick Detection",
            "objective": "Detect subtle influx signature in a 3,000 ft horizontal drainhole and execute immediate soft shut-in.",
            "briefing": "Drilling the 8-1/2 inch reservoir section at 14,000 ft MD (9,200 ft TVD). In horizontal holes, gas influx does not build vertical hydrostatic head initially. Watch flow show and pit volume totalizer closely.",
            "bop": "surface",
            "trajectory": "horizontal",
            "start": "drilling",
            "mud_weight_ppg": 11.4,
            "shoe_md_ft": 9400.0,
            "frac_gradient_ppg": 14.5,
            "kick_after_s": 60.0,
            "require_kill": False,
            "faults": [],
        },
        {
            "key": "pump_packing_failure",
            "name": "Driller's Circulation with Triplex Pump Breakdown",
            "objective": "Manage pump swap during first circulation without allowing bottomhole pressure to plunge.",
            "briefing": "First circulation of Driller's Method is underway. At stroke 1,500, mud pump #1 blows fluid-end valve packing. Shut in or switch to pump #2 on the fly while feathering the choke.",
            "bop": "surface",
            "trajectory": "vertical",
            "start": "shut_in",
            "mud_weight_ppg": 10.2,
            "shoe_md_ft": 7500.0,
            "frac_gradient_ppg": 14.0,
            "sidpp_psi": 380.0,
            "sicp_psi": 530.0,
            "pit_gain_bbl": 18.0,
            "require_kill": False,
            "faults": [
                {
                    "kind": "pump_failure",
                    "at_strokes": 1500,
                    "message": "Triplex Mud Pump #1 blown packing and ruptured discharge liner!",
                    "severity": "critical",
                }
            ],
        },
    ]


def get_scenario(key: str) -> Scenario:
    """Look one up by key across built-in and custom scenarios.

    Raises:
        KeyError: naming the ones that exist, so a typo is self-correcting.
    """
    if key in _CUSTOM_SCENARIOS:
        return _CUSTOM_SCENARIOS[key]
    if key in _BY_KEY:
        return _BY_KEY[key]
    all_keys = sorted(list(_BY_KEY.keys()) + list(_CUSTOM_SCENARIOS.keys()))
    raise KeyError(
        f"No scenario '{key}'. Available: {', '.join(all_keys)}"
    )


def scenario_list() -> list[dict]:
    """Every scenario (built-in and custom), for the picker."""
    return [s.summary() for s in SCENARIOS] + [
        s.summary() for s in _CUSTOM_SCENARIOS.values()
    ]


def custom_scenario_list() -> list[dict]:
    """Only custom instructor-defined scenarios (including faults for editor)."""
    return [s.detailed_dict() for s in _CUSTOM_SCENARIOS.values()]
