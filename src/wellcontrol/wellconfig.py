"""Well configurations: where the BOP is, and where the hole goes.

Kill methods do not behave identically on every well. Two axes matter enough to
change the procedure:

**BOP location.** A surface stack has a short choke line and the gauge sits at
the same datum as the wellhead. A subsea stack has a choke line as long as the
water is deep, whose friction lands on the formation, and a wellhead thousands
of feet below the gauge reading it.

**Trajectory.** In a vertical well every foot of hole is a foot of hydrostatic
and gas migrates freely. In a horizontal lateral neither is true: measured depth
buys no vertical height, and gas in the lateral has no upward direction to
migrate in. Methods that *depend* on migration -- volumetric, lube and bleed --
stop working while the influx is out in the lateral.

The four standard combinations:

* Surface BOP, vertical
* Surface BOP, horizontal
* Subsea BOP, vertical
* Subsea BOP, horizontal
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class BOPLocation(Enum):
    """Where the blowout preventer stack sits."""

    SURFACE = "surface"
    SUBSEA = "subsea"

    @property
    def label(self) -> str:
        return "Surface BOP" if self is BOPLocation.SURFACE else "Subsea BOP"


class Trajectory(Enum):
    """The shape of the hole, as it affects well control."""

    VERTICAL = "vertical"
    DEVIATED = "deviated"
    HORIZONTAL = "horizontal"

    @property
    def label(self) -> str:
        return self.value.capitalize()

    @property
    def migration_reliable(self) -> bool:
        """Whether gas can be relied on to migrate up the annulus.

        Vertical and moderately deviated holes: yes. Horizontal: not while the
        influx is in the lateral.
        """
        return self is not Trajectory.HORIZONTAL


@dataclass(frozen=True)
class WellConfiguration:
    """A BOP location paired with a trajectory."""

    bop: BOPLocation
    trajectory: Trajectory

    @property
    def label(self) -> str:
        return f"{self.bop.label} - {self.trajectory.label}"

    @property
    def key(self) -> str:
        return f"{self.bop.value}_{self.trajectory.value}"

    @property
    def is_subsea(self) -> bool:
        return self.bop is BOPLocation.SUBSEA

    @property
    def is_horizontal(self) -> bool:
        return self.trajectory is Trajectory.HORIZONTAL

    @classmethod
    def standard(cls) -> list["WellConfiguration"]:
        """The four combinations the app offers."""
        return [
            cls(BOPLocation.SURFACE, Trajectory.VERTICAL),
            cls(BOPLocation.SURFACE, Trajectory.HORIZONTAL),
            cls(BOPLocation.SUBSEA, Trajectory.VERTICAL),
            cls(BOPLocation.SUBSEA, Trajectory.HORIZONTAL),
        ]

    @classmethod
    def from_key(cls, key: str) -> "WellConfiguration":
        for config in cls.standard():
            if config.key == key:
                return config
        # Fall back to parsing, so "surface_deviated" also works.
        bop_value, _, trajectory_value = key.partition("_")
        return cls(BOPLocation(bop_value), Trajectory(trajectory_value))

    def considerations(self) -> list[str]:
        """Things this configuration changes about any kill."""
        notes: list[str] = []

        if self.is_subsea:
            notes.append(
                "Choke line friction acts on the formation. Subtract it from the "
                "circulating pressure targets, or hold it off with the choke."
            )
            notes.append(
                "The gauge is at the rig floor; the BOP is at the mudline. "
                "Convert before checking any stack or wellhead rating."
            )
            notes.append(
                "Check riser margin. If the riser is lost, hydrostatic drops by "
                "the difference between mud and seawater over the water depth."
            )
        else:
            notes.append(
                "Short choke line, so choke line friction is negligible and no "
                "correction to the circulating pressures is needed."
            )

        if self.is_horizontal:
            notes.append(
                "Kill mud weight must be computed on TVD. Using measured depth "
                "on this well gives a mud weight far too light."
            )
            notes.append(
                "An influx in the lateral has almost no vertical height, so it "
                "barely raises casing pressure and cannot be identified from "
                "the shut-in pressures."
            )
            notes.append(
                "Gas does not migrate in the lateral. Shut-in pressures will not "
                "climb the way they would on a vertical well -- which removes "
                "the time pressure, but also removes the warning."
            )
        else:
            notes.append(
                "Gas migrates. Expect shut-in pressures to climb while the well "
                "is closed in and not circulating."
            )

        return notes
