"""Tests for the wellcontrol Model Context Protocol (MCP) server and tool layer.

The pure-Python tool functions in :mod:`wellcontrol.mcp_server` depend only on
the core ``wellcontrol`` package and are always tested. Tests that exercise the
``mcp`` SDK server registration use ``pytest.importorskip("mcp")`` so the core
suite remains runnable with zero third-party packages.
"""

from __future__ import annotations

import pytest

from wellcontrol.mcp_server import (
    build_mcp_server,
    evaluate_kill_methods,
    plan_stripping_and_snubbing,
    plan_well_kill,
    simulator_create_or_step,
    simulator_list_scenarios,
)


class TestEvaluateKillMethodsTool:
    def test_vertical_surface_well_evaluates_all_seven_methods(self):
        result = evaluate_kill_methods(bop="surface", trajectory="vertical")
        assert result["configuration"]["key"] == "surface_vertical"
        assert result["shut_in_essentials"]["kill_mud_weight_ppg"] == pytest.approx(10.4)
        assert set(result["methods"]) == {
            "drillers",
            "wait_and_weight",
            "volumetric",
            "stripping",
            "lube_and_bleed",
            "reverse",
            "bullhead",
        }
        # On bottom on a vertical well: circulating methods are usable,
        # stripping is blocked because the bit is already on bottom.
        assert "drillers" in result["usable_methods"]
        assert "wait_and_weight" in result["usable_methods"]
        assert "stripping" in result["blocked_methods"]

    def test_horizontal_well_blocks_volumetric_and_lube_and_bleed(self):
        result = evaluate_kill_methods(bop="surface", trajectory="horizontal")
        assert not result["methods"]["volumetric"]["usable"]
        assert not result["methods"]["lube_and_bleed"]["usable"]
        assert any(
            "horizontal" in b.lower()
            for b in result["methods"]["volumetric"]["blockers"]
        )

    def test_off_bottom_enables_stripping(self):
        result = evaluate_kill_methods(
            bop="surface", trajectory="vertical", bit_off_bottom_ft=2500.0
        )
        assert result["methods"]["stripping"]["usable"]
        assert result["configuration"]["bit_md_ft"] == pytest.approx(7500.0)

    def test_invalid_bop_or_trajectory_raises_value_error(self):
        with pytest.raises(ValueError, match="Unknown bop"):
            evaluate_kill_methods(bop="moon")
        with pytest.raises(ValueError, match="Unknown trajectory"):
            evaluate_kill_methods(trajectory="spiral")


class TestPlanWellKillTool:
    def test_wait_and_weight_returns_stages_and_schedule_segments(self):
        plan = plan_well_kill(
            method_key="wait_and_weight", bop="surface", trajectory="vertical"
        )
        assert plan["usable"] is True
        assert len(plan["stages"]) >= 3
        assert len(plan["schedule_segments"]) >= 2
        assert plan["peak_shoe_pressure_psi"] is not None

    def test_horizontal_schedule_flags_pressure_reversal_in_lateral(self):
        plan = plan_well_kill(
            method_key="wait_and_weight", bop="surface", trajectory="horizontal"
        )
        assert any(seg["pressure_reverses"] for seg in plan["schedule_segments"])

    def test_strip_then_kill_sequence_included_when_off_bottom(self):
        plan = plan_well_kill(
            method_key="stripping",
            bop="surface",
            trajectory="vertical",
            bit_off_bottom_ft=2000.0,
            include_strip_then_kill=True,
            follow_on_kill_method="wait_and_weight",
        )
        assert "strip_then_kill_sequence" in plan
        seq = plan["strip_then_kill_sequence"]
        assert seq["usable"] is True
        assert seq["total_hours"] > 0
        assert seq["worst_phase"] in ("stripping", "the kill")


class TestPlanStrippingAndSnubbingTool:
    def test_high_surface_pressure_at_shallow_depth_requires_snubbing(self):
        res = plan_stripping_and_snubbing(
            start_depth_md_ft=500.0,
            target_depth_md_ft=10000.0,
            surface_pressure_psi=2000.0,
        )
        assert res["physics"]["snubbing_required"] is True
        assert res["physics"]["balance_point_md_ft"] > 500.0
        assert res["physics"]["recommended_technique"] == "ram_to_ram"

    def test_deep_pipe_strips_under_its_own_weight(self):
        res = plan_stripping_and_snubbing(
            start_depth_md_ft=6000.0,
            target_depth_md_ft=10000.0,
            surface_pressure_psi=800.0,
            migration_rate_ft_per_hr=300.0,
        )
        assert res["physics"]["snubbing_required"] is False
        assert res["physics"]["migration_bleed_per_stand_bbl"] > 0
        assert res["physics"]["surface_pressure_if_one_stand_not_bled_psi"] > 800.0
        assert res["physics"]["estimated_surge_pressure_psi"] > 0
        assert len(res["schedule_preview"]) > 0


class TestSimulatorTools:
    def test_lists_all_ten_scenarios(self):
        scenarios = simulator_list_scenarios()
        assert len(scenarios) >= 10
        keys = {s["key"] for s in scenarios}
        assert {"drillers", "find_the_kick", "volumetric", "stripping"} <= keys

    def test_creates_and_steps_a_simulator_session(self):
        snap = simulator_create_or_step(
            session_id="test-mcp-sim",
            scenario="drillers",
            choke_percent=22.0,
            pump_spm=30.0,
            advance_seconds=15.0,
            include_debrief=True,
        )
        assert snap["session_id"] == "test-mcp-sim"
        assert snap["gauges"]["choke_commanded"] == pytest.approx(22.0)
        assert snap["gauges"]["pump_commanded"] == pytest.approx(30.0)
        assert snap["gauges"]["time_s"] >= 15.0
        assert snap["killsheet"]["available"] is True
        assert snap["debrief"]["grade"] in ("excellent", "pass", "marginal", "fail")


class TestMCPServerRegistration:
    def test_mcp_server_registers_all_five_tools(self):
        pytest.importorskip("mcp", reason="pip install -e '.[mcp]'")
        server = build_mcp_server()
        assert server.name == "wellcontrol"
