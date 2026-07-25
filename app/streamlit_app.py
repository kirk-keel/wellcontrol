"""Well Control Kill Planner -- Streamlit front end.

Run with::

    streamlit run app/streamlit_app.py

Pick a well configuration and a kill method, enter the well and kick data, and
the app builds the geometry, plans the kill, and renders the step-by-step
procedure with diagnostic plots.

Applicability is checked as soon as a method is selected, before any data is
entered, so a combination that cannot work says so rather than producing
numbers for a procedure that would stall on the rig.
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

# Allow running straight from a checkout without installing.
_SRC = Path(__file__).resolve().parent.parent / "src"
if _SRC.exists() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from wellcontrol.geometry import (  # noqa: E402
    Annulus,
    DrillString,
    HoleSection,
    Pipe,
    Pump,
    Wellbore,
)
from wellcontrol.killsheet import SlowCirculatingRate  # noqa: E402
from wellcontrol.methods import METHODS, get_method  # noqa: E402
from wellcontrol.methods.base import WellState  # noqa: E402
from wellcontrol.plotting import plot_kill, trace_table  # noqa: E402
from wellcontrol.subsea import SubseaGeometry  # noqa: E402
from wellcontrol.survey import Survey  # noqa: E402
from wellcontrol.wellconfig import WellConfiguration  # noqa: E402

st.set_page_config(
    page_title="Well Control Kill Planner",
    page_icon="🛢",
    layout="wide",
)


# --------------------------------------------------------------------------
# Defaults per configuration
# --------------------------------------------------------------------------

DEFAULTS: dict[str, dict[str, float]] = {
    "surface_vertical": dict(
        total_md=10000.0, shoe_md=7000.0, casing_id=8.681, hole_id=8.5,
        bit_md=10000.0, dp_od=5.0, dp_id=4.276, dc_od=6.5, dc_id=2.8125,
        dc_len=600.0, mw=9.6, sidpp=400.0, sicp=660.0, pit_gain=20.0,
        scr_spm=30.0, scr_psi=600.0, frac=12.85, clf=0.0,
        air_gap=0.0, water_depth=0.0, kop=0.0, build=3.0, dp_weight=19.5,
    ),
    "surface_horizontal": dict(
        total_md=12000.0, shoe_md=7200.0, casing_id=8.681, hole_id=6.0,
        bit_md=12000.0, dp_od=4.0, dp_id=3.34, dc_od=4.75, dc_id=2.25,
        dc_len=400.0, mw=10.2, sidpp=350.0, sicp=520.0, pit_gain=15.0,
        scr_spm=35.0, scr_psi=750.0, frac=13.5, clf=0.0,
        air_gap=0.0, water_depth=0.0, kop=4000.0, build=3.0, dp_weight=14.0,
    ),
    "subsea_vertical": dict(
        total_md=15000.0, shoe_md=11000.0, casing_id=12.415, hole_id=12.25,
        bit_md=15000.0, dp_od=5.5, dp_id=4.778, dc_od=8.0, dc_id=3.0,
        dc_len=800.0, mw=12.5, sidpp=500.0, sicp=664.0, pit_gain=25.0,
        scr_spm=30.0, scr_psi=900.0, frac=13.8, clf=350.0,
        air_gap=75.0, water_depth=5000.0, kop=0.0, build=3.0, dp_weight=21.9,
    ),
    "subsea_horizontal": dict(
        total_md=17000.0, shoe_md=12200.0, casing_id=8.681, hole_id=6.0,
        bit_md=17000.0, dp_od=4.0, dp_id=3.34, dc_od=4.75, dc_id=2.25,
        dc_len=400.0, mw=12.5, sidpp=450.0, sicp=520.0, pit_gain=20.0,
        scr_spm=30.0, scr_psi=950.0, frac=14.2, clf=350.0,
        air_gap=75.0, water_depth=5000.0, kop=9000.0, build=3.0, dp_weight=14.0,
    ),
}


def as_text_rows(rows: list[dict]) -> list[dict]:
    """Render every cell as text before handing a table to Streamlit.

    These tables mix types within a column on purpose -- a snub force is a
    number when snubbing is needed and "-" when it is not, and the summary
    holds both "10000 / 10000" and 5392. Arrow cannot type a mixed column, so
    Streamlit falls back with a logged traceback on every rerun. Formatting to
    text up front avoids the round trip and the noise.
    """
    return [{k: ("" if v is None else str(v)) for k, v in row.items()}
            for row in rows]


def detect_theme() -> str:
    """Whichever theme Streamlit is rendering in, so the plots match it.

    A light figure on a dark page reads as a bright slab. Streamlit has moved
    this API around between versions, so try the current one, then the older
    config option, then fall back to light.
    """
    try:
        base = st.context.theme.type
        if base in ("light", "dark"):
            return base
    except Exception:
        pass
    try:
        base = st.get_option("theme.base")
        if base in ("light", "dark"):
            return base
    except Exception:
        pass
    return "light"


def build_well(config: WellConfiguration, values: dict) -> WellState:
    """Assemble a WellState from the form values.

    Raises:
        ValueError: with a message suitable for showing to the user.
    """
    total_md = values["total_md"]
    shoe_md = values["shoe_md"]
    bit_md = values["bit_md"]

    # -- survey ----------------------------------------------------------
    if config.is_horizontal:
        survey = Survey.build_and_hold(
            kop_md=values["kop"],
            build_rate_deg_per_100ft=values["build"],
            final_inclination_deg=90.0,
            total_md=total_md,
        )
    else:
        survey = Survey.vertical(total_md)

    # -- wellbore --------------------------------------------------------
    sections: list[HoleSection] = []
    if config.is_subsea:
        mudline = values["air_gap"] + values["water_depth"]
        if mudline >= shoe_md:
            raise ValueError(
                f"The mudline ({mudline:,.0f} ft) is at or below the casing shoe "
                f"({shoe_md:,.0f} ft). Check the air gap, water depth and shoe "
                "depth."
            )
        sections.append(
            HoleSection("Riser", id_in=values["riser_id"], top_md=0.0,
                        bottom_md=mudline)
        )
        sections.append(
            HoleSection("Casing", id_in=values["casing_id"], top_md=mudline,
                        bottom_md=shoe_md)
        )
    else:
        sections.append(
            HoleSection("Casing", id_in=values["casing_id"], top_md=0.0,
                        bottom_md=shoe_md)
        )
    sections.append(
        HoleSection("Open Hole", id_in=values["hole_id"], top_md=shoe_md,
                    bottom_md=total_md, is_open_hole=True)
    )
    wellbore = Wellbore(sections)

    # -- string ----------------------------------------------------------
    collars = Pipe(
        name="Drill Collars", od_in=values["dc_od"], id_in=values["dc_id"],
        length_ft=values["dc_len"],
    )
    drill_pipe = Pipe(
        name="Drill Pipe", od_in=values["dp_od"], id_in=values["dp_id"],
        length_ft=0.0,
    )
    string = DrillString.from_bha([collars], drill_pipe, bit_md)
    annulus = Annulus(wellbore, string)

    pump = Pump(
        liner_id_in=values["liner_id"],
        stroke_length_in=values["stroke_len"],
        efficiency=values["pump_eff"],
        kind=values["pump_kind"],
        rod_od_in=values.get("rod_od", 0.0),
    )

    subsea = None
    if config.is_subsea:
        subsea = SubseaGeometry(
            air_gap_ft=values["air_gap"],
            water_depth_ft=values["water_depth"],
        )

    return WellState(
        annulus=annulus,
        survey=survey,
        pump=pump,
        mud_weight_ppg=values["mw"],
        slow_circulating_rate=SlowCirculatingRate(
            spm=values["scr_spm"], pressure_psi=values["scr_psi"]
        ),
        configuration=config,
        sidpp_psi=values["sidpp"],
        sicp_psi=values["sicp"],
        pit_gain_bbl=values["pit_gain"],
        frac_gradient_ppg=values["frac"] or None,
        shoe_md_ft=shoe_md,
        subsea=subsea,
        choke_line_friction_psi=values["clf"],
        safety_factor_ppg=values["safety"],
        pipe_weight_lb_per_ft=values["dp_weight"],
        stand_length_ft=values["stand_length"],
        gas_migration_rate_ft_per_hr=values["migration"],
    )


# --------------------------------------------------------------------------
# Layout
# --------------------------------------------------------------------------

st.title("Well Control Kill Planner")
st.caption(
    "Select the well type and kill method, enter the data, and the kill is "
    "calculated step by step with diagnostic plots."
)

configs = WellConfiguration.standard()

selector_left, selector_right = st.columns(2)
with selector_left:
    config_label = st.selectbox(
        "Well configuration", [c.label for c in configs], index=0
    )
    config = next(c for c in configs if c.label == config_label)
with selector_right:
    method_label = st.selectbox(
        "Kill method", [m.name for m in METHODS], index=1
    )
    method = next(m for m in METHODS if m.name == method_label)

st.caption(method.summary)

defaults = DEFAULTS[config.key]

# --------------------------------------------------------------------------
# Inputs
# --------------------------------------------------------------------------

with st.sidebar:
    st.header("Well data")

    with st.expander("Hole and casing", expanded=True):
        total_md = st.number_input(
            "Total depth (ft MD)", 1000.0, 40000.0, defaults["total_md"], 100.0
        )
        shoe_md = st.number_input(
            "Casing shoe (ft MD)", 100.0, 40000.0, defaults["shoe_md"], 100.0
        )
        casing_id = st.number_input(
            "Casing ID (in)", 3.0, 30.0, defaults["casing_id"], 0.001,
            format="%.3f",
        )
        hole_id = st.number_input(
            "Open hole ID (in)", 3.0, 30.0, defaults["hole_id"], 0.001,
            format="%.3f",
        )

    if config.is_subsea:
        with st.expander("Subsea", expanded=True):
            air_gap = st.number_input(
                "Air gap (ft)", 0.0, 300.0, defaults["air_gap"], 5.0
            )
            water_depth = st.number_input(
                "Water depth (ft)", 100.0, 15000.0, defaults["water_depth"], 100.0
            )
            riser_id = st.number_input("Riser ID (in)", 10.0, 24.0, 19.5, 0.5)
            clf = st.number_input(
                "Choke line friction at kill rate (psi)",
                0.0, 3000.0, defaults["clf"], 25.0,
                help="Measured: SCR through the choke line minus SCR through "
                     "the riser. Acts on the formation, so it is subtracted "
                     "from the circulating pressure targets.",
            )
    else:
        air_gap = water_depth = 0.0
        riser_id = 19.5
        clf = 0.0

    if config.is_horizontal:
        with st.expander("Trajectory", expanded=True):
            kop = st.number_input(
                "Kick-off point (ft MD)", 0.0, 30000.0, defaults["kop"], 100.0
            )
            build = st.number_input(
                "Build rate (deg/100 ft)", 0.5, 15.0, defaults["build"], 0.5
            )
    else:
        kop, build = 0.0, 3.0

    with st.expander("Drill string", expanded=False):
        bit_md = st.number_input(
            "Bit depth (ft MD)", 100.0, 40000.0, defaults["bit_md"], 100.0
        )
        dp_od = st.number_input("Drill pipe OD (in)", 2.0, 8.0,
                                defaults["dp_od"], 0.125)
        dp_id = st.number_input("Drill pipe ID (in)", 1.0, 7.0,
                                defaults["dp_id"], 0.001, format="%.3f")
        dc_od = st.number_input("Collar OD (in)", 2.0, 12.0,
                                defaults["dc_od"], 0.125)
        dc_id = st.number_input("Collar ID (in)", 1.0, 6.0,
                                defaults["dc_id"], 0.0625, format="%.4f")
        dc_len = st.number_input("Collar length (ft)", 0.0, 3000.0,
                                 defaults["dc_len"], 30.0)
        dp_weight = st.number_input(
            "Drill pipe weight (lb/ft)", 5.0, 60.0, defaults["dp_weight"], 0.5,
            help="Nominal weight in air. Sets the balance point between pipe "
                 "weight and well pressure when stripping.",
        )
        stand_length = st.number_input(
            "Stand length (ft)", 30.0, 120.0, 93.0, 1.0,
            help="93 ft for triples, 63 ft for doubles.",
        )

    with st.expander("Pump", expanded=False):
        pump_kind = st.selectbox("Type", ["triplex", "duplex"], index=0)
        liner_id = st.number_input("Liner ID (in)", 3.0, 9.0, 6.5, 0.125)
        stroke_len = st.number_input("Stroke length (in)", 6.0, 20.0, 12.0, 0.5)
        pump_eff = st.slider("Volumetric efficiency", 0.70, 1.00, 0.95, 0.01)
        rod_od = (
            st.number_input("Rod OD (in)", 0.5, 4.0, 2.0, 0.125)
            if pump_kind == "duplex" else 0.0
        )

    st.header("Kick data")
    mw = st.number_input("Mud weight (ppg)", 8.0, 20.0, defaults["mw"], 0.1)
    sidpp = st.number_input("SIDPP (psi)", 0.0, 8000.0, defaults["sidpp"], 10.0)
    sicp = st.number_input("SICP (psi)", 0.0, 8000.0, defaults["sicp"], 10.0)
    pit_gain = st.number_input("Pit gain (bbl)", 0.0, 500.0,
                               defaults["pit_gain"], 1.0)
    scr_spm = st.number_input("Kill rate (spm)", 5.0, 120.0,
                              defaults["scr_spm"], 1.0)
    scr_psi = st.number_input("SCR pressure at kill rate (psi)", 0.0, 5000.0,
                              defaults["scr_psi"], 10.0)
    frac = st.number_input(
        "Fracture gradient at shoe (ppg EMW)", 0.0, 25.0, defaults["frac"], 0.05,
        help="From the leak-off test. Set to 0 if unknown -- the shoe cannot "
             "then be checked.",
    )
    safety = st.number_input("Kill mud safety factor (ppg)", 0.0, 2.0, 0.0, 0.1)
    migration = st.number_input(
        "Gas migration rate (ft/hr)", 0.0, 5000.0, 0.0, 50.0,
        help="From the rate of shut-in pressure rise: rate = (psi/hr) / "
             "(0.052 x MW). Used by the Volumetric and Stripping methods. "
             "Leave at 0 if gas is not migrating.",
    )

    st.header("Display")
    theme = st.radio(
        "Chart theme", ["light", "dark"], horizontal=True,
        index=["light", "dark"].index(detect_theme()),
        help="Defaults to whichever theme the app is running in, so the plots "
             "do not sit as a bright slab on a dark page.",
    )

values = dict(
    total_md=total_md, shoe_md=shoe_md, casing_id=casing_id, hole_id=hole_id,
    bit_md=bit_md, dp_od=dp_od, dp_id=dp_id, dc_od=dc_od, dc_id=dc_id,
    dc_len=dc_len, mw=mw, sidpp=sidpp, sicp=sicp, pit_gain=pit_gain,
    scr_spm=scr_spm, scr_psi=scr_psi, frac=frac, clf=clf, safety=safety,
    air_gap=air_gap, water_depth=water_depth, riser_id=riser_id,
    kop=kop, build=build, liner_id=liner_id, stroke_len=stroke_len,
    pump_eff=pump_eff, pump_kind=pump_kind, rod_od=rod_od,
    dp_weight=dp_weight, stand_length=stand_length, migration=migration,
)

# --------------------------------------------------------------------------
# Build and plan
# --------------------------------------------------------------------------

try:
    well = build_well(config, values)
except ValueError as exc:
    st.error(f"**Cannot build this well:** {exc}")
    st.stop()
except Exception as exc:  # geometry constructors raise plain ValueErrors mostly
    st.error(f"**Cannot build this well:** {exc}")
    st.stop()

try:
    plan = get_method(method.key).plan(well)
except Exception as exc:
    st.error(f"**{method.name} could not be planned:** {exc}")
    st.stop()

# -- applicability ---------------------------------------------------------

applicability = plan.applicability
if applicability.blockers:
    st.error(
        f"**{method.name} is not usable on this well.**\n\n"
        + "\n\n".join(f"- {b}" for b in applicability.blockers)
    )
if applicability.warnings:
    count = len(applicability.warnings)
    with st.expander(
        f"⚠ {count} thing{'' if count == 1 else 's'} to watch — "
        f"{method.name} on a {config.label} well",
        expanded=bool(applicability.blockers),
    ):
        for warning in applicability.warnings:
            st.markdown(f"- {warning}")

# -- headline numbers ------------------------------------------------------

st.subheader("Kill sheet numbers")

metrics = st.columns(4)
metrics[0].metric("Kill mud weight", f"{well.kill_mud_weight_ppg:.2f} ppg",
                  f"{well.kill_mud_weight_ppg - well.mud_weight_ppg:+.2f}")
metrics[1].metric("Formation pressure", f"{well.formation_pressure_psi:,.0f} psi")
metrics[2].metric("Bit TVD", f"{well.bit_tvd_ft:,.0f} ft",
                  f"{well.bit_tvd_ft - well.bit_md_ft:+,.0f} vs MD")
peak_shoe = plan.peak_shoe_pressure_psi
if peak_shoe is not None and plan.shoe_frac_pressure_psi:
    margin = plan.shoe_frac_pressure_psi - peak_shoe
    metrics[3].metric(
        "Margin at shoe", f"{margin:,.0f} psi",
        delta=None if margin >= 0 else "FRACTURES",
        delta_color="inverse" if margin < 0 else "normal",
    )
else:
    metrics[3].metric("Peak casing", f"{plan.peak_casing_pressure_psi or 0:,.0f} psi")

with st.expander("All calculated values", expanded=False):
    st.dataframe(
        as_text_rows([{"Quantity": k, "Value": v} for k, v in plan.summary.items()]),
        width="stretch", hide_index=True,
    )

# -- plots -----------------------------------------------------------------

st.subheader("Kill diagnostics")
try:
    figure = plot_kill(plan, theme=theme)
    st.pyplot(figure)
except ValueError as exc:
    st.info(str(exc))

with st.expander("Plot data as a table", expanded=False):
    st.dataframe(trace_table(plan, every=3), width="stretch", hide_index=True)

# -- procedure -------------------------------------------------------------

st.subheader("Procedure")
for index, stage in enumerate(plan.stages, 1):
    header = stage.name
    if stage.strokes:
        header += f"  ·  {stage.strokes:,.0f} strokes"
    with st.expander(header, expanded=index <= 2):
        st.markdown(f"*{stage.description}*")
        for action in stage.actions:
            st.markdown(f"- {action}")
        if stage.table:
            st.dataframe(as_text_rows(stage.table), width="stretch",
                         hide_index=True)

# -- notes -----------------------------------------------------------------

if plan.notes:
    with st.expander("Notes on this method and well type", expanded=False):
        for note in plan.notes:
            st.markdown(f"- {note}")

st.divider()
st.caption(
    "These are engineering aids, not a substitute for certification, a company "
    "well control manual, or the judgement of a competent person on the rig."
)
