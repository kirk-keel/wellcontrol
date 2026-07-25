"""Directional survey handling: the MD vs TVD distinction.

This is the single most common source of blown well control calculations on
anything that is not a vertical land well.

**Hydrostatic pressure depends only on TVD.** A 20,000 ft horizontal well with
a 9,000 ft TVD has the hydrostatic head of a 9,000 ft well. Get this wrong on a
kill sheet and the kill mud weight is wrong by the ratio MD/TVD -- on a well
with a 2,000 ft lateral that is not a rounding error, it is a well control
incident.

**Volumes, strokes and pump displacement depend only on MD.** The mud has to
travel the whole measured length of the hole regardless of where it points.

So: pressure calculations take TVD, circulation calculations take MD, and this
module converts between them.
"""

from __future__ import annotations

import math
from bisect import bisect_left
from dataclasses import dataclass


@dataclass(frozen=True)
class SurveyStation:
    """One directional survey station.

    Attributes:
        md: Measured depth along hole, ft.
        tvd: True vertical depth, ft.
        inclination_deg: Angle from vertical. 0 = vertical, 90 = horizontal.
        azimuth_deg: Compass heading of the wellbore, degrees.
    """

    md: float
    tvd: float
    inclination_deg: float = 0.0
    azimuth_deg: float = 0.0


