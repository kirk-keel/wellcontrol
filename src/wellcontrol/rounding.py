"""Well control rounding rules.

Rounding in well control is **directional**, not to-nearest. Every quantity is
rounded the way that adds margin, because the arithmetic feeds a decision made
under pressure with an incomplete picture of the well.

=====================  ===========  =======  ==============================
Quantity               Direction    Places   Why that direction is safe
=====================  ===========  =======  ==============================
Kill mud weight        **up**       1        Heavier mud, more overbalance
Max allowable MW       **down**     1        Lower ceiling, less chance of
                                             fracturing the shoe
MAASP / MASP           **down**     0        Lower limit, more margin before
                                             breakdown
Pressure step          **down**     0        Smaller decrement, so pressure
                                             stays higher longer and BHP
                                             stays up
Strokes                **up**       0        No such thing as a fraction of a
                                             stroke, and stopping short of a
                                             target is the failure mode
Volume                 nearest      1        Measured, not a limit -- but see
                                             the note on half-up below
=====================  ===========  =======  ==============================

## Nearest means half away from zero

Where a quantity rounds to nearest rather than in a safe direction, it rounds
the way it is done on paper: **3.45 bbl is 3.5**. Python's built-in ``round``
does not do this -- it uses banker's rounding, sending halves to the nearest
even digit, so ``round(0.5)`` is 0 and ``round(2.5)`` is 2. Nobody filling in a
kill sheet rounds that way, and a figure that disagrees with the one the crew
worked by hand is worse than useless.

A worked pair: a computed kill mud weight of 10.37 ppg is mixed as **10.4**,
and a computed MAASP of 1,181.6 psi is written as **1,181**. Rounding either
one the other way would quietly remove margin -- the mud would be light, or the
limit would be higher than the well can actually stand.

**Rounded values are the operational ones.** The rig mixes 10.4 ppg, so 10.4 is
what the final circulating pressure and the schedule are built from, not 10.37.
Where the unrounded figure is useful for showing the working, it is available
alongside under an ``_exact`` name.

## Floating point

``10.4 * 10`` is ``104.00000000000001`` in binary floating point, so a naive
``ceil`` would push it to 10.5 -- rounding up a value that needed no rounding at
all. Every function here snaps to a tolerance first.
"""

from __future__ import annotations

import math
from decimal import ROUND_HALF_UP, Decimal

#: Decimal places to snap to before applying a directional rounding, to stop
#: binary representation error from triggering a spurious step.
_SNAP = 9


def _snap(value: float) -> float:
    return round(value, _SNAP)


def _half_up(value: float, places: int) -> float:
    """Round half away from zero -- the way it is done on paper.

    Python's built-in ``round`` uses banker's rounding, which sends halves to
    the nearest even digit: ``round(0.5)`` is 0 and ``round(2.5)`` is 2. That
    is not what anyone means by rounding a well control figure. 3.45 bbl is
    3.5, not 3.4.

    Going through ``Decimal`` on the string form also sidesteps binary
    representation: ``Decimal("3.45")`` is exactly 3.45, where the float 3.45
    is not, and rounding the float directly can fall either way.
    """
    quantum = Decimal(1).scaleb(-places)
    return float(Decimal(str(_snap(value))).quantize(quantum, ROUND_HALF_UP))


# --------------------------------------------------------------------------
# Mud weight
# --------------------------------------------------------------------------

def kill_mud_weight(ppg: float) -> float:
    """Round a kill mud weight UP to the nearest tenth of a ppg.

    10.37 becomes 10.4. Rounding down would mix mud lighter than the well
    needs, which is the one direction a kill mud weight must never err in.

    >>> kill_mud_weight(10.37)
    10.4
    >>> kill_mud_weight(10.40)
    10.4
    """
    return math.ceil(_snap(ppg * 10.0)) / 10.0


def max_allowable_mud_weight(ppg: float) -> float:
    """Round a maximum allowable mud weight DOWN to the nearest tenth.

    A limit, so it rounds the other way from the kill weight. 12.87 becomes
    12.8, not 12.9 -- claiming the extra tenth would be claiming strength the
    formation has not been shown to have.

    >>> max_allowable_mud_weight(12.87)
    12.8
    """
    return math.floor(_snap(ppg * 10.0)) / 10.0


# --------------------------------------------------------------------------
# Pressure
# --------------------------------------------------------------------------

def pressure_limit(psi: float) -> int:
    """Round a pressure limit DOWN to a whole psi.

    For MAASP, MASP and anything else that is a ceiling on what the well can
    stand. 1181.6 becomes 1181.

    >>> pressure_limit(1181.6)
    1181
    """
    return int(math.floor(_snap(psi)))


def pressure(psi: float) -> int:
    """Round a pressure to a whole psi, half away from zero.

    For reporting a computed pressure that is not itself a limit -- formation
    pressure, ICP, FCP. Pressures are not quoted with decimals in well control;
    no gauge on a rig resolves better than a few psi.

    >>> pressure(1000.4)
    1000
    >>> pressure(1000.5)
    1001
    """
    return int(_half_up(psi, 0))


def pressure_step(psi: float) -> int:
    """Round a per-step pressure decrement DOWN to a whole psi.

    A schedule that comes down 51.6 psi per step is worked as 51. Rounding up
    would take drill pipe pressure -- and with it bottomhole pressure -- down
    faster than the schedule intends, eating the overbalance.

    The cost is that the steps no longer land exactly on FCP; the last step is
    slightly short, leaving marginally more pressure on the well. That is the
    right way for the error to fall.

    >>> pressure_step(51.6)
    51
    """
    return int(math.floor(_snap(psi)))


# --------------------------------------------------------------------------
# Strokes
# --------------------------------------------------------------------------

def strokes(count: float) -> int:
    """Round a stroke count UP to a whole number.

    There is no such thing as a fraction of a pump stroke, and the rounding
    goes up because a stroke count is a target to be reached, not a limit. A
    displacement needing 1465.1 strokes is not complete at 1465 -- kill mud
    would still be short of the bit, and every figure that assumes it arrived
    would be wrong.

    Stopping short is the failure mode; a stroke of overshoot is not.

    >>> strokes(1465.1)
    1466
    >>> strokes(1466.0)
    1466
    """
    return int(math.ceil(_snap(count)))


# --------------------------------------------------------------------------
# Volume
# --------------------------------------------------------------------------

def volume(bbl: float) -> float:
    """Round a volume to **one decimal place**, half away from zero.

    Volumes are measured rather than computed against a limit, so they round to
    nearest rather than in a safe direction -- but to nearest the way it is
    done on paper, not the way Python's ``round`` does it. 3.45 bbl is 3.5.

    One decimal place throughout. A trip tank does not resolve more finely than
    that, so quoting a bleed volume as 2.26 bbl implies a precision the
    measurement does not have.

    >>> volume(3.45)
    3.5
    >>> volume(470.095)
    470.1
    """
    return _half_up(bbl, 1)
