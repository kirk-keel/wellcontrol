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
]
