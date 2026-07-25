"""Kill methods, and the registry that selects between them.

Six methods, covering the ways a well can be killed:

======================  ===========================================
Method                  Used when
======================  ===========================================
Driller's Method        Standard. Start immediately, weight up later.
Wait and Weight         Standard. Weight up first, one circulation.
Volumetric Method       Cannot circulate; gas migrating.
Stripping to Bottom     Bit off bottom; restore the circulation path.
Lube and Bleed          Cannot circulate; gas already at surface.
Reverse Circulation     Keeping the influx away from the casing shoe.
Bullheading             Cannot or must not bring the influx up.
======================  ===========================================

Usage::

    from wellcontrol.methods import get_method, plan_kill

    plan = plan_kill(well, "wait_and_weight")
    print(plan.format_summary())
    for stage in plan.stages:
        print(stage.name)

Every plan carries an :class:`~wellcontrol.methods.base.Applicability` verdict.
Check ``plan.applicability.usable`` and read the blockers and warnings before
using the numbers -- not every method works on every well, and the framework
says so rather than quietly producing figures for a procedure that would stall.
"""

from __future__ import annotations

from dataclasses import dataclass

from .alternative import Bullhead, ReverseCirculation
from .base import (
    Applicability,
    FluidColumn,
    KillMethod,
    KillPlan,
    KillStage,
    TracePoint,
    WellState,
    Zone,
)
from .circulating import DrillersMethod, WaitAndWeight, simulate_circulation
from .stripping import StrippingToBottom
from .volumetric import LubeAndBleed, VolumetricMethod

#: All available methods, in the order they should be offered.
METHODS: tuple[KillMethod, ...] = (
    DrillersMethod(),
    WaitAndWeight(),
    VolumetricMethod(),
    StrippingToBottom(),
    LubeAndBleed(),
    ReverseCirculation(),
    Bullhead(),
)

_BY_KEY = {method.key: method for method in METHODS}


def list_methods() -> list[KillMethod]:
    """Every method, in presentation order."""
    return list(METHODS)


def method_keys() -> list[str]:
    return [method.key for method in METHODS]


def get_method(key: str) -> KillMethod:
    """Look a method up by key.

    Raises:
        KeyError: if the key is not one of the six methods.
    """
    if key not in _BY_KEY:
        raise KeyError(
            f"Unknown kill method '{key}'. Available: {sorted(_BY_KEY)}"
        )
    return _BY_KEY[key]


def plan_kill(well: WellState, method_key: str) -> KillPlan:
    """Plan a kill on a well using the named method."""
    return get_method(method_key).plan(well)