class Survey:
    """A directional survey with interpolation between stations.

    Interpolation is linear in TVD vs MD between stations, which is accurate
    enough for well control work when stations are at normal 30-100 ft spacing.
    (Minimum-curvature is the right method for building the survey itself; this
    class consumes an already-computed survey.)
    """

    def __init__(self, stations: list[SurveyStation]):
        if len(stations) < 2:
            raise ValueError("A survey needs at least two stations")

        ordered = sorted(stations, key=lambda s: s.md)
        for a, b in zip(ordered, ordered[1:]):
            if b.md == a.md:
                raise ValueError(f"Duplicate survey station at MD {a.md}")
            if b.tvd < a.tvd - 1e-9:
                raise ValueError(
                    f"TVD decreases between MD {a.md} and {b.md}. "
                    "This well is drilled upward; that is not supported."
                )
            span = b.md - a.md
            if b.tvd - a.tvd > span + 1e-6:
                raise ValueError(
                    f"TVD gain ({b.tvd - a.tvd:.1f} ft) exceeds MD gain "
                    f"({span:.1f} ft) between MD {a.md} and {b.md}. "
                    "TVD can never increase faster than MD."
                )

        self.stations = ordered
        self._mds = [s.md for s in ordered]
        self._tvds = [s.tvd for s in ordered]

    # -- construction helpers ------------------------------------------------

    @classmethod
    def vertical(cls, total_depth: float) -> "Survey":
        """A perfectly vertical well where MD == TVD everywhere."""
        return cls([
            SurveyStation(md=0.0, tvd=0.0, inclination_deg=0.0),
            SurveyStation(md=total_depth, tvd=total_depth, inclination_deg=0.0),
        ])

    @classmethod
    def build_and_hold(
        cls,
        kop_md: float,
        build_rate_deg_per_100ft: float,
        final_inclination_deg: float,
        total_md: float,
        azimuth_deg: float = 0.0,
        station_interval_ft: float = 100.0,
    ) -> "Survey":
        """Generate a build-and-hold trajectory.

        Vertical to the kick-off point, build at a constant rate to the final
        inclination, then hold that angle tangentially to total depth. Set
        ``final_inclination_deg=90`` for a horizontal well.

        Uses the radius-of-curvature method through the build section.

        Args:
            kop_md: Kick-off point, MD in ft.
            build_rate_deg_per_100ft: Build rate, e.g. 3.0 for 3 deg/100ft.
            final_inclination_deg: Inclination held through the tangent section.
            total_md: Total measured depth, ft.
            azimuth_deg: Constant hole azimuth.
            station_interval_ft: Spacing of generated stations.
        """
        if build_rate_deg_per_100ft <= 0:
            raise ValueError("Build rate must be positive")
        if not 0 < final_inclination_deg <= 90:
            raise ValueError("Final inclination must be in (0, 90] degrees")

        build_md_length = (final_inclination_deg / build_rate_deg_per_100ft) * 100.0
        end_of_build_md = kop_md + build_md_length
        if total_md < end_of_build_md:
            raise ValueError(
                f"Total MD ({total_md:.0f} ft) is shallower than the end of the "
                f"build section ({end_of_build_md:.0f} ft). Reduce the final "
                "inclination or increase the build rate."
            )

        # Radius of curvature of the build arc, ft.
        radius = (180.0 / math.pi) * (100.0 / build_rate_deg_per_100ft)

        stations = [SurveyStation(0.0, 0.0, 0.0, azimuth_deg)]

        def add(md: float) -> None:
            if md <= stations[-1].md:
                return
            if md <= kop_md:
                inc = 0.0
                tvd = md
            elif md <= end_of_build_md:
                inc = (md - kop_md) * build_rate_deg_per_100ft / 100.0
                tvd = kop_md + radius * math.sin(math.radians(inc))
            else:
                inc = final_inclination_deg
                tvd_at_eob = kop_md + radius * math.sin(math.radians(final_inclination_deg))
                tvd = tvd_at_eob + (md - end_of_build_md) * math.cos(math.radians(inc))
            stations.append(SurveyStation(md, tvd, inc, azimuth_deg))

        add(kop_md)
        md = kop_md + station_interval_ft
        while md < end_of_build_md:
            add(md)
            md += station_interval_ft
        add(end_of_build_md)
        md = end_of_build_md + station_interval_ft
        while md < total_md:
            add(md)
            md += station_interval_ft
        add(total_md)

        return cls(stations)

    # -- conversions ---------------------------------------------------------

    @property
    def total_md(self) -> float:
        return self._mds[-1]

    @property
    def total_tvd(self) -> float:
        return self._tvds[-1]

    def tvd_at(self, md: float) -> float:
        """True vertical depth at a measured depth, by linear interpolation."""
        if md < self._mds[0] - 1e-9 or md > self._mds[-1] + 1e-9:
            raise ValueError(
                f"MD {md} ft is outside the surveyed interval "
                f"{self._mds[0]}-{self._mds[-1]} ft"
            )
        md = min(max(md, self._mds[0]), self._mds[-1])

        i = bisect_left(self._mds, md)
        if i == 0:
            return self._tvds[0]
        if self._mds[i] == md:
            return self._tvds[i]

        md0, md1 = self._mds[i - 1], self._mds[i]
        tvd0, tvd1 = self._tvds[i - 1], self._tvds[i]
        frac = (md - md0) / (md1 - md0)
        return tvd0 + frac * (tvd1 - tvd0)

    def md_at(self, tvd: float) -> float:
        """Measured depth at a true vertical depth.

        In a horizontal or near-horizontal section many measured depths share
        one TVD. This returns the **shallowest** MD that reaches the given TVD,
        which is the correct choice for locating a casing shoe or a formation
        top by TVD.
        """
        if tvd < self._tvds[0] - 1e-9 or tvd > self._tvds[-1] + 1e-9:
            raise ValueError(
                f"TVD {tvd} ft is outside the surveyed interval "
                f"{self._tvds[0]}-{self._tvds[-1]} ft"
            )
        tvd = min(max(tvd, self._tvds[0]), self._tvds[-1])

        for i in range(1, len(self._tvds)):
            tvd0, tvd1 = self._tvds[i - 1], self._tvds[i]
            if tvd1 >= tvd - 1e-9:
                if abs(tvd1 - tvd0) < 1e-9:
                    return self._mds[i - 1]
                frac = (tvd - tvd0) / (tvd1 - tvd0)
                return self._mds[i - 1] + frac * (self._mds[i] - self._mds[i - 1])
        return self._mds[-1]

    def inclination_at(self, md: float) -> float:
        """Hole inclination at a measured depth, degrees from vertical."""
        i = bisect_left(self._mds, md)
        if i == 0:
            return self.stations[0].inclination_deg
        if i >= len(self.stations):
            return self.stations[-1].inclination_deg
        if self._mds[i] == md:
            return self.stations[i].inclination_deg
        md0, md1 = self._mds[i - 1], self._mds[i]
        inc0 = self.stations[i - 1].inclination_deg
        inc1 = self.stations[i].inclination_deg
        frac = (md - md0) / (md1 - md0)
        return inc0 + frac * (inc1 - inc0)

    def trajectory_sections(
        self, tolerance_deg: float = 1.0, lateral_threshold_deg: float = 85.0
    ) -> list[tuple[float, float, str]]:
        """Split the well into vertical, build, drop and tangent sections.

        Returns ``(top_md, bottom_md, name)`` per section.

        A kill schedule behaves differently in each of these, because the TVD
        gained per foot of hole is different. In the vertical section every
        foot of kill mud buys a foot of hydrostatic; through the build it buys
        progressively less; in a lateral it buys none at all. A single
        straight-line schedule cannot represent all three.
        """
        if len(self.stations) < 2:
            return [(0.0, self.total_md, "Vertical")]

        def classify(start, end) -> str:
            change = end.inclination_deg - start.inclination_deg
            if abs(change) > tolerance_deg:
                return "Build" if change > 0 else "Drop"
            if end.inclination_deg >= lateral_threshold_deg:
                return "Lateral"
            if end.inclination_deg >= tolerance_deg:
                return "Tangent"
            return "Vertical"

        sections: list[list] = []
        for start, end in zip(self.stations, self.stations[1:]):
            name = classify(start, end)
            if sections and sections[-1][2] == name:
                sections[-1][1] = end.md
            else:
                sections.append([start.md, end.md, name])

        # Merge away slivers left by a single noisy station.
        merged: list[list] = []
        for section in sections:
            if merged and section[1] - section[0] < 1e-6:
                merged[-1][1] = section[1]
            else:
                merged.append(section)
        return [(top, bottom, name) for top, bottom, name in merged]

    def section_at(self, md: float, **kwargs) -> str:
        """Name of the trajectory section containing a measured depth."""
        for top, bottom, name in self.trajectory_sections(**kwargs):
            if top - 1e-9 <= md <= bottom + 1e-9:
                return name
        return "Unknown"

    def vertical_height_of(self, top_md: float, bottom_md: float) -> float:
        """TVD height spanned by a measured-depth interval.

        This is what converts an influx length in the annulus (measured along
        the hole) into the vertical height that actually generates hydrostatic
        pressure. In a horizontal lateral this returns ~0: a gas influx sitting
        in the lateral contributes no hydrostatic head and, critically, cannot
        migrate.
        """
        if bottom_md < top_md:
            top_md, bottom_md = bottom_md, top_md
        return self.tvd_at(bottom_md) - self.tvd_at(top_md)
