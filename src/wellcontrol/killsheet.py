"""Kill sheet: the numbers that kill the well.

Both constant-bottomhole-pressure methods work the same way. Hold bottomhole
pressure a little above formation pressure at every instant, and the formation
stops flowing. The choke controls annulus pressure; the drill pipe gauge tells
you whether you are getting it right.

**Why the drill pipe gauge and not the casing gauge?** The drill pipe is full
of clean mud of known weight. It is a reliable pressure gauge reading the
bottom of the hole. The annulus contains mud plus an influx of unknown and
changing size -- reading bottomhole pressure through it is guesswork. So:
follow a drill pipe pressure schedule, and use the choke to make the drill pipe
gauge match it.

The schedule itself:

* **ICP** (initial circulating pressure) ``= SIDPP + SCR``. What the gauge
  reads once you are up to kill rate with the original mud still in the string.
* **FCP** (final circulating pressure) ``= SCR x KMW / OMW``. What it reads
  once kill mud has reached the bit. Heavier mud means more friction, so FCP is
  higher than the original SCR -- but there is no longer any SIDPP to add,
  because the kill mud now balances the formation on its own.
* Between those two points the pressure is taken down on a schedule as kill mud
  displaces original mud down the string.

Once kill mud is at the bit, hold FCP constant until it reaches surface.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import rounding
from .geometry import Annulus, Pump
from .hydrostatics import hydrostatic_pressure
from .survey import Survey
from .units import PSI_PER_PPG_FT


# --------------------------------------------------------------------------
# Slow circulating rates
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class SlowCirculatingRate:
    """A measured slow circulating rate pressure.

    Taken on every tour, at every rate that might be used to kill, on every
    pump, and after every change of mud weight or bit. It cannot be measured
    once a kick is in the hole, so if it was not recorded beforehand it has to
    be estimated -- and an estimate is a much weaker basis for a kill.

    Attributes:
        spm: Pump speed at which the reading was taken.
        pressure_psi: Standpipe pressure at that speed.
        pump_label: Which pump.
    """

    spm: float
    pressure_psi: float
    pump_label: str = "Pump 1"

    def scaled_to(self, new_spm: float) -> float:
        """Estimate the pressure at a different pump speed, psi.

        Friction goes roughly with the square of the rate::

            P2 = P1 x (SPM2 / SPM1)^2

        This is an estimate for planning. Measure the rate you intend to use.
        """
        if self.spm <= 0:
            raise ValueError("Reference SPM must be positive")
        return self.pressure_psi * (new_spm / self.spm) ** 2


# --------------------------------------------------------------------------
# Schedule rows
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class ScheduleStep:
    """One row of a drill pipe pressure schedule."""

    strokes: float
    drill_pipe_pressure_psi: float
    volume_bbl: float
    kill_mud_md_ft: float
    note: str = ""


@dataclass(frozen=True)
class ScheduleSegment:
    """A stretch of the kill over which the schedule behaves consistently.

    The drill pipe schedule is only a straight line within a section. It
    changes slope wherever the TVD gained per foot changes (the build), and
    wherever the volume per foot changes (a change of pipe size). Splitting
    the schedule at those points is the difference between a usable schedule
    and one that is wrong in the middle.
    """

    name: str
    reason: str
    top_md: float
    bottom_md: float
    start_strokes: float
    end_strokes: float
    start_pressure_psi: float
    end_pressure_psi: float

    @property
    def strokes(self) -> float:
        return self.end_strokes - self.start_strokes

    @property
    def length_ft(self) -> float:
        return self.bottom_md - self.top_md

    @property
    def pressure_change_psi(self) -> float:
        """Negative when the schedule takes pressure down, as usual."""
        return self.end_pressure_psi - self.start_pressure_psi

    @property
    def slope_psi_per_100_strokes(self) -> float:
        """Rate of change, positive when pressure is being taken DOWN.

        Quoted this way because that is how a driller reads a kill sheet: "come
        down 56 psi every hundred strokes".
        """
        if self.strokes <= 0:
            return 0.0
        return -self.pressure_change_psi / self.strokes * 100.0

    @property
    def pressure_rises(self) -> bool:
        """True when this segment needs pressure taken UP, not down.

        Happens in a lateral: the kill mud front gains no TVD, so hydrostatic
        stops increasing while friction keeps climbing toward FCP. A driller
        following a single straight line would be bleeding pressure off here
        when he should be adding it.
        """
        return self.pressure_change_psi > 0.5


@dataclass(frozen=True)
class Stage:
    """A stage of a kill operation."""

    name: str
    strokes: float
    description: str
    schedule: list[ScheduleStep] = field(default_factory=list)


# --------------------------------------------------------------------------
# Kill sheet
# --------------------------------------------------------------------------

@dataclass
class KillSheet:
    """A complete kill sheet.

    Args:
        sidpp_psi: Shut-in drill pipe pressure.
        sicp_psi: Shut-in casing pressure.
        pit_gain_bbl: Influx volume.
        mud_weight_ppg: Original mud weight (OMW).
        annulus: Wellbore and string geometry.
        survey: Directional survey.
        pump: The pump being used to kill.
        slow_circulating_rate: Measured SCR at kill rate.
        safety_factor_ppg: Extra weight added to the kill mud. Field practice
            varies; some operators use 0, others 0.2-0.5 ppg. Note that this is
            *not* free -- it raises the pressure the shoe sees.
        choke_line_friction_psi: Subsea only. Friction in the choke line at
            kill rate, which must be subtracted from the ICP the driller holds.
            See :mod:`wellcontrol.subsea`.
    """

    sidpp_psi: float
    sicp_psi: float
    pit_gain_bbl: float
    mud_weight_ppg: float
    annulus: Annulus
    survey: Survey
    pump: Pump
    slow_circulating_rate: SlowCirculatingRate
    safety_factor_ppg: float = 0.0
    choke_line_friction_psi: float = 0.0

    # -- depths --------------------------------------------------------------

    @property
    def bit_md_ft(self) -> float:
        return self.annulus.string.bit_depth_md

    @property
    def bit_tvd_ft(self) -> float:
        return self.survey.tvd_at(self.bit_md_ft)

    # -- weights and pressures ----------------------------------------------

    @property
    def formation_pressure_psi(self) -> float:
        """Formation pore pressure, psi."""
        return self.sidpp_psi + hydrostatic_pressure(self.mud_weight_ppg, self.bit_tvd_ft)

    @property
    def kill_mud_weight_exact_ppg(self) -> float:
        """Kill mud weight before rounding, ppg::

            KMW = OMW + SIDPP / (0.052 x TVD)

        Uses **TVD**. On a deviated well, using MD here gives a kill mud weight
        that is too light by the ratio TVD/MD, and the well will not die.

        Shown for the working. What gets mixed is
        :attr:`kill_mud_weight_ppg`.
        """
        return (
            self.mud_weight_ppg
            + self.sidpp_psi / (PSI_PER_PPG_FT * self.bit_tvd_ft)
            + self.safety_factor_ppg
        )

    @property
    def kill_mud_weight_ppg(self) -> float:
        """Kill mud weight as it would be mixed, ppg.

        **Rounded up to the nearest tenth.** 10.37 is mixed as 10.4. Rounding
        down would put lighter mud in the hole than the well needs, which is
        the one direction this figure must never err in.

        This is the operational value, so everything downstream -- the final
        circulating pressure, the schedule, MAASP at kill weight -- is built
        from it rather than from the unrounded figure.
        """
        return rounding.kill_mud_weight(self.kill_mud_weight_exact_ppg)

    @property
    def scr_psi(self) -> float:
        """Slow circulating rate pressure at kill rate, psi."""
        return self.slow_circulating_rate.pressure_psi

    @property
    def initial_circulating_pressure_psi(self) -> float:
        """ICP, psi. ``= SIDPP + SCR``, less choke line friction if subsea."""
        return self.sidpp_psi + self.scr_psi - self.choke_line_friction_psi

    @property
    def final_circulating_pressure_psi(self) -> float:
        """FCP, psi. ``= SCR x KMW / OMW``, less choke line friction if subsea.

        Scaling friction linearly with density is the standard field
        assumption. It holds well when the circulating system is
        turbulent-dominated, which it usually is at kill rates.
        """
        base = self.scr_psi * self.kill_mud_weight_ppg / self.mud_weight_ppg
        return base - self.choke_line_friction_psi

    # -- volumes and strokes -------------------------------------------------

    @property
    def string_volume_bbl(self) -> float:
        """Volume inside the drill string, surface to bit, bbl."""
        return self.annulus.string.internal_volume_bbl

    @property
    def annulus_volume_bbl(self) -> float:
        """Annular volume, total depth to surface, bbl."""
        return self.annulus.volume_bbl

    @property
    def total_volume_bbl(self) -> float:
        return self.string_volume_bbl + self.annulus_volume_bbl

    @property
    def strokes_to_bit(self) -> float:
        """Strokes to pump kill mud from surface to the bit."""
        return self.pump.strokes_for(self.string_volume_bbl)

    @property
    def strokes_bit_to_surface(self) -> float:
        """Strokes to move fluid from the bottom of the annulus to surface.

        This is also how many strokes it takes for the **influx** to reach
        surface once pumping starts -- the annulus starts moving immediately,
        it does not wait for mud to reach the bit.
        """
        return self.pump.strokes_for(self.annulus_volume_bbl)

    @property
    def total_strokes(self) -> float:
        """Strokes for one complete circulation, surface to surface."""
        return self.strokes_to_bit + self.strokes_bit_to_surface

    def minutes_to_bit(self, spm: float | None = None) -> float:
        rate = self.slow_circulating_rate.spm if spm is None else spm
        return self.strokes_to_bit / rate

    def total_minutes(self, spm: float | None = None) -> float:
        rate = self.slow_circulating_rate.spm if spm is None else spm
        return self.total_strokes / rate

    # -- kill mud position ---------------------------------------------------

    def kill_mud_depth_at_volume(self, volume_bbl: float) -> float:
        """MD reached by kill mud after pumping a volume into the string, ft.

        Fills the string from surface down, honouring the capacity change
        where drill pipe meets the heavy-walled pipe and collars.
        """
        if volume_bbl <= 0:
            return 0.0
        remaining = volume_bbl
        for top_md, bottom_md, comp in self.annulus.string.intervals():
            capacity = comp.capacity_bbl_per_ft
            if capacity <= 0:
                continue
            if remaining <= comp.volume_bbl:
                return top_md + remaining / capacity
            remaining -= comp.volume_bbl
        return self.bit_md_ft

    # -- schedules -----------------------------------------------------------

    def drill_pipe_pressure_at(self, front_md: float) -> float:
        """Drill pipe pressure with the kill mud front at a given depth, psi.

        The single source of truth for the schedule: both the step table and
        the segment breakdown are built from this, so they cannot disagree.
        """
        string_volume = self.string_volume_bbl
        volume = self.annulus.string.internal_volume_to(front_md)
        fraction = min(1.0, volume / string_volume) if string_volume else 1.0

        front_tvd = self.survey.tvd_at(front_md)
        hydrostatic = hydrostatic_pressure(
            self.kill_mud_weight_ppg, front_tvd
        ) + hydrostatic_pressure(
            self.mud_weight_ppg, self.bit_tvd_ft - front_tvd
        )
        fcp_friction = self.scr_psi * self.kill_mud_weight_ppg / self.mud_weight_ppg
        friction = self.scr_psi + (fcp_friction - self.scr_psi) * fraction
        return (
            self.formation_pressure_psi
            - hydrostatic
            + friction
            - self.choke_line_friction_psi
        )

    def schedule_segments(self) -> list[ScheduleSegment]:
        """The schedule broken at every point where its slope changes.

        Breaks at two kinds of boundary:

        * **Trajectory** -- the end of the vertical section, the end of the
          build. TVD gained per foot changes across each.
        * **Pipe size** -- every change of drill pipe bore. Volume per foot,
          and therefore feet per stroke, changes across each.

        On a vertical well with a uniform string this returns a single
        segment, which is why the classic one-line kill sheet works there.
        """
        bit_md = self.bit_md_ft
        boundaries = {0.0, bit_md}

        for top, bottom, _ in self.survey.trajectory_sections():
            for depth in (top, bottom):
                if 0.0 < depth < bit_md:
                    boundaries.add(depth)

        size_changes = set(self.annulus.string.size_change_depths())
        for depth in size_changes:
            if 0.0 < depth < bit_md:
                boundaries.add(depth)

        depths = sorted(boundaries)
        segments: list[ScheduleSegment] = []
        for top, bottom in zip(depths, depths[1:]):
            if bottom - top < 1e-6:
                continue
            midpoint = (top + bottom) / 2.0
            section = self.survey.section_at(midpoint)

            reasons = []
            if top in size_changes:
                reasons.append("pipe size change")
            if any(abs(top - b) < 1e-6
                   for _, b, _ in self.survey.trajectory_sections()):
                reasons.append("end of section")
            reason = ", ".join(reasons) if reasons else "start"

            start_volume = self.annulus.string.internal_volume_to(top)
            end_volume = self.annulus.string.internal_volume_to(bottom)

            segments.append(
                ScheduleSegment(
                    name=section,
                    reason=reason,
                    top_md=top,
                    bottom_md=bottom,
                    start_strokes=self.pump.strokes_for(start_volume),
                    end_strokes=self.pump.strokes_for(end_volume),
                    start_pressure_psi=self.drill_pipe_pressure_at(top),
                    end_pressure_psi=self.drill_pipe_pressure_at(bottom),
                )
            )
        return segments

    def format_segments(self) -> str:
        """Render the segment breakdown as a fixed-width table."""
        lines = [
            f"{'Section':<12}{'From MD':>9}{'To MD':>9}{'Strokes':>10}"
            f"{'DP psi':>16}{'psi/100 stk':>13}",
            "-" * 72,
        ]
        for segment in self.schedule_segments():
            arrow = "UP" if segment.pressure_rises else "down"
            lines.append(
                f"{segment.name:<12}{segment.top_md:>9.0f}{segment.bottom_md:>9.0f}"
                f"{segment.strokes:>10.0f}"
                f"{segment.start_pressure_psi:>8.0f}"
                f" -> {segment.end_pressure_psi:<4.0f}"
                f"{segment.slope_psi_per_100_strokes:>9.1f} {arrow}"
            )
        return "\n".join(lines)

    @property
    def rounding_overbalance_psi(self) -> float:
        """Extra bottomhole pressure bought by rounding the kill weight up, psi.

        The mud that gets mixed is heavier than the mud that exactly balances
        the formation, because the kill weight rounds up to a tenth. That
        difference is real overbalance::

            0.052 x (KMW_mixed - KMW_calculated) x TVD

        On the reference well, 10.369 rounds to 10.4 and the well ends up
        16 psi overbalanced. That is the margin the rounding rule exists to
        create.

        It also explains a discrepancy that looks like an error and is not.
        :attr:`final_circulating_pressure_psi` follows the standard formula
        ``SCR x KMW / OMW`` and is the number the driller holds. But the
        pressure that would hold bottomhole pressure *exactly* at formation
        pressure is this much lower -- see :meth:`drill_pipe_pressure_at`.
        Holding FCP keeps the extra margin; that is the intent.
        """
        return hydrostatic_pressure(
            self.kill_mud_weight_ppg - self.kill_mud_weight_exact_ppg,
            self.bit_tvd_ft,
        )

    @property
    def balanced_final_pressure_psi(self) -> float:
        """Drill pipe pressure holding bottomhole pressure exactly at Pf, psi.

        Lower than :attr:`final_circulating_pressure_psi` by
        :attr:`rounding_overbalance_psi`. Shown for completeness -- the number
        to work to is FCP.
        """
        return self.drill_pipe_pressure_at(self.bit_md_ft)

    @property
    def pressure_step_psi(self) -> int:
        """Pressure taken off per step of the schedule, psi.

        **Rounded down.** A schedule spanning 516 psi over ten steps is worked
        as 51 psi per step, not 51.6. Rounding up would take drill pipe
        pressure -- and with it bottomhole pressure -- down faster than
        intended, eating into the overbalance a little on every step.

        The cost is that ten steps of 51 psi come to 510, not 516, so the
        schedule lands 6 psi above FCP. Slightly more pressure on the well than
        planned is the right way for that error to fall.
        """
        return self.pressure_step_for(10)

    def pressure_step_for(self, steps: int) -> int:
        """Pressure per step for a schedule of a given number of steps, psi."""
        if steps < 1:
            raise ValueError("Need at least one step")
        span = (
            self.initial_circulating_pressure_psi
            - self.final_circulating_pressure_psi
        )
        return rounding.pressure_step(span / steps)

    def strokes_step_for(self, steps: int) -> int:
        """Strokes per step for a schedule of a given number of steps."""
        if steps < 1:
            raise ValueError("Need at least one step")
        return rounding.strokes(self.strokes_to_bit / steps)

    def schedule_linear(self, steps: int = 10) -> list[ScheduleStep]:
        """The classic straight-line schedule, as printed on a paper kill sheet.

        Comes down from ICP in whole-psi steps, each rounded **down**, over the
        strokes to the bit. This is what crews use and what is drilled in
        training. It is exact for a vertical well with a uniform string, and
        close enough for most others.

        Because the step is floored, the steps do not land exactly on FCP --
        they finish slightly above it. The final row is set to FCP, which is
        the number to hold once kill mud is at the bit.

        Compare against :meth:`schedule_by_depth` to see how much the
        straight-line approximation costs on this particular well.
        """
        if steps < 1:
            raise ValueError("Need at least one step")
        icp = self.initial_circulating_pressure_psi
        fcp = self.final_circulating_pressure_psi
        step_psi = self.pressure_step_for(steps)
        step_strokes = self.strokes_step_for(steps)

        out: list[ScheduleStep] = []
        for i in range(steps + 1):
            last = i == steps
            strokes = (
                float(rounding.strokes(self.strokes_to_bit))
                if last else float(step_strokes * i)
            )
            volume = self.pump.volume_for(strokes)
            out.append(
                ScheduleStep(
                    strokes=strokes,
                    drill_pipe_pressure_psi=(
                        float(rounding.pressure(fcp)) if last
                        else float(rounding.pressure(icp) - step_psi * i)
                    ),
                    volume_bbl=volume,
                    kill_mud_md_ft=self.kill_mud_depth_at_volume(volume),
                    note="Kill mud at the bit" if last else "",
                )
            )
        return out

    def schedule_by_depth(self, steps: int = 10) -> list[ScheduleStep]:
        """A depth-accurate schedule.

        Instead of interpolating pressure against strokes, this tracks where
        the kill mud front actually is, converts that MD to TVD, and computes
        the drill pipe pressure that holds bottomhole pressure constant::

            P_dp = Pf - [0.052 x KMW x TVD_front
                         + 0.052 x OMW x (TVD_bit - TVD_front)]
                      + friction

        Friction is interpolated linearly from SCR to FCP with the fraction of
        the string displaced.

        This matters on two kinds of well:

        * **Deviated wells**, where TVD is not proportional to MD, so equal
          stroke increments do not buy equal hydrostatic.
        * **Wells with large-bore collars or a tapered string**, where equal
          stroke increments do not buy equal depth.

        On a vertical well with a uniform string it reduces to the straight
        line and the two schedules agree in shape.

        **The final value is below FCP**, by
        :attr:`rounding_overbalance_psi`. That is not an error: this schedule
        holds bottomhole pressure exactly at formation pressure, while FCP is
        computed from the rounded-up kill weight and therefore carries extra
        margin. Work to FCP; the difference is the margin the rounding buys.
        """
        if steps < 1:
            raise ValueError("Need at least one step")

        pf = self.formation_pressure_psi
        kmw = self.kill_mud_weight_ppg
        omw = self.mud_weight_ppg
        bit_tvd = self.bit_tvd_ft
        scr = self.scr_psi
        fcp_friction = self.scr_psi * kmw / omw
        string_volume = self.string_volume_bbl

        out: list[ScheduleStep] = []
        for i in range(steps + 1):
            fraction = i / steps
            volume = string_volume * fraction
            strokes = self.pump.strokes_for(volume)
            front_md = self.kill_mud_depth_at_volume(volume)
            front_tvd = self.survey.tvd_at(front_md)

            hydrostatic = hydrostatic_pressure(kmw, front_tvd) + hydrostatic_pressure(
                omw, bit_tvd - front_tvd
            )
            friction = scr + (fcp_friction - scr) * fraction
            pressure = pf - hydrostatic + friction - self.choke_line_friction_psi

            out.append(
                ScheduleStep(
                    strokes=float(rounding.strokes(strokes)),
                    drill_pipe_pressure_psi=float(rounding.pressure(pressure)),
                    volume_bbl=volume,
                    kill_mud_md_ft=front_md,
                    note="Kill mud at the bit" if i == steps else "",
                )
            )
        return out

    # -- methods -------------------------------------------------------------

    def wait_and_weight(self, steps: int = 10) -> list[Stage]:
        """The Wait and Weight method (also: Engineer's Method, One Circulation).

        Weight the mud up **before** circulating, then kill the well in a
        single circulation. Kill mud goes down the string while the influx
        comes up the annulus.

        Advantages: one circulation, and because the heavier mud reaches the
        annulus sooner, the pressure the casing shoe sees is generally lower
        than with the Driller's Method.

        Disadvantages: the well sits shut in while the mud is weighted up, and
        if gas is migrating that wait is not free. It also needs the mud system
        to be able to weight up promptly, and demands more of the crew.
        """
        return [
            Stage(
                name="Weight up",
                strokes=0.0,
                description=(
                    f"Well shut in. Raise mud weight from {self.mud_weight_ppg:.1f} "
                    f"to {self.kill_mud_weight_ppg:.1f} ppg. Watch for pressure "
                    "rise from gas migration while waiting."
                ),
            ),
            Stage(
                name="Circulate to bit",
                strokes=self.strokes_to_bit,
                description=(
                    f"Bring the pump to kill rate holding casing pressure "
                    f"constant, then follow the drill pipe schedule down from "
                    f"{self.initial_circulating_pressure_psi:.0f} psi to "
                    f"{self.final_circulating_pressure_psi:.0f} psi."
                ),
                schedule=self.schedule_by_depth(steps),
            ),
            Stage(
                name="Circulate to surface",
                strokes=self.strokes_bit_to_surface,
                description=(
                    f"Hold drill pipe pressure constant at "
                    f"{self.final_circulating_pressure_psi:.0f} psi until kill "
                    "mud returns at surface. The influx reaches surface at "
                    f"{self.strokes_bit_to_surface:.0f} strokes from the start "
                    "of pumping."
                ),
            ),
        ]

    def drillers_method(self, steps: int = 10) -> list[Stage]:
        """The Driller's Method (also: Two Circulation, Wait and Weight's rival).

        First circulation removes the influx using the original mud. Then
        weight up, and a second circulation replaces the mud with kill mud.

        Advantages: starts immediately with no wait, needs no mud mixing before
        the influx is out, and is simpler to execute under pressure -- the
        first circulation is just "hold the drill pipe pressure at ICP".

        Disadvantages: two circulations means longer exposure, and the casing
        shoe sees higher pressure for longer because the annulus still holds
        original-weight mud while the influx is being circulated out.
        """
        icp = self.initial_circulating_pressure_psi
        fcp = self.final_circulating_pressure_psi
        return [
            Stage(
                name="First circulation - remove the influx",
                strokes=self.strokes_bit_to_surface,
                description=(
                    f"Circulate at kill rate with the original "
                    f"{self.mud_weight_ppg:.1f} ppg mud. Hold drill pipe "
                    f"pressure constant at {icp:.0f} psi throughout. The influx "
                    f"reaches surface after {self.strokes_bit_to_surface:.0f} "
                    "strokes. Casing pressure will rise as gas expands near "
                    "surface -- that is expected; keep the drill pipe gauge on "
                    "its number."
                ),
            ),
            Stage(
                name="Weight up",
                strokes=0.0,
                description=(
                    f"Shut in. SIDPP and SICP should now be equal (the influx is "
                    f"gone, so both sides read through the same mud). Raise mud "
                    f"weight from {self.mud_weight_ppg:.1f} to "
                    f"{self.kill_mud_weight_ppg:.1f} ppg."
                ),
            ),
            Stage(
                name="Second circulation - displace to kill mud",
                strokes=self.strokes_to_bit,
                description=(
                    f"Follow the drill pipe schedule from {icp:.0f} psi down to "
                    f"{fcp:.0f} psi as kill mud goes to the bit."
                ),
                schedule=self.schedule_by_depth(steps),
            ),
            Stage(
                name="Second circulation - kill mud to surface",
                strokes=self.strokes_bit_to_surface,
                description=(
                    f"Hold drill pipe pressure at {fcp:.0f} psi until kill mud "
                    "returns at surface. Casing pressure should fall to zero. "
                    "Shut down, check for flow."
                ),
            ),
        ]

    # -- reporting -----------------------------------------------------------

    def summary(self) -> dict[str, float]:
        """The headline kill sheet numbers, rounded the way they are used.

        Kill mud weight up to a tenth, pressures to whole psi, strokes to
        whole numbers. The unrounded kill mud weight is included so the
        working can be checked.
        """
        return {
            "Original mud weight (ppg)": round(self.mud_weight_ppg, 2),
            "Kill mud weight, calculated (ppg)": round(
                self.kill_mud_weight_exact_ppg, 3
            ),
            "Kill mud weight, as mixed (ppg)": self.kill_mud_weight_ppg,
            "Formation pressure (psi)": rounding.pressure(
                self.formation_pressure_psi
            ),
            "Bit TVD (ft)": round(self.bit_tvd_ft, 0),
            "Bit MD (ft)": round(self.bit_md_ft, 0),
            "SCR at kill rate (psi)": rounding.pressure(self.scr_psi),
            "ICP (psi)": rounding.pressure(
                self.initial_circulating_pressure_psi
            ),
            "FCP (psi)": rounding.pressure(self.final_circulating_pressure_psi),
            "Pressure per step, 10 steps (psi)": self.pressure_step_psi,
            "String volume (bbl)": rounding.volume(self.string_volume_bbl),
            "Annulus volume (bbl)": rounding.volume(self.annulus_volume_bbl),
            "Strokes to bit": rounding.strokes(self.strokes_to_bit),
            "Strokes bit to surface": rounding.strokes(
                self.strokes_bit_to_surface
            ),
            "Total strokes": rounding.strokes(self.total_strokes),
        }

    def format_schedule(self, schedule: list[ScheduleStep]) -> str:
        """Render a schedule as a fixed-width table for printing."""
        lines = [
            f"{'Strokes':>9} {'Volume bbl':>11} {'Kill mud MD':>12} {'DP psi':>9}  Note",
            "-" * 60,
        ]
        for step in schedule:
            lines.append(
                f"{step.strokes:9.0f} {step.volume_bbl:11.1f} "
                f"{step.kill_mud_md_ft:12.0f} {step.drill_pipe_pressure_psi:9.0f}  "
                f"{step.note}"
            )
        return "\n".join(lines)