@dataclass
class KillSequence:
    """Stripping to bottom followed by a circulating kill.

    A kick taken with the bit off bottom is not one operation but two, and
    planning them separately hides what matters: the total time the well is
    open, and which of the two phases actually puts the most pressure on the
    shoe. Often it is the stripping, not the kill.
    """

    strip: KillPlan
    kill: KillPlan
    well_off_bottom: WellState
    well_on_bottom: WellState

    @property
    def usable(self) -> bool:
        return self.strip.applicability.usable and self.kill.applicability.usable

    @property
    def blockers(self) -> list[str]:
        return (
            [f"Stripping: {b}" for b in self.strip.applicability.blockers]
            + [f"{self.kill.method_name}: {b}"
               for b in self.kill.applicability.blockers]
        )

    @property
    def warnings(self) -> list[str]:
        return (
            [f"Stripping: {w}" for w in self.strip.applicability.warnings]
            + [f"{self.kill.method_name}: {w}"
               for w in self.kill.applicability.warnings]
        )

    @property
    def peak_shoe_pressure_psi(self) -> float | None:
        values = [p for p in (self.strip.peak_shoe_pressure_psi,
                              self.kill.peak_shoe_pressure_psi) if p is not None]
        return max(values) if values else None

    @property
    def worst_phase(self) -> str:
        """Which phase puts the most pressure on the shoe."""
        strip_peak = self.strip.peak_shoe_pressure_psi
        kill_peak = self.kill.peak_shoe_pressure_psi
        if strip_peak is None or kill_peak is None:
            return "unknown"
        return "stripping" if strip_peak >= kill_peak else "the kill"

    @property
    def total_hours(self) -> float:
        strip_hours = float(self.strip.summary.get("Stripping time (hr)", 0.0) or 0.0)
        strokes = self.kill.trace[-1].x if self.kill.trace else 0.0
        spm = self.well_on_bottom.slow_circulating_rate.spm
        kill_hours = strokes / spm / 60.0 if spm else 0.0
        return strip_hours + kill_hours

    def summary(self) -> dict[str, object]:
        strip_hours = float(self.strip.summary.get("Stripping time (hr)", 0.0) or 0.0)
        strokes = self.kill.trace[-1].x if self.kill.trace else 0.0
        spm = self.well_on_bottom.slow_circulating_rate.spm
        kill_hours = strokes / spm / 60.0 if spm else 0.0
        out: dict[str, object] = {
            "Phase 1": "Strip to bottom",
            "Bit from (ft MD)": round(self.well_off_bottom.bit_md_ft),
            "Bit to (ft MD)": round(self.well_on_bottom.bit_md_ft),
            "Stands": self.strip.summary.get("Stands required", "-"),
            "Stripping time (hr)": round(strip_hours, 1),
            "Phase 2": self.kill.method_name,
            "Kill mud weight (ppg)": round(
                self.well_on_bottom.kill_mud_weight_ppg, 2
            ),
            "Kill strokes": round(strokes),
            "Kill time (hr)": round(kill_hours, 1),
            "Total time (hr)": round(strip_hours + kill_hours, 1),
        }
        peak = self.peak_shoe_pressure_psi
        if peak is not None:
            out["Peak shoe, whole operation (psi)"] = round(peak)
            out["Worst phase"] = self.worst_phase
        frac = self.kill.shoe_frac_pressure_psi
        if frac is not None and peak is not None:
            out["Shoe fracture pressure (psi)"] = round(frac)
            out["Margin at shoe (psi)"] = round(frac - peak)
        return out


def strip_then_kill(
    well: WellState, kill_method_key: str = "drillers"
) -> KillSequence:
    """Plan stripping to bottom and the circulating kill that follows.

    The bit must be off bottom for this to mean anything -- with the bit
    already on bottom the well can simply be circulated and the stripping
    phase is empty.

    Args:
        well: The well as it stands, bit off bottom.
        kill_method_key: ``"drillers"`` or ``"wait_and_weight"``.
    """
    if kill_method_key not in ("drillers", "wait_and_weight"):
        raise ValueError(
            f"'{kill_method_key}' is not a circulating kill method. After "
            "stripping to bottom the well is killed conventionally, with "
            "'drillers' or 'wait_and_weight'."
        )
    strip = plan_kill(well, "stripping")
    on_bottom = well.with_bit_at(well.hole_md_ft)
    kill = plan_kill(on_bottom, kill_method_key)
    return KillSequence(
        strip=strip, kill=kill, well_off_bottom=well, well_on_bottom=on_bottom
    )


def applicability_matrix(well: WellState) -> dict[str, Applicability]:
    """Applicability of every method to one well, keyed by method key.

    Useful for greying out or annotating options before the user picks one.
    """
    return {method.key: method.applicability(well) for method in METHODS}


__all__ = [
    "Applicability",
    "Bullhead",
    "DrillersMethod",
    "FluidColumn",
    "KillMethod",
    "KillPlan",
    "KillSequence",
    "KillStage",
    "LubeAndBleed",
    "METHODS",
    "ReverseCirculation",
    "StrippingToBottom",
    "TracePoint",
    "VolumetricMethod",
    "WaitAndWeight",
    "WellState",
    "Zone",
    "applicability_matrix",
    "get_method",
    "list_methods",
    "method_keys",
    "plan_kill",
    "simulate_circulation",
    "strip_then_kill",
]
