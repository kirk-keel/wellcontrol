"""Model Context Protocol (MCP) server for deterministic well control & CWI agents.

Exposes the ``wellcontrol`` physics solver, 7-method kill planner, CWI stripping
and snubbing calculators, and forward dynamic choke simulator as structured MCP
tools so LLM agents never have to improvise well control arithmetic.

The tool functions in this module are pure Python and depend only on the core
``wellcontrol`` library. The ``mcp`` package (``pip install -e ".[mcp]"``) is
loaded lazily by :func:`build_mcp_server` and :func:`main` so importing this
module in unit tests or agent pipelines keeps the core library dependency-free.

Run over stdio for Claude Desktop, Cursor, or OpenAI Agents SDK::

    python -m wellcontrol.mcp_server
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from . import examples
from .methods import METHODS, WellState, applicability_matrix, plan_kill, strip_then_kill
from .rheology import BinghamPlastic
from .sim import Session, Standard, ValveState
from .sim.scenario import SCENARIOS
from .stripping import (
    StripDirection,
    StrippingOperation,
    pressure_rise_if_not_bled,
    surge_pressure_estimate,
)
from .wellconfig import BOPLocation, Trajectory, WellConfiguration

# In-memory simulator session store for multi-turn agentic well control runs.
_SIM_SESSIONS: dict[str, Session] = {}


def _build_configured_well(
    bop: str = "surface",
    trajectory: str = "vertical",
    sidpp_psi: float | None = None,
    sicp_psi: float | None = None,
    pit_gain_bbl: float | None = None,
    mud_weight_ppg: float | None = None,
    bit_off_bottom_ft: float = 0.0,
    gas_migration_rate_ft_per_hr: float | None = None,
) -> WellState:
    """Build a :class:`WellState` from a standard configuration with overrides."""
    try:
        bop_enum = BOPLocation(bop.lower().strip())
    except ValueError as exc:
        valid = [b.value for b in BOPLocation]
        raise ValueError(f"Unknown bop {bop!r}; choose from {valid}") from exc

    try:
        traj_enum = Trajectory(trajectory.lower().strip())
    except ValueError as exc:
        valid = [t.value for t in Trajectory]
        raise ValueError(
            f"Unknown trajectory {trajectory!r}; choose from {valid}"
        ) from exc

    config = WellConfiguration(bop_enum, traj_enum)
    well = examples.well_state(config, bit_off_bottom_ft=max(0.0, bit_off_bottom_ft))

    overrides: dict[str, Any] = {}
    if sidpp_psi is not None:
        overrides["sidpp_psi"] = float(sidpp_psi)
    if sicp_psi is not None:
        overrides["sicp_psi"] = float(sicp_psi)
    if pit_gain_bbl is not None:
        overrides["pit_gain_bbl"] = float(pit_gain_bbl)
    if mud_weight_ppg is not None:
        overrides["mud_weight_ppg"] = float(mud_weight_ppg)
    if gas_migration_rate_ft_per_hr is not None:
        overrides["gas_migration_rate_ft_per_hr"] = float(gas_migration_rate_ft_per_hr)

    if overrides:
        well = replace(well, **overrides)
    return well


def evaluate_kill_methods(
    bop: str = "surface",
    trajectory: str = "vertical",
    sidpp_psi: float | None = None,
    sicp_psi: float | None = None,
    pit_gain_bbl: float | None = None,
    mud_weight_ppg: float | None = None,
    bit_off_bottom_ft: float = 0.0,
    gas_migration_rate_ft_per_hr: float | None = None,
) -> dict[str, Any]:
    """Evaluate all 7 well control methods on a well and return applicability & shoe margins.

    Computes kill mud weight (rounded UP to 0.1 ppg), formation pressure, MAASP
    (rounded DOWN to whole psi), influx gradient/type, and runs every registered
    method (Driller's, Wait and Weight, Volumetric, Stripping to Bottom, Lube
    and Bleed, Reverse Circulation, Bullheading) to report which methods are
    usable, which are blocked (and why), and what peak pressure each puts on the
    casing shoe.
    """
    well = _build_configured_well(
        bop=bop,
        trajectory=trajectory,
        sidpp_psi=sidpp_psi,
        sicp_psi=sicp_psi,
        pit_gain_bbl=pit_gain_bbl,
        mud_weight_ppg=mud_weight_ppg,
        bit_off_bottom_ft=bit_off_bottom_ft,
        gas_migration_rate_ft_per_hr=gas_migration_rate_ft_per_hr,
    )
    matrix = applicability_matrix(well)
    methods_report: dict[str, dict[str, Any]] = {}

    for method in METHODS:
        plan = method.plan(well)
        peak_shoe = plan.peak_shoe_pressure_psi
        frac = plan.shoe_frac_pressure_psi
        margin = (
            round(frac - peak_shoe)
            if (frac is not None and peak_shoe is not None)
            else None
        )
        methods_report[method.key] = {
            "name": method.name,
            "summary": method.summary,
            "circulates": method.circulates,
            "usable": plan.applicability.usable,
            "blockers": list(plan.applicability.blockers),
            "warnings": list(plan.applicability.warnings),
            "peak_shoe_pressure_psi": (
                round(peak_shoe) if peak_shoe is not None else None
            ),
            "shoe_fracture_pressure_psi": round(frac) if frac is not None else None,
            "shoe_margin_psi": margin,
            "headline_metrics": dict(plan.summary),
        }

    maasp = well.maasp_psi()
    return {
        "configuration": {
            "key": well.configuration.key,
            "label": well.configuration.label,
            "bop": well.configuration.bop.value,
            "trajectory": well.configuration.trajectory.value,
            "hole_md_ft": round(well.hole_md_ft, 1),
            "hole_tvd_ft": round(well.hole_tvd_ft, 1),
            "bit_md_ft": round(well.bit_md_ft, 1),
            "bit_tvd_ft": round(well.bit_tvd_ft, 1),
            "shoe_tvd_ft": (
                round(well.shoe_tvd_ft, 1) if well.shoe_tvd_ft is not None else None
            ),
        },
        "shut_in_essentials": {
            "original_mud_weight_ppg": well.mud_weight_ppg,
            "kill_mud_weight_ppg": well.kill_mud_weight_ppg,
            "sidpp_psi": well.sidpp_psi,
            "sicp_psi": well.sicp_psi,
            "pit_gain_bbl": well.pit_gain_bbl,
            "formation_pressure_psi": round(well.formation_pressure_psi, 1),
            "maasp_psi": round(maasp) if maasp is not None else None,
            "shoe_fracture_pressure_psi": (
                round(well.frac_pressure_psi)
                if well.frac_pressure_psi is not None
                else None
            ),
            "influx_gradient_psi_per_ft": round(well.influx_gradient_psi_per_ft, 3),
            "influx_density_ppg": round(well.influx_density_ppg, 2),
        },
        "usable_methods": [
            k for k, v in methods_report.items() if v["usable"]
        ],
        "blocked_methods": [
            k for k, v in methods_report.items() if not v["usable"]
        ],
        "methods": methods_report,
        "quick_applicability": {
            k: {
                "usable": v.usable,
                "blocker_count": len(v.blockers),
                "warning_count": len(v.warnings),
            }
            for k, v in matrix.items()
        },
    }


def plan_well_kill(
    method_key: str = "wait_and_weight",
    bop: str = "surface",
    trajectory: str = "vertical",
    sidpp_psi: float | None = None,
    sicp_psi: float | None = None,
    pit_gain_bbl: float | None = None,
    mud_weight_ppg: float | None = None,
    bit_off_bottom_ft: float = 0.0,
    gas_migration_rate_ft_per_hr: float | None = None,
    include_strip_then_kill: bool = False,
    follow_on_kill_method: str = "drillers",
) -> dict[str, Any]:
    """Generate a complete well control kill plan and drill pipe pressure schedule.

    Args:
        method_key: One of ``"drillers"``, ``"wait_and_weight"``, ``"volumetric"``,
            ``"stripping"``, ``"lube_and_bleed"``, ``"reverse"``, or ``"bullhead"``.
        bop: ``"surface"`` or ``"subsea"``.
        trajectory: ``"vertical"``, ``"deviated"``, or ``"horizontal"``.
        sidpp_psi: Shut-in drill pipe pressure (psi). Uses preset default if None.
        sicp_psi: Shut-in casing pressure (psi). Uses preset default if None.
        pit_gain_bbl: Recorded pit gain (bbl). Uses preset default if None.
        mud_weight_ppg: Current mud weight in hole (ppg). Uses preset default if None.
        bit_off_bottom_ft: Distance of bit off bottom (ft MD).
        gas_migration_rate_ft_per_hr: Measured gas migration rate (ft/hr).
        include_strip_then_kill: When True and ``bit_off_bottom_ft > 0``, also
            computes the combined two-phase :func:`strip_then_kill` sequence.
        follow_on_kill_method: ``"drillers"`` or ``"wait_and_weight"`` for phase 2
            when ``include_strip_then_kill`` is True.
    """
    well = _build_configured_well(
        bop=bop,
        trajectory=trajectory,
        sidpp_psi=sidpp_psi,
        sicp_psi=sicp_psi,
        pit_gain_bbl=pit_gain_bbl,
        mud_weight_ppg=mud_weight_ppg,
        bit_off_bottom_ft=bit_off_bottom_ft,
        gas_migration_rate_ft_per_hr=gas_migration_rate_ft_per_hr,
    )
    plan = plan_kill(well, method_key)
    segments = well.kill_sheet.schedule_segments()

    result: dict[str, Any] = {
        "method_key": plan.method_key,
        "method_name": plan.method_name,
        "usable": plan.applicability.usable,
        "blockers": list(plan.applicability.blockers),
        "warnings": list(plan.applicability.warnings),
        "summary": dict(plan.summary),
        "peak_shoe_pressure_psi": (
            round(plan.peak_shoe_pressure_psi)
            if plan.peak_shoe_pressure_psi is not None
            else None
        ),
        "shoe_fracture_pressure_psi": (
            round(plan.shoe_frac_pressure_psi)
            if plan.shoe_frac_pressure_psi is not None
            else None
        ),
        "stages": [
            {
                "name": stage.name,
                "description": stage.description,
                "strokes": round(stage.strokes) if stage.strokes is not None else None,
                "actions": list(stage.actions),
                "table": stage.table,
            }
            for stage in plan.stages
        ],
        "schedule_segments": [
            {
                "component": seg.name,
                "reason": seg.reason,
                "start_md_ft": round(seg.top_md, 1),
                "end_md_ft": round(seg.bottom_md, 1),
                "strokes_in_segment": round(seg.strokes),
                "start_strokes": round(seg.start_strokes),
                "end_strokes": round(seg.end_strokes),
                "start_drill_pipe_psi": round(seg.start_pressure_psi, 1),
                "end_drill_pipe_psi": round(seg.end_pressure_psi, 1),
                "psi_per_100_strokes": round(seg.slope_psi_per_100_strokes, 2),
                "pressure_reverses": seg.pressure_rises,
            }
            for seg in segments
        ],
        "notes": list(plan.notes),
    }

    if include_strip_then_kill and bit_off_bottom_ft > 0:
        sequence = strip_then_kill(well, kill_method_key=follow_on_kill_method)
        result["strip_then_kill_sequence"] = {
            "usable": sequence.usable,
            "worst_phase": sequence.worst_phase,
            "total_hours": round(sequence.total_hours, 2),
            "peak_shoe_pressure_psi": (
                round(sequence.peak_shoe_pressure_psi)
                if sequence.peak_shoe_pressure_psi is not None
                else None
            ),
            "blockers": sequence.blockers,
            "warnings": sequence.warnings,
            "summary": sequence.summary(),
        }

    return result


def plan_stripping_and_snubbing(
    pipe_od_in: float = 5.0,
    pipe_id_in: float = 4.276,
    pipe_weight_lb_per_ft: float = 19.5,
    stand_length_ft: float = 93.0,
    start_depth_md_ft: float = 6000.0,
    target_depth_md_ft: float = 10000.0,
    annular_capacity_bbl_per_ft: float = 0.0459,
    mud_weight_ppg: float = 10.5,
    surface_pressure_psi: float = 900.0,
    direction: str = "in",
    has_float: bool = True,
    migration_rate_ft_per_hr: float = 0.0,
    minutes_per_stand: float = 5.0,
    gas_volume_bbl: float = 20.0,
    running_speed_ft_per_min: float = 30.0,
    hole_id_in: float = 8.5,
    plastic_viscosity_cp: float = 18.0,
    yield_point_lbf_100ft2: float = 14.0,
) -> dict[str, Any]:
    """Compute CWI stripping and snubbing forces, balance point, and bleed schedule.

    Determines whether wellhead pressure acting on the closed-end (or open-end)
    pipe area outweighs the buoyed string weight (requiring a snubbing unit),
    computes the exact balance point depth, closed-end vs. open-end displacement,
    gas migration bleed allowance per stand, surge pressure estimate, and the
    surface pressure jump if a single stand is stripped without bleeding.
    """
    strip_dir = (
        StripDirection.IN
        if direction.lower().strip() == "in"
        else StripDirection.OUT
    )
    op = StrippingOperation(
        pipe_od_in=pipe_od_in,
        pipe_id_in=pipe_id_in,
        pipe_weight_lb_per_ft=pipe_weight_lb_per_ft,
        stand_length_ft=stand_length_ft,
        start_depth_md_ft=start_depth_md_ft,
        target_depth_md_ft=target_depth_md_ft,
        annular_capacity_bbl_per_ft=annular_capacity_bbl_per_ft,
        mud_weight_ppg=mud_weight_ppg,
        surface_pressure_psi=surface_pressure_psi,
        direction=strip_dir,
        has_float=has_float,
        migration_rate_ft_per_hr=migration_rate_ft_per_hr,
        minutes_per_stand=minutes_per_stand,
    )
    steps = op.schedule()

    missed_stand_psi: float | None = None
    if gas_volume_bbl > op.volume_per_stand_bbl and surface_pressure_psi >= 0:
        try:
            missed_stand_psi = round(
                pressure_rise_if_not_bled(
                    op.volume_per_stand_bbl, gas_volume_bbl, surface_pressure_psi
                ),
                1,
            )
        except ValueError:
            missed_stand_psi = None

    rheology_model = BinghamPlastic(
        plastic_viscosity_cp=plastic_viscosity_cp,
        yield_point_lb_100ft2=yield_point_lbf_100ft2,
    )
    surge_psi = round(
        surge_pressure_estimate(
            pipe_speed_ft_per_min=running_speed_ft_per_min,
            hole_id_in=hole_id_in,
            pipe_od_in=pipe_od_in,
            length_ft=max(start_depth_md_ft, target_depth_md_ft),
            model=rheology_model,
            mud_weight_ppg=mud_weight_ppg,
        ),
        1,
    )

    return {
        "summary": op.summary(),
        "physics": {
            "buoyancy_factor": round(op.buoyancy_factor, 4),
            "buoyed_weight_lb_per_ft": round(
                op.pipe_weight_lb_per_ft * op.buoyancy_factor, 2
            ),
            "upward_pressure_force_lbf": round(op.upward_force_lbf, 1),
            "balance_point_md_ft": round(op.balance_point_ft, 1),
            "snubbing_required": op.snubbing_required,
            "recommended_technique": op.recommended_technique.value,
            "recommended_technique_label": op.recommended_technique.label,
            "closed_end_displacement_bbl_per_ft": round(
                op.displacement_bbl_per_ft, 5
            ),
            "open_end_displacement_bbl_per_ft": round(
                op.open_ended_displacement_bbl_per_ft, 5
            ),
            "displacement_per_stand_bbl": round(op.volume_per_stand_bbl, 3),
            "migration_bleed_per_stand_bbl": round(
                op.migration_bleed_per_stand_bbl, 3
            ),
            "total_bleed_per_stand_bbl": round(op.total_bleed_per_stand_bbl, 3),
            "surface_pressure_if_one_stand_not_bled_psi": missed_stand_psi,
            "estimated_surge_pressure_psi": surge_psi,
        },
        "schedule_preview": [
            {
                "stand": s.stand,
                "pipe_depth_md_ft": round(s.pipe_depth_md_ft, 1),
                "displacement_bbl": round(s.displacement_bbl, 2),
                "migration_bleed_bbl": round(s.migration_bleed_bbl, 2),
                "total_bleed_bbl": round(s.total_bleed_bbl, 2),
                "cumulative_bleed_bbl": round(s.cumulative_bleed_bbl, 2),
                "needs_snubbing": s.needs_snubbing,
                "snub_force_lbf": round(s.snub_force_lbf, 0),
            }
            for s in steps[:: max(1, len(steps) // 15)]
        ],
    }


def simulator_list_scenarios() -> list[dict[str, Any]]:
    """List all 10 built-in well control simulator scenarios and training objectives."""
    return [scenario.summary() for scenario in SCENARIOS]


def simulator_create_or_step(
    session_id: str | None = None,
    scenario: str = "drillers",
    choke_percent: float | None = None,
    pump_spm: float | None = None,
    strip_fpm: float | None = None,
    open_valves: list[str] | None = None,
    close_valves: list[str] | None = None,
    advance_seconds: float = 0.0,
    include_debrief: bool = False,
) -> dict[str, Any]:
    """Create or step a live forward-dynamic well control simulator session.

    Allows an AI agent to operate the rig floor controls (remote choke, mud pump,
    BOP stack & manifold valves, and stripping drawworks), advance simulated
    well time, inspect surface gauges and the latched kill sheet, and request a
    graded debrief against the scenario standard.
    """
    if session_id is None or session_id not in _SIM_SESSIONS:
        session = Session.for_scenario(scenario)
        sid = session_id or session.session_id
        _SIM_SESSIONS[sid] = session
    else:
        sid = session_id
        session = _SIM_SESSIONS[sid]

    if open_valves:
        for valve_name in open_valves:
            session.set_valve(valve_name, ValveState.OPEN)
    if close_valves:
        for valve_name in close_valves:
            session.set_valve(valve_name, ValveState.CLOSED)
    if choke_percent is not None:
        session.set_choke(float(choke_percent))
    if pump_spm is not None:
        session.set_pump(float(pump_spm))
    if strip_fpm is not None:
        session.strip(float(strip_fpm))

    if advance_seconds > 0:
        session.simulator.run(float(advance_seconds), dt=0.1)

    response: dict[str, Any] = {
        "session_id": sid,
        "scenario": session.scenario.summary() if session.scenario else None,
        "gauges": session.gauges(),
        "killsheet": session.kill_sheet(),
        "events": session.events_since(0)["events"][-15:],
    }
    if include_debrief:
        response["debrief"] = session.debrief()
    return response


def build_mcp_server() -> Any:
    """Create and configure the MCP server instance registering all wellcontrol tools.

    Supports both ``mcp>=2.0`` (``MCPServer``) and ``mcp 1.x`` (``FastMCP``).
    """
    try:
        from mcp.server.mcpserver import MCPServer as _ServerClass
    except ImportError:
        from mcp.server.fastmcp import FastMCP as _ServerClass  # type: ignore[no-redef]

    server = _ServerClass("wellcontrol")
    server.tool()(evaluate_kill_methods)
    server.tool()(plan_well_kill)
    server.tool()(plan_stripping_and_snubbing)
    server.tool()(simulator_list_scenarios)
    server.tool()(simulator_create_or_step)
    return server


def main() -> None:
    """Run the wellcontrol MCP server over stdio."""
    server = build_mcp_server()
    server.run()


if __name__ == "__main__":
    main()
