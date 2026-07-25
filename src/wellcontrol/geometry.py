"""Wellbore geometry: capacities, volumes, displacements and pump strokes.

Every volume in well control reduces to one constant::

    capacity (bbl/ft) = ID(in)^2 / 1029.4

That 1029.4 is just unit bookkeeping: a cylinder of diameter D inches and
length 1 ft has a volume of (pi/4) * D^2 * 12 cubic inches, and there are 9702
cubic inches in a 42-gallon barrel, so (pi/4 * 12) / 9702 = 1 / 1029.4.

For an annulus, subtract the pipe that occupies the space::

    annular capacity (bbl/ft) = (hole ID^2 - pipe OD^2) / 1029.4

Volumes drive **strokes**, and strokes are how a driller measures position
during a kill. Knowing that the influx is "300 strokes from surface" is the
only way to anticipate what the choke is about to do.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .units import CAPACITY_CONSTANT


# --------------------------------------------------------------------------
# Primitive capacity helpers
# --------------------------------------------------------------------------

def capacity_bbl_per_ft(id_in: float) -> float:
    """Internal capacity of a cylinder, bbl/ft."""
    if id_in < 0:
        raise ValueError("Diameter cannot be negative")
    return id_in ** 2 / CAPACITY_CONSTANT


def annular_capacity_bbl_per_ft(hole_id_in: float, pipe_od_in: float) -> float:
    """Capacity of the annulus between a hole and the pipe inside it, bbl/ft."""
    if pipe_od_in > hole_id_in:
        raise ValueError(
            f"Pipe OD ({pipe_od_in} in) is larger than hole ID ({hole_id_in} in)"
        )
    return (hole_id_in ** 2 - pipe_od_in ** 2) / CAPACITY_CONSTANT


def metal_displacement_bbl_per_ft(od_in: float, id_in: float) -> float:
    """Steel volume of a tubular, bbl/ft.

    This is what the pipe displaces when run **open-ended** (mud flows freely
    up the bore), and what governs the trip tank volume when tripping.
    """
    if id_in > od_in:
        raise ValueError(f"ID ({id_in} in) is larger than OD ({od_in} in)")
    return (od_in ** 2 - id_in ** 2) / CAPACITY_CONSTANT


def closed_end_displacement_bbl_per_ft(od_in: float) -> float:
    """Displacement of a tubular run with a float or plugged bit, bbl/ft.

    A string with a float sub does not fill as it is run, so it displaces its
    full outside volume, not just the steel. Tripping in on a float and
    monitoring against open-ended figures will make the well look like it is
    flowing when it is not -- and mask a real influx when it is.
    """
    return od_in ** 2 / CAPACITY_CONSTANT


# --------------------------------------------------------------------------
# Components
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Pipe:
    """One tubular component of the drill string.

    Attributes:
        name: Label, e.g. "5in Drill Pipe" or "8in Drill Collars".
        od_in: Outside diameter, inches.
        id_in: Inside diameter, inches.
        length_ft: Measured length, ft.
    """

    name: str
    od_in: float
    id_in: float
    length_ft: float

    def __post_init__(self) -> None:
        if self.id_in > self.od_in:
            raise ValueError(f"{self.name}: ID {self.id_in} exceeds OD {self.od_in}")
        if self.length_ft < 0:
            raise ValueError(f"{self.name}: negative length")

    @property
    def capacity_bbl_per_ft(self) -> float:
        return capacity_bbl_per_ft(self.id_in)

    @property
    def volume_bbl(self) -> float:
        """Internal volume of this component, bbl."""
        return self.capacity_bbl_per_ft * self.length_ft

    @property
    def metal_displacement_bbl_per_ft(self) -> float:
        return metal_displacement_bbl_per_ft(self.od_in, self.id_in)

    @property
    def closed_end_displacement_bbl_per_ft(self) -> float:
        return closed_end_displacement_bbl_per_ft(self.od_in)


@dataclass(frozen=True)
class HoleSection:
    """A cased or open-hole interval, defined by measured depth.

    Attributes:
        name: Label, e.g. "9-5/8in Casing" or "8-1/2in Open Hole".
        id_in: Drift/inside diameter for casing, or bit size for open hole.
        top_md: Top of the section, MD ft.
        bottom_md: Bottom of the section, MD ft.
        is_open_hole: True for open hole, False for cased.
    """

    name: str
    id_in: float
    top_md: float
    bottom_md: float
    is_open_hole: bool = False

    def __post_init__(self) -> None:
        if self.bottom_md <= self.top_md:
            raise ValueError(f"{self.name}: bottom MD must be below top MD")

    @property
    def length_ft(self) -> float:
        return self.bottom_md - self.top_md


@dataclass(frozen=True)
class AnnularInterval:
    """A depth interval of the annulus with constant geometry."""

    top_md: float
    bottom_md: float
    hole_id_in: float
    pipe_od_in: float
    description: str = ""

    @property
    def length_ft(self) -> float:
        return self.bottom_md - self.top_md

    @property
    def capacity_bbl_per_ft(self) -> float:
        return annular_capacity_bbl_per_ft(self.hole_id_in, self.pipe_od_in)

    @property
    def volume_bbl(self) -> float:
        return self.capacity_bbl_per_ft * self.length_ft


# --------------------------------------------------------------------------
# Drill string
# --------------------------------------------------------------------------

@dataclass
class DrillString:
    """A drill string, described from the bit upward.

    ``components[0]`` is the deepest item (bit sub / collars) and the list runs
    up toward surface. The string is assumed to reach surface, so the total
    length of the components must equal the bit depth.

    Use :meth:`from_bha` to avoid computing the drill pipe length by hand.
    """

    components: list[Pipe]
    bit_depth_md: float

    def __post_init__(self) -> None:
        if not self.components:
            raise ValueError("Drill string has no components")
        total = sum(c.length_ft for c in self.components)
        if abs(total - self.bit_depth_md) > 1.0:
            raise ValueError(
                f"Drill string length ({total:.1f} ft) does not reach the bit "
                f"depth ({self.bit_depth_md:.1f} ft). Difference "
                f"{self.bit_depth_md - total:+.1f} ft. Use DrillString.from_bha() "
                "to have the drill pipe length computed automatically."
            )

    @classmethod
    def from_bha(
        cls, bha: list[Pipe], drill_pipe: Pipe, bit_depth_md: float
    ) -> "DrillString":
        """Build a string from a BHA plus enough drill pipe to reach surface.

        Args:
            bha: BHA components from the bottom up. Lengths are taken as given.
            drill_pipe: Drill pipe spec. Its ``length_ft`` is ignored and
                recomputed to fill the remaining hole.
            bit_depth_md: Bit depth, MD ft.
        """
        bha_length = sum(c.length_ft for c in bha)
        dp_length = bit_depth_md - bha_length
        if dp_length < 0:
            raise ValueError(
                f"BHA length ({bha_length:.1f} ft) exceeds bit depth "
                f"({bit_depth_md:.1f} ft)"
            )
        joint = Pipe(
            name=drill_pipe.name,
            od_in=drill_pipe.od_in,
            id_in=drill_pipe.id_in,
            length_ft=dp_length,
        )
        return cls(components=list(bha) + [joint], bit_depth_md=bit_depth_md)

    def intervals(self) -> list[tuple[float, float, Pipe]]:
        """Depth ranges of each component as ``(top_md, bottom_md, pipe)``."""
        out: list[tuple[float, float, Pipe]] = []
        bottom = self.bit_depth_md
        for comp in self.components:
            top = bottom - comp.length_ft
            out.append((top, bottom, comp))
            bottom = top
        out.reverse()
        return out

    @property
    def internal_volume_bbl(self) -> float:
        """Total volume inside the string, surface to bit, bbl."""
        return sum(c.volume_bbl for c in self.components)

    def internal_volume_to(self, md: float) -> float:
        """Volume inside the string from surface down to a measured depth, bbl.

        The inverse of finding a depth from a pumped volume. Used to convert a
        depth of interest -- a casing shoe, a change of pipe size, the end of
        the build -- into the stroke count at which the kill mud front reaches
        it.
        """
        total = 0.0
        for top, bottom, comp in self.intervals():
            if md <= top:
                break
            covered = min(md, bottom) - top
            total += comp.capacity_bbl_per_ft * covered
        return total

    def size_change_depths(self) -> list[float]:
        """Measured depths where the string's bore or outside diameter changes.

        Each is a break in the kill schedule: above and below it, a stroke of
        the pump moves the kill mud front a different distance.
        """
        depths: list[float] = []
        for (_, bottom, upper), (_, _, lower) in zip(
            self.intervals(), self.intervals()[1:]
        ):
            if (
                abs(upper.id_in - lower.id_in) > 1e-9
                or abs(upper.od_in - lower.od_in) > 1e-9
            ):
                depths.append(bottom)
        return depths

    def pipe_od_at(self, md: float) -> float:
        """Outside diameter of the string at a measured depth."""
        for top, bottom, comp in self.intervals():
            if top - 1e-9 <= md <= bottom + 1e-9:
                return comp.od_in
        raise ValueError(f"MD {md} ft is below the bit at {self.bit_depth_md} ft")


# --------------------------------------------------------------------------
# Wellbore
# --------------------------------------------------------------------------

@dataclass
class Wellbore:
    """The hole itself: a contiguous stack of cased and open-hole sections."""

    sections: list[HoleSection] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.sections:
            raise ValueError("Wellbore has no sections")
        self.sections = sorted(self.sections, key=lambda s: s.top_md)
        if abs(self.sections[0].top_md) > 1e-6:
            raise ValueError("The shallowest hole section must start at MD 0")
        for a, b in zip(self.sections, self.sections[1:]):
            if abs(b.top_md - a.bottom_md) > 1e-6:
                raise ValueError(
                    f"Gap or overlap between '{a.name}' (ends {a.bottom_md} ft) "
                    f"and '{b.name}' (starts {b.top_md} ft)"
                )

    @property
    def total_depth_md(self) -> float:
        return self.sections[-1].bottom_md

    @property
    def shoe_md(self) -> float:
        """MD of the deepest casing shoe.

        This is the weak point of the wellbore during a kill: the pressure the
        formation just below the shoe can stand is what limits how much casing
        pressure you can accept.
        """
        cased = [s for s in self.sections if not s.is_open_hole]
        if not cased:
            raise ValueError("This wellbore has no cased sections, so no shoe")
        return max(s.bottom_md for s in cased)

    def hole_id_at(self, md: float) -> float:
        for s in self.sections:
            if s.top_md - 1e-9 <= md <= s.bottom_md + 1e-9:
                return s.id_in
        raise ValueError(f"MD {md} ft is below total depth {self.total_depth_md} ft")

    def section_at(self, md: float) -> HoleSection:
        for s in self.sections:
            if s.top_md - 1e-9 <= md <= s.bottom_md + 1e-9:
                return s
        raise ValueError(f"MD {md} ft is below total depth {self.total_depth_md} ft")


# --------------------------------------------------------------------------
# Annulus (the overlay of string on wellbore)
# --------------------------------------------------------------------------

class Annulus:
    """The annular space, computed by overlaying the string on the wellbore.

    Splits the well at every geometry change -- casing shoes, bit depth, and
    every change of pipe OD -- so annular capacity is exact rather than
    averaged. Doing this by hand is where kill sheet volume errors come from.
    """

    def __init__(self, wellbore: Wellbore, string: DrillString):
        if string.bit_depth_md > wellbore.total_depth_md + 1e-6:
            raise ValueError(
                f"Bit depth ({string.bit_depth_md} ft) is below total depth "
                f"({wellbore.total_depth_md} ft)"
            )
        self.wellbore = wellbore
        self.string = string
        self._check_the_string_fits()
        self._intervals = self._build()

    def _check_the_string_fits(self) -> None:
        """Reject a string that cannot physically go in this hole.

        Caught here rather than when a volume is first requested, because the
        failure then surfaces deep inside an unrelated calculation with a
        message that does not say which component is too big or where. The
        usual cause is a pipe tally paired with the wrong hole section.
        """
        for top_md, bottom_md, component in self.string.intervals():
            for section in self.wellbore.sections:
                overlap_top = max(top_md, section.top_md)
                overlap_bottom = min(bottom_md, section.bottom_md)
                if overlap_bottom - overlap_top <= 1e-6:
                    continue
                if component.od_in > section.id_in + 1e-9:
                    raise ValueError(
                        f"'{component.name}' has an outside diameter of "
                        f"{component.od_in} in, which does not fit inside "
                        f"'{section.name}' at {section.id_in} in. They overlap "
                        f"between {overlap_top:,.0f} and {overlap_bottom:,.0f} ft "
                        "MD. Check the pipe tally is for this hole section."
                    )

    def _build(self) -> list[AnnularInterval]:
        breaks = {0.0, self.string.bit_depth_md, self.wellbore.total_depth_md}
        for s in self.wellbore.sections:
            breaks.add(s.top_md)
            breaks.add(s.bottom_md)
        for top, bottom, _ in self.string.intervals():
            breaks.add(top)
            breaks.add(bottom)

        depths = sorted(d for d in breaks if 0.0 <= d <= self.wellbore.total_depth_md)

        out: list[AnnularInterval] = []
        for top, bottom in zip(depths, depths[1:]):
            if bottom - top < 1e-6:
                continue
            mid = (top + bottom) / 2.0
            hole_id = self.wellbore.hole_id_at(mid)
            # Below the bit there is no pipe: the full hole is open.
            pipe_od = (
                self.string.pipe_od_at(mid) if mid <= self.string.bit_depth_md else 0.0
            )
            section = self.wellbore.section_at(mid)
            desc = section.name if pipe_od == 0.0 else f"{section.name} / string"
            out.append(AnnularInterval(top, bottom, hole_id, pipe_od, desc))
        return out

    @property
    def intervals(self) -> list[AnnularInterval]:
        return list(self._intervals)

    @property
    def volume_bbl(self) -> float:
        """Total annular volume from surface to total depth, bbl.

        Includes any rathole below the bit.
        """
        return sum(i.volume_bbl for i in self._intervals)

    def volume_between(self, top_md: float, bottom_md: float) -> float:
        """Annular volume between two measured depths, bbl."""
        if bottom_md < top_md:
            top_md, bottom_md = bottom_md, top_md
        total = 0.0
        for i in self._intervals:
            lo = max(i.top_md, top_md)
            hi = min(i.bottom_md, bottom_md)
            if hi > lo:
                total += i.capacity_bbl_per_ft * (hi - lo)
        return total

    def capacity_at(self, md: float) -> float:
        """Annular capacity at a measured depth, bbl/ft."""
        for i in self._intervals:
            if i.top_md - 1e-9 <= md <= i.bottom_md + 1e-9:
                return i.capacity_bbl_per_ft
        raise ValueError(f"MD {md} ft is outside the wellbore")

    def height_of_volume_from_bottom(self, volume_bbl: float) -> float:
        """Length occupied by a volume sitting on bottom, ft (measured).

        Fills upward from total depth through each annular interval, honouring
        the capacity change at the top of the drill collars. An influx almost
        always straddles that change, and treating the annulus as one uniform
        capacity is the classic way to under-estimate influx height.

        Returns the measured length. Convert it to vertical height with
        :meth:`Survey.vertical_height_of` before using it in a pressure balance.
        """
        if volume_bbl < 0:
            raise ValueError("Volume cannot be negative")
        remaining = volume_bbl
        height = 0.0
        for i in reversed(self._intervals):
            capacity = i.capacity_bbl_per_ft
            if capacity <= 0:
                continue
            interval_volume = i.volume_bbl
            if remaining <= interval_volume:
                return height + remaining / capacity
            remaining -= interval_volume
            height += i.length_ft
        raise ValueError(
            f"Volume {volume_bbl:.1f} bbl exceeds the total annular volume "
            f"({self.volume_bbl:.1f} bbl) -- the whole annulus would be full."
        )

    def top_of_volume_from_bottom(self, volume_bbl: float) -> float:
        """MD of the top of a volume sitting on bottom, ft."""
        return self.wellbore.total_depth_md - self.height_of_volume_from_bottom(volume_bbl)


# --------------------------------------------------------------------------
# Pumps
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Pump:
    """A mud pump, for converting between volume, strokes and time.

    Attributes:
        liner_id_in: Liner inside diameter, inches.
        stroke_length_in: Stroke length, inches.
        efficiency: Volumetric efficiency, 0-1. Typically 0.95-1.0 for a
            well-maintained triplex.
        kind: ``"triplex"`` (single acting, 3 cylinders) or ``"duplex"``
            (double acting, 2 cylinders).
        rod_od_in: Piston rod OD, inches. Duplex pumps only -- the rod occupies
            part of the cylinder on the return stroke.
    """

    liner_id_in: float
    stroke_length_in: float
    efficiency: float = 1.0
    kind: str = "triplex"
    rod_od_in: float = 0.0

    def __post_init__(self) -> None:
        if self.kind not in ("triplex", "duplex"):
            raise ValueError(f"Unknown pump type '{self.kind}'")
        if not 0 < self.efficiency <= 1.0:
            raise ValueError("Efficiency must be between 0 and 1")
        if self.kind == "duplex" and self.rod_od_in >= self.liner_id_in:
            raise ValueError("Rod OD must be smaller than liner ID")

    @property
    def output_bbl_per_stroke(self) -> float:
        """Displacement per stroke, bbl.

        Triplex (single acting, 3 cylinders)::

            bbl/stk = 0.000243 x liner ID^2 x stroke length x efficiency

        Duplex (double acting, 2 cylinders)::

            bbl/stk = 0.000162 x stroke length x (2 x liner ID^2 - rod OD^2) x efficiency
        """
        if self.kind == "triplex":
            raw = 0.000243 * self.liner_id_in ** 2 * self.stroke_length_in
        else:
            raw = (
                0.000162
                * self.stroke_length_in
                * (2 * self.liner_id_in ** 2 - self.rod_od_in ** 2)
            )
        return raw * self.efficiency

    def strokes_for(self, volume_bbl: float) -> float:
        """Strokes needed to pump a volume."""
        return volume_bbl / self.output_bbl_per_stroke

    def volume_for(self, strokes: float) -> float:
        """Volume delivered by a number of strokes, bbl."""
        return strokes * self.output_bbl_per_stroke

    def flow_rate_gpm(self, spm: float) -> float:
        """Flow rate at a given pump speed, gpm."""
        return self.output_bbl_per_stroke * spm * 42.0

    def spm_for_flow(self, gpm: float) -> float:
        """Pump speed needed for a flow rate, strokes per minute."""
        return gpm / (self.output_bbl_per_stroke * 42.0)

    def minutes_for(self, volume_bbl: float, spm: float) -> float:
        """Time to pump a volume at a given speed, minutes."""
        if spm <= 0:
            raise ValueError("Pump speed must be positive")
        return self.strokes_for(volume_bbl) / spm
