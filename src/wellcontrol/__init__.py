"""wellcontrol -- well control calculations for every type of well.

A calculation library covering the arithmetic of well control, from a vertical
land well through directional, subsea, HPHT and managed pressure drilling.

Quick start::

    from wellcontrol import examples
    sheet = examples.vertical_land_well_kill_sheet()
    for key, value in sheet.summary().items():
        print(f"{key:.<40} {value}")
    print(sheet.format_schedule(sheet.schedule_by_depth()))

The teaching content in ``content/`` walks through the theory behind each
module with worked examples.

**These are engineering aids, not a substitute for certification, a
company well control manual, or the judgement of a competent person on the
rig.** Verify against your own procedures before using any of it operationally.
"""

from __future__ import annotations

from . import (
    examples,
    geometry,
    hpht,
    hydrostatics,
    kick,
    killsheet,
    methods,
    mpd,
    rheology,
    rounding,
    stripping,
    subsea,
    survey,
    tolerance,
    units,
    wellconfig,
)
from .geometry import (
    Annulus,
    DrillString,
    HoleSection,
    Pipe,
    Pump,
    Wellbore,
    annular_capacity_bbl_per_ft,
    capacity_bbl_per_ft,
)
from .hydrostatics import (
    FluidSegment,
    equivalent_circulating_density,
    equivalent_mud_weight,
    hydrostatic_pressure,
)
from .kick import ShutInAnalysis, classify_influx, gas_expansion_boyle
from .killsheet import KillSheet, SlowCirculatingRate
from .methods import (
    KillPlan,
    WellState,
    applicability_matrix,
    get_method,
    list_methods,
    plan_kill,
)
from .rheology import BinghamPlastic, PowerLaw
from .subsea import SubseaGeometry, riser_margin_ppg
from .survey import Survey, SurveyStation
from .tolerance import KickTolerance, maasp

__version__ = "0.1.0"

__all__ = [
    # submodules
    "units",
    "survey",
    "geometry",
    "hydrostatics",
    "rheology",
    "kick",
    "killsheet",
    "tolerance",
    "subsea",
    "hpht",
    "mpd",
    "wellconfig",
    "rounding",
    "stripping",
    "methods",
    "examples",
    # common types
    "Survey",
    "SurveyStation",
    "Pipe",
    "HoleSection",
    "DrillString",
    "Wellbore",
    "Annulus",
    "Pump",
    "FluidSegment",
    "BinghamPlastic",
    "PowerLaw",
    "ShutInAnalysis",
    "KillSheet",
    "SlowCirculatingRate",
    "KickTolerance",
    "SubseaGeometry",
    "WellConfiguration",
    "WellState",
    "KillPlan",
    # common functions
    "capacity_bbl_per_ft",
    "annular_capacity_bbl_per_ft",
    "hydrostatic_pressure",
    "equivalent_mud_weight",
    "equivalent_circulating_density",
    "classify_influx",
    "gas_expansion_boyle",
    "maasp",
    "riser_margin_ppg",
    "plan_kill",
    "get_method",
    "list_methods",
    "applicability_matrix",
]
