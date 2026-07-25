"""Shared framework for every kill method.

A kill method takes a :class:`WellState` -- the well, the string, the pump, and
the three shut-in readings -- and returns a :class:`KillPlan`: an applicability
verdict, a set of headline numbers, an ordered list of stages with actions, and
a :class:`TracePoint` series suitable for plotting.

The framework carries two ideas worth stating explicitly.

**Applicability is part of the answer.** Not every method works on every well.
Volumetric and lube-and-bleed depend on gas migrating upward, and gas in a
horizontal lateral has no upward direction to migrate in. Rather than returning
plausible-looking numbers for a procedure that would stall on the rig, methods
return blockers and warnings alongside their results.

**Pressures come from a fluid column, not a formula.** During a kill the annulus
holds several fluids at once -- kill mud at the bottom, original mud, an influx,
more original mud above. :class:`FluidColumn` models that stack explicitly and
computes pressure at any depth from it. That is what makes the shoe pressure
plot trustworthy: it is not a correction applied to a surface reading, it is the
actual pressure at the shoe given what is actually in the hole.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from ..geometry import Annulus, Pump
from ..killsheet import KillSheet, SlowCirculatingRate
from ..subsea import SubseaGeometry
from ..survey import Survey
from ..units import PSI_PER_PPG_FT
from ..wellconfig import WellConfiguration

#: Planning gradient for a gas influx when its density cannot be resolved.
DEFAULT_GAS_GRADIENT: float = 0.1


# --------------------------------------------------------------------------
# Fluid column
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Zone:
    """A slice of the annulus occupied by one fluid.

    Depths are measured. The vertical extent is resolved through the survey, so
    a zone lying in a horizontal lateral contributes no hydrostatic.
    """

    top_md: float
    bottom_md: float
    density_ppg: float
    label: str = ""

    @property
    def length_md_ft(self) -> float:
        return max(0.0, self.bottom_md - self.top_md)


class FluidColumn:
    """A stack of fluid zones, from surface down.

    Zones are given in any order and sorted on construction. Gaps are not
    checked -- callers build these from cumulative volumes, so they are
    contiguous by construction.
    """

    def __init__(self, zones: list[Zone], survey: Survey):
        self.zones = sorted((z for z in zones if z.length_md_ft > 1e-9),
                            key=lambda z: z.top_md)
        self.survey = survey

    def hydrostatic_to(self, md: float) -> float:
        """Hydrostatic pressure of everything above a measured depth, psi."""
        total = 0.0
        for zone in self.zones:
            if zone.top_md >= md:
                break
            bottom = min(zone.bottom_md, md)
            vertical = self.survey.tvd_at(bottom) - self.survey.tvd_at(zone.top_md)
            total += PSI_PER_PPG_FT * zone.density_ppg * vertical
        return total

    @property
    def total_hydrostatic(self) -> float:
        if not self.zones:
            return 0.0
        return self.hydrostatic_to(self.zones[-1].bottom_md)

    def surface_pressure_for_bottomhole(self, target_bhp_psi: float) -> float:
        """Surface pressure that puts a given pressure at the bottom, psi.

        This is how casing pressure is derived throughout: hold bottomhole
        pressure at the formation pressure, and whatever the fluid column does
        not supply must show at surface.
        """
        return target_bhp_psi - self.total_hydrostatic

    def pressure_at(self, md: float, surface_pressure_psi: float) -> float:
        """Pressure at a measured depth given a surface pressure, psi."""
        return surface_pressure_psi + self.hydrostatic_to(md)

    def describe(self) -> list[str]:
        return [
            f"{z.label or 'fluid'}: {z.top_md:.0f}-{z.bottom_md:.0f} ft MD "
            f"@ {z.density_ppg:.2f} ppg"
            for z in self.zones
        ]


# --------------------------------------------------------------------------
# Well state
# --------------------------------------------------------------------------

@dataclass
class WellState:
    """Everything a kill method needs to know.

    Args:
        annulus: Wellbore and drill string geometry.
        survey: Directional survey, for MD/TVD conversion.
        pump: The pump being used to kill.
        mud_weight_ppg: Original mud weight in the hole.
        slow_circulating_rate: Measured SCR at kill rate.
        configuration: BOP location and trajectory.
        sidpp_psi: Shut-in drill pipe pressure.
        sicp_psi: Shut-in casing pressure.
        pit_gain_bbl: Influx volume.
        frac_gradient_ppg: Formation strength at the shoe, ppg EMW.
        shoe_md_ft: Casing shoe, MD. Defaults to the wellbore's deepest shoe.
        subsea: Water depth and air gap, for a subsea stack.
        choke_line_friction_psi: Measured choke line friction at kill rate.
        safety_factor_ppg: Extra weight added to the kill mud.
        influx_gradient_override: Force an influx gradient rather than deriving
            it from the shut-in pressures.
    """

    annulus: Annulus
    survey: Survey
    pump: Pump
    mud_weight_ppg: float
    slow_circulating_rate: SlowCirculatingRate
    configuration: WellConfiguration
    sidpp_psi: float
    sicp_psi: float
    pit_gain_bbl: float
    frac_gradient_ppg: float | None = None
    shoe_md_ft: float | None = None
    subsea: SubseaGeometry | None = None
    choke_line_friction_psi: float = 0.0
    safety_factor_ppg: float = 0.0
    influx_gradient_override: float | None = None
    #: Nominal drill pipe weight in air, lb/ft. Used by stripping for the
    #: balance point between pipe weight and well pressure.
    pipe_weight_lb_per_ft: float = 19.5
    #: Length of one stand, ft. 93 ft for triples, 63 ft for doubles.
    stand_length_ft: float = 93.0
    #: Measured gas migration rate, ft/hr. Zero means "not migrating".
    gas_migration_rate_ft_per_hr: float = 0.0

    # -- depths --------------------------------------------------------------

    @property
    def bit_md_ft(self) -> float:
        return self.annulus.string.bit_depth_md

    @property
    def bit_tvd_ft(self) -> float:
        return self.survey.tvd_at(self.bit_md_ft)

    @property
    def hole_md_ft(self) -> float:
        return self.annulus.wellbore.total_depth_md

    @property
    def hole_tvd_ft(self) -> float:
        return self.survey.tvd_at(self.hole_md_ft)

    @property
    def shoe_md(self) -> float | None:
        if self.shoe_md_ft is not None:
            return self.shoe_md_ft
        try:
            return self.annulus.wellbore.shoe_md
        except ValueError:
            return None

    @property
    def shoe_tvd_ft(self) -> float | None:
        shoe = self.shoe_md
        return None if shoe is None else self.survey.tvd_at(shoe)

    # -- pressures -----------------------------------------------------------

    @property
    def hydrostatic_below_bit_psi(self) -> float:
        """Hydrostatic between the bit and total depth, psi.

        Zero when the bit is on bottom, which is the usual case and the one
        every kill sheet assumes.

        **Off bottom it is not zero, and ignoring it is an error.** The drill
        pipe gauge reads the pressure at the *bit*, not at the formation. When
        the bit has been pulled up, the formation is deeper, and whatever sits
        between the two adds its own hydrostatic. That interval usually holds
        the influx -- which contributes far less than mud would -- so the gap
        is real but smaller than a mud column of the same height.
        """
        if self.bit_md_ft >= self.hole_md_ft - 1e-6:
            return 0.0

        influx_top = self.influx_top_md_ft
        gradient = self.influx_gradient_psi_per_ft
        mud_gradient = PSI_PER_PPG_FT * self.mud_weight_ppg
        bit_tvd = self.bit_tvd_ft
        hole_tvd = self.hole_tvd_ft

        if influx_top <= self.bit_md_ft:
            # The influx reaches above the bit; everything below it is influx.
            return gradient * (hole_tvd - bit_tvd)

        influx_top_tvd = self.survey.tvd_at(influx_top)
        return (
            mud_gradient * (influx_top_tvd - bit_tvd)
            + gradient * (hole_tvd - influx_top_tvd)
        )

    @property
    def formation_pressure_psi(self) -> float:
        """Pore pressure at total depth, psi.

        Read up the drill pipe through clean mud to the bit, then down through
        whatever lies between the bit and the formation::

            Pf = SIDPP + 0.052 x MW x TVD_bit + hydrostatic below the bit

        The last term vanishes when the bit is on bottom.
        """
        return (
            self.sidpp_psi
            + PSI_PER_PPG_FT * self.mud_weight_ppg * self.bit_tvd_ft
            + self.hydrostatic_below_bit_psi
        )

    @property
    def kill_mud_weight_ppg(self) -> float:
        return (
            self.mud_weight_ppg
            + self.sidpp_psi / (PSI_PER_PPG_FT * self.bit_tvd_ft)
            + self.safety_factor_ppg
        )

    @property
    def frac_pressure_psi(self) -> float | None:
        if self.frac_gradient_ppg is None or self.shoe_tvd_ft is None:
            return None
        return PSI_PER_PPG_FT * self.frac_gradient_ppg * self.shoe_tvd_ft

    def maasp_psi(self, mud_weight_ppg: float | None = None) -> float | None:
        """MAASP for a mud weight, defaulting to the mud currently in the hole."""
        if self.frac_gradient_ppg is None or self.shoe_tvd_ft is None:
            return None
        weight = self.mud_weight_ppg if mud_weight_ppg is None else mud_weight_ppg
        return PSI_PER_PPG_FT * (self.frac_gradient_ppg - weight) * self.shoe_tvd_ft

    # -- influx --------------------------------------------------------------

    @property
    def influx_height_md_ft(self) -> float:
        return self.annulus.height_of_volume_from_bottom(self.pit_gain_bbl)

    @property
    def influx_top_md_ft(self) -> float:
        return self.hole_md_ft - self.influx_height_md_ft

    @property
    def influx_height_tvd_ft(self) -> float:
        return self.survey.vertical_height_of(self.influx_top_md_ft, self.hole_md_ft)

    @property
    def influx_gradient_resolved(self) -> tuple[float, bool]:
        """Influx gradient and whether it was measured rather than assumed.

        Returns ``(gradient_psi_per_ft, was_measured)``. When the influx has no
        vertical height -- an influx lying in a lateral -- its density cannot be
        recovered from the shut-in pressures, and the planning value for gas is
        used instead.
        """
        if self.influx_gradient_override is not None:
            return self.influx_gradient_override, False

        height = self.influx_height_tvd_ft
        if height < 1.0:
            return DEFAULT_GAS_GRADIENT, False

        gradient = (
            PSI_PER_PPG_FT * self.mud_weight_ppg
            - (self.sicp_psi - self.sidpp_psi) / height
        )
        if not 0.0 < gradient < PSI_PER_PPG_FT * self.mud_weight_ppg:
            return DEFAULT_GAS_GRADIENT, False
        return gradient, True

    @property
    def influx_gradient_psi_per_ft(self) -> float:
        return self.influx_gradient_resolved[0]

    @property
    def influx_density_ppg(self) -> float:
        return self.influx_gradient_psi_per_ft / PSI_PER_PPG_FT

    # -- derived helpers -----------------------------------------------------

    @property
    def kill_sheet(self) -> KillSheet:
        """The conventional kill sheet numbers for this well."""
        return KillSheet(
            sidpp_psi=self.sidpp_psi,
            sicp_psi=self.sicp_psi,
            pit_gain_bbl=self.pit_gain_bbl,
            mud_weight_ppg=self.mud_weight_ppg,
            annulus=self.annulus,
            survey=self.survey,
            pump=self.pump,
            slow_circulating_rate=self.slow_circulating_rate,
            safety_factor_ppg=self.safety_factor_ppg,
            choke_line_friction_psi=self.effective_choke_line_friction,
        )

    @property
    def effective_choke_line_friction(self) -> float:
        """Choke line friction, forced to zero on a surface stack."""
        return self.choke_line_friction_psi if self.configuration.is_subsea else 0.0

    def annulus_md_at_volume_from_bottom(self, volume_bbl: float) -> float:
        """MD of the top of a volume measured up from total depth, clamped.

        Returns 0.0 (surface) once the volume exceeds the annulus.
        """
        if volume_bbl <= 0:
            return self.hole_md_ft
        if volume_bbl >= self.annulus.volume_bbl:
            return 0.0
        return self.annulus.top_of_volume_from_bottom(volume_bbl)

    def annulus_md_at_volume_from_surface(self, volume_bbl: float) -> float:
        """MD reached by a volume measured down from surface, clamped."""
        remaining = self.annulus.volume_bbl - max(0.0, volume_bbl)
        return self.annulus_md_at_volume_from_bottom(remaining)

    def string_md_at_volume_from_bit(self, volume_bbl: float) -> float:
        """MD of a point in the string, measured as a volume up from the bit.

        Used by reverse circulation, where returns travel up the inside of the
        string rather than up the annulus.
        """
        string_volume = self.annulus.string.internal_volume_bbl
        from_surface = string_volume - max(0.0, min(volume_bbl, string_volume))
        return self.kill_sheet.kill_mud_depth_at_volume(from_surface)


# --------------------------------------------------------------------------
# Plan structures
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class TracePoint:
    """One sample of a kill in progress, for plotting.

    ``x`` is progress in whatever unit the plan declares -- strokes for a
    circulating kill, cycle number for volumetric, barrels pumped for a
    bullhead.
    """

    x: float
    stage: str
    drill_pipe_psi: float | None = None
    casing_psi: float | None = None
    shoe_psi: float | None = None
    influx_volume_bbl: float | None = None
    influx_top_md_ft: float | None = None
    influx_bottom_md_ft: float | None = None
    #: Bit depth, for operations that move pipe rather than circulate.
    pipe_depth_md_ft: float | None = None
    note: str = ""


@dataclass(frozen=True)
class KillStage:
    """One stage of a procedure: what to do, and the numbers that go with it."""

    name: str
    description: str
    actions: list[str] = field(default_factory=list)
    table: list[dict[str, object]] = field(default_factory=list)
    strokes: float | None = None


@dataclass
class Applicability:
    """Whether a method can be used on this well, and what to watch out for.

    ``blockers`` mean the method should not be attempted as described.
    ``warnings`` mean it can be, with care.
    """

    usable: bool = True
    blockers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def block(self, reason: str) -> None:
        self.usable = False
        self.blockers.append(reason)

    def warn(self, reason: str) -> None:
        self.warnings.append(reason)


@dataclass
class KillPlan:
    """The complete output of a kill method."""

    method_key: str
    method_name: str
    configuration: WellConfiguration
    applicability: Applicability
    summary: dict[str, object] = field(default_factory=dict)
    stages: list[KillStage] = field(default_factory=list)
    trace: list[TracePoint] = field(default_factory=list)
    x_label: str = "Pump strokes"
    notes: list[str] = field(default_factory=list)
    #: Fracture pressure at the shoe, for the limit line on the shoe plot.
    shoe_frac_pressure_psi: float | None = None
    #: MAASP at the kill mud weight, for the limit line on the casing plot.
    maasp_psi: float | None = None
    #: Casing shoe MD, for the marker on the influx position plot.
    shoe_md_ft: float | None = None

    @property
    def peak_shoe_pressure_psi(self) -> float | None:
        values = [p.shoe_psi for p in self.trace if p.shoe_psi is not None]
        return max(values) if values else None

    @property
    def peak_casing_pressure_psi(self) -> float | None:
        values = [p.casing_psi for p in self.trace if p.casing_psi is not None]
        return max(values) if values else None

    def format_summary(self) -> str:
        return "\n".join(f"{k:.<44} {v}" for k, v in self.summary.items())


# --------------------------------------------------------------------------
# Method contract
# --------------------------------------------------------------------------

class KillMethod(ABC):
    """Base class for a kill method.

    Subclasses set the class attributes and implement :meth:`plan`. The default
    :meth:`applicability` handles the checks common to all methods; subclasses
    call ``super().applicability(well)`` and add their own.
    """

    key: str = ""
    name: str = ""
    summary: str = ""

    #: Whether the method circulates the well.
    circulates: bool = True
    #: Whether the method depends on gas migrating up the annulus.
    requires_migration: bool = False
    #: Whether the method requires the influx to have reached surface.
    requires_gas_at_surface: bool = False

    def applicability(self, well: WellState) -> Applicability:
        """Checks that apply to every method on every well."""
        result = Applicability()

        if self.requires_migration and not well.configuration.trajectory.migration_reliable:
            result.warn(
                "This method relies on gas migrating up the annulus. In a "
                "horizontal lateral gas has no upward direction to migrate in, "
                "so it will not move on its own. The method only starts working "
                "once the influx has reached the build section, and it cannot "
                "move the influx out of the lateral in the first place."
            )

        if well.configuration.is_subsea and well.choke_line_friction_psi <= 0:
            result.warn(
                "No choke line friction has been entered for a subsea stack. "
                "Circulating pressures will be over-stated and the formation "
                "over-pressured by the amount of the friction. Measure it "
                "before relying on these numbers."
            )

        if well.configuration.is_horizontal:
            _, measured = well.influx_gradient_resolved
            if not measured:
                result.warn(
                    "The influx density could not be resolved from the shut-in "
                    f"pressures, so {DEFAULT_GAS_GRADIENT} psi/ft has been "
                    "assumed for gas. This is normal for an influx in a lateral."
                )

        if well.frac_gradient_ppg is None:
            result.warn(
                "No fracture gradient supplied, so shoe pressure cannot be "
                "checked against the formation strength. The shoe plot will be "
                "produced without a limit line."
            )

        if self.circulates and well.slow_circulating_rate.pressure_psi <= 0:
            result.block(
                "No slow circulating rate pressure. It cannot be measured with "
                "a kick in the hole, and a circulating kill cannot be planned "
                "without it."
            )

        return result

    @abstractmethod
    def plan(self, well: WellState) -> KillPlan:
        """Produce the full plan for this well."""

    # -- helpers for subclasses ---------------------------------------------

    def _new_plan(self, well: WellState, **kwargs) -> KillPlan:
        kwargs.setdefault("shoe_frac_pressure_psi", well.frac_pressure_psi)
        kwargs.setdefault(
            "maasp_psi", well.maasp_psi(well.kill_mud_weight_ppg)
        )
        kwargs.setdefault("shoe_md_ft", well.shoe_md)
        return KillPlan(
            method_key=self.key,
            method_name=self.name,
            configuration=well.configuration,
            applicability=self.applicability(well),
            **kwargs,
        )
