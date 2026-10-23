"""Equipment the student operates: the pump, the choke, the trip tank.

Everything here answers one question -- how much flow, given what the student
has set? The engine takes those answers and does the volume balance.

The choke is the important one. It is the instrument the whole exercise turns
on, and its behaviour has to be right in a specific way: **the same choke
movement must matter differently depending on what is in the hole.** That is
not modelled here directly; it falls out of the volume balance in
:mod:`wellcontrol.sim.engine`. What this module supplies is an honest
relationship between opening, pressure drop and flow.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from ..geometry import Pump


@dataclass
class MudPump:
    """A rig pump under the driller's control.

    Wraps the library :class:`~wellcontrol.geometry.Pump` with the state a
    simulator needs: whether it is running, how fast, and how quickly it can
    change speed. Pumps do not step instantly from zero to kill rate, and the
    ramp is where a lot of well control goes wrong.
    """

    pump: Pump
    running: bool = False
    spm: float = 0.0
    commanded_spm: float = 0.0
    max_spm: float = 120.0
    #: How fast the pump can change speed, spm per second.
    ramp_rate: float = 2.0

    def command(self, spm: float) -> None:
        """Ask for a speed. The pump ramps toward it rather than jumping."""
        self.commanded_spm = max(0.0, min(spm, self.max_spm))
        if self.commanded_spm > 0:
            self.running = True

    def stop(self) -> None:
        self.commanded_spm = 0.0

    def advance(self, dt: float) -> None:
        """Move the actual speed toward the commanded speed."""
        step = self.ramp_rate * dt
        if self.spm < self.commanded_spm:
            self.spm = min(self.commanded_spm, self.spm + step)
        elif self.spm > self.commanded_spm:
            self.spm = max(self.commanded_spm, self.spm - step)
        self.running = self.spm > 1e-6

    @property
    def flow_bbl_per_min(self) -> float:
        return self.pump.output_bbl_per_stroke * self.spm

    def strokes_in(self, dt: float) -> float:
        return self.spm * dt / 60.0


@dataclass
class AdjustableChoke:
    """An adjustable choke.

    Flow follows the standard orifice relation::

        Q = Cd . A . sqrt(2 . dP / rho)

    What matters for training is the **shape**, not the constant: flow goes
    with the square root of pressure drop and roughly with the square of the
    opening near the seat. So the choke is insensitive when wide open and
    vicious when nearly shut, which is where a kill is actually controlled.

    Attributes:
        position: Opening, 0 (shut) to 100 (wide open).
        full_open_area_in2: Flow area at 100%.
        discharge_coefficient: Cd, around 0.8 for a choke bean.
        travel_rate: How fast the position can change, percent per second. A
            real choke takes seconds to move, and a student who expects it to
            be instant will over-correct.
    """

    position: float = 0.0
    full_open_area_in2: float = 2.0
    discharge_coefficient: float = 0.8
    travel_rate: float = 10.0
    commanded_position: float = 0.0

    def command(self, position: float) -> None:
        self.commanded_position = max(0.0, min(100.0, position))

    def advance(self, dt: float) -> None:
        step = self.travel_rate * dt
        if self.position < self.commanded_position:
            self.position = min(self.commanded_position, self.position + step)
        elif self.position > self.commanded_position:
            self.position = max(self.commanded_position, self.position - step)

    @property
    def area_in2(self) -> float:
        """Flow area at the current opening.

        Squared rather than linear with position: a choke's effective area
        closes far faster than its travel near the seat, which is why the last
        ten percent of the handle does most of the work.
        """
        fraction = max(0.0, min(1.0, self.position / 100.0))
        return self.full_open_area_in2 * fraction ** 2

    def flow_bbl_per_min(
        self, pressure_drop_psi: float, density_ppg: float
    ) -> float:
        """Flow the choke will pass at a given pressure drop, bbl/min.

        Returns zero for a shut choke or a negative pressure drop -- a choke
        does not flow backwards.
        """
        if self.area_in2 <= 0.0 or pressure_drop_psi <= 0.0 or density_ppg <= 0:
            return 0.0

        # Q(gpm) = 29.81 . Cd . d^2 . sqrt(dP / rho) is the familiar nozzle
        # form with d in inches; expressed through area it becomes the constant
        # below. Converted to bbl/min for the volume balance.
        gpm = (
            37.94
            * self.discharge_coefficient
            * self.area_in2
            * math.sqrt(pressure_drop_psi / density_ppg)
        )
        return gpm / 42.0

    @property
    def is_shut(self) -> bool:
        return self.position <= 1e-9


@dataclass
class TripTank:
    """A calibrated tank for measuring what the well takes or gives back."""

    volume_bbl: float = 50.0
    baseline_bbl: float = 50.0

    @property
    def change_bbl(self) -> float:
        """Positive when the tank has gained -- the well gave fluid back."""
        return self.volume_bbl - self.baseline_bbl

    def zero(self) -> None:
        self.baseline_bbl = self.volume_bbl

    def refill(self, target_bbl: float = 50.0) -> None:
        self.volume_bbl = target_bbl
        self.baseline_bbl = target_bbl


@dataclass
class Accumulator:
    """The BOP closing unit, and the fact that it is not free.

    Every element operated takes hydraulic volume out of the bottles, and the
    pressure falls. The pumps put it back, slowly. A student who cycles the
    stack because they are unsure can find they have nothing left to close
    with, which is a real way to lose a well and is invisible if the BOP panel
    is drawn as a row of indicator lights.

    Attributes:
        pressure_psi: What the gauge on the closing unit reads.
        minimum_psi: Below this there is not enough to shift an element. Stands
            in for the accumulator precharge.
        recharge_psi_per_min: How fast the pumps make it back up.
        annular_cost_psi: Pressure given up closing or opening the annular. It
            has the largest closing volume of the three.
        ram_cost_psi: The same for a set of rams.
    """

    pressure_psi: float = 3000.0
    capacity_psi: float = 3000.0
    minimum_psi: float = 1200.0
    recharge_psi_per_min: float = 60.0
    annular_cost_psi: float = 250.0
    ram_cost_psi: float = 150.0

    @property
    def can_operate(self) -> bool:
        return self.pressure_psi > self.minimum_psi

    @property
    def fraction(self) -> float:
        return max(0.0, min(1.0, self.pressure_psi / self.capacity_psi))

    def operate(self, is_annular: bool) -> bool:
        """Spend the volume for one element. False if there is not enough."""
        if not self.can_operate:
            return False
        cost = self.annular_cost_psi if is_annular else self.ram_cost_psi
        self.pressure_psi = max(0.0, self.pressure_psi - cost)
        return True

    def advance(self, dt: float) -> None:
        self.pressure_psi = min(
            self.capacity_psi,
            self.pressure_psi + self.recharge_psi_per_min * dt / 60.0,
        )


@dataclass
class PitSystem:
    """The active system, and the gain that tells you a well is flowing."""

    active_bbl: float = 800.0
    baseline_bbl: float = 800.0

    @property
    def gain_bbl(self) -> float:
        return self.active_bbl - self.baseline_bbl

    def zero(self) -> None:
        self.baseline_bbl = self.active_bbl
