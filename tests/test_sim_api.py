"""The HTTP layer.

Skipped when FastAPI is absent, so the core suite stays dependency-free --
the same arrangement ``test_streamlit_app.py`` uses for Streamlit.

**Everything here is transport.** The physics is tested in ``test_simulator.py``
and the time model in ``test_session.py``; what these check is that a request
reaches the right session method and that the result serialises. Anything that
looks like a well control decision in this file would mean logic had leaked into
the API layer.
"""

from __future__ import annotations

import pytest

fastapi = pytest.importorskip("fastapi", reason="pip install -e '.[sim]'")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from wellcontrol.sim import api  # noqa: E402


@pytest.fixture
def client():
    with TestClient(api.app) as test_client:
        yield test_client


@pytest.fixture
def session_id(client):
    response = client.post("/api/sessions", json={})
    assert response.status_code == 201
    return response.json()["session_id"]


class TestSessionLifecycle:
    def test_creating_a_session_returns_gauges_and_lineup(self, client):
        body = client.post("/api/sessions", json={}).json()
        assert body["session_id"]
        assert body["gauges"]["casing_psi"] > 0
        assert any(v["name"] == "annular" for v in body["lineup"])

    def test_a_new_session_starts_shut_in_and_lined_up(self, client):
        body = client.post("/api/sessions", json={"start": "shut_in"}).json()
        assert "choke" in body["gauges"]["returns"]

    def test_drilling_start_is_available(self, client):
        body = client.post("/api/sessions", json={"start": "drilling"}).json()
        assert "flowline" in body["gauges"]["returns"]

    @pytest.mark.parametrize("bop", ["surface", "subsea"])
    @pytest.mark.parametrize(
        "trajectory", ["vertical", "deviated", "horizontal"]
    )
    def test_every_configuration_can_be_created(self, client, bop, trajectory):
        response = client.post(
            "/api/sessions", json={"bop": bop, "trajectory": trajectory}
        )
        assert response.status_code == 201

    def test_an_unknown_configuration_is_rejected(self, client):
        response = client.post("/api/sessions", json={"bop": "underground"})
        assert response.status_code == 422

    def test_a_missing_session_is_a_404(self, client):
        assert client.get("/api/sessions/nope").status_code == 404

    def test_a_session_can_be_ended(self, client, session_id):
        assert client.delete(f"/api/sessions/{session_id}").status_code == 204
        assert client.get(f"/api/sessions/{session_id}").status_code == 404

    def test_sessions_are_independent(self, client):
        first = client.post("/api/sessions", json={}).json()["session_id"]
        second = client.post("/api/sessions", json={}).json()["session_id"]
        client.post(f"/api/sessions/{first}/choke", json={"percent": 40.0})
        other = client.get(f"/api/sessions/{second}").json()
        assert other["gauges"]["choke_commanded"] == 0.0


class TestScenarioLibrary:
    def test_the_library_is_published(self, client):
        body = client.get("/api/scenarios").json()["scenarios"]
        assert len(body) >= 8
        assert any(s["key"] == "drillers" for s in body)

    def test_a_session_can_be_built_from_one(self, client):
        body = client.post("/api/sessions", json={"scenario": "stripping"}).json()
        assert body["scenario"]["key"] == "stripping"
        assert body["gauges"]["bit_md_ft"] < 10000

    def test_an_unknown_scenario_is_a_404_naming_the_options(self, client):
        response = client.post("/api/sessions", json={"scenario": "nope"})
        assert response.status_code == 404
        assert "drillers" in response.json()["detail"]

    def test_the_listing_does_not_reveal_the_faults(self, client):
        """Only that there are some. Which and when is the exercise."""
        for s in client.get("/api/scenarios").json()["scenarios"]:
            assert "faults" not in s
            assert isinstance(s["has_faults"], bool)

    def test_the_debrief_defaults_to_the_scenarios_standard(self, client):
        created = client.post("/api/sessions", json={"scenario": "drillers"}).json()
        body = client.get(
            f"/api/sessions/{created['session_id']}/debrief"
        ).json()
        assert body["scenario"]["key"] == "drillers"

    def test_the_panel_offers_the_library(self, client):
        text = client.get("/").text
        assert "/api/scenarios" in text
        assert "brief-obj" in text


class TestSnapshot:
    def test_snapshot_carries_gauges_events_and_trace(self, client, session_id):
        body = client.get(f"/api/sessions/{session_id}").json()
        assert set(body) >= {"session_id", "gauges", "events", "trace"}

    def test_events_are_incremental(self, client, session_id):
        first = client.get(f"/api/sessions/{session_id}").json()["events"]
        index = first["next_index"]
        again = client.get(
            f"/api/sessions/{session_id}?since_event={index}"
        ).json()["events"]
        assert again["events"] == []
        assert again["next_index"] == index

    def test_trace_limit_is_honoured(self, client, session_id):
        body = client.get(f"/api/sessions/{session_id}?trace_limit=1").json()
        assert len(body["trace"]) <= 1


class TestControls:
    def test_choke_position_is_commanded(self, client, session_id):
        body = client.post(
            f"/api/sessions/{session_id}/choke", json={"percent": 35.0}
        ).json()
        assert body["gauges"]["choke_commanded"] == pytest.approx(35.0)

    def test_choke_beyond_the_stops_is_rejected(self, client, session_id):
        for bad in (-1.0, 101.0):
            response = client.post(
                f"/api/sessions/{session_id}/choke", json={"percent": bad}
            )
            assert response.status_code == 422

    def test_pump_speed_is_commanded(self, client, session_id):
        body = client.post(
            f"/api/sessions/{session_id}/pump", json={"spm": 30.0}
        ).json()
        assert body["gauges"]["pump_commanded"] == pytest.approx(30.0)

    def test_valves_can_be_operated(self, client, session_id):
        body = client.post(
            f"/api/sessions/{session_id}/valve",
            json={"name": "annular", "state": "open"},
        ).json()
        states = {v["name"]: v["state"] for v in body["lineup"]}
        assert states["annular"] == "open"

    def test_an_unknown_valve_is_a_404_naming_the_options(self, client, session_id):
        response = client.post(
            f"/api/sessions/{session_id}/valve",
            json={"name": "magic_valve", "state": "open"},
        )
        assert response.status_code == 404
        assert "annular" in response.json()["detail"]

    def test_an_unknown_valve_state_is_rejected(self, client, session_id):
        response = client.post(
            f"/api/sessions/{session_id}/valve",
            json={"name": "annular", "state": "ajar"},
        )
        assert response.status_code == 422

    def test_speed_can_be_changed(self, client, session_id):
        body = client.post(
            f"/api/sessions/{session_id}/speed", json={"speed": 10.0}
        ).json()
        assert body["gauges"]["speed"] == pytest.approx(10.0)

    def test_the_available_speeds_are_published(self, client):
        assert 0.0 in client.get("/api/speeds").json()["speeds"]

    def test_mud_weight_can_be_commanded(self, client, session_id):
        body = client.post(
            f"/api/sessions/{session_id}/mud-weight", json={"ppg": 11.5}
        ).json()
        assert body["gauges"]["active_mud_weight_ppg"] == pytest.approx(11.5)

    def test_trip_tank_and_pits_can_be_zeroed(self, client, session_id):
        res_tt = client.post(f"/api/sessions/{session_id}/zero-trip-tank")
        assert res_tt.status_code == 200
        res_pit = client.post(f"/api/sessions/{session_id}/zero-pits")
        assert res_pit.status_code == 200


class TestTheRigScreenEndpoints:
    def test_pipe_can_be_stripped(self, client, session_id):
        body = client.post(
            f"/api/sessions/{session_id}/strip", json={"feet_per_min": 30.0}
        ).json()
        assert body["gauges"]["strip_rate_ft_per_min"] == pytest.approx(30.0)

    def test_an_absurd_pipe_speed_is_rejected(self, client, session_id):
        response = client.post(
            f"/api/sessions/{session_id}/strip", json={"feet_per_min": 5000.0}
        )
        assert response.status_code == 422

    def test_the_schematic_describes_the_hole(self, client, session_id):
        body = client.get(f"/api/sessions/{session_id}/schematic").json()
        assert body["hole_md_ft"] > 0
        assert body["visible"] is True
        assert any(z["label"] == "influx" for z in body["annulus_zones"])

    def test_the_schematic_is_withheld_while_detecting(self, client):
        created = client.post("/api/sessions", json={"start": "drilling"}).json()
        body = client.get(
            f"/api/sessions/{created['session_id']}/schematic"
        ).json()
        assert body["visible"] is False
        assert "annulus_zones" not in body

    def test_the_kill_sheet_is_the_librarys_own(self, client, session_id):
        body = client.get(f"/api/sessions/{session_id}/killsheet").json()
        for key in ("kill_mud_weight_ppg", "icp_psi", "fcp_psi",
                    "total_strokes", "maasp_psi", "schedule", "target_dp_psi"):
            assert body[key] is not None
        assert body["icp_psi"] > body["fcp_psi"]
        assert len(body["schedule"]) > 0
        assert body["schedule"][0]["strokes"] == 0
        assert body["schedule"][0]["target_dp_psi"] == body["icp_psi"]

    def test_a_drilling_session_has_no_kill_sheet_yet(self, client):
        """Inventing one would hand over the exercise."""
        created = client.post("/api/sessions", json={"start": "drilling"}).json()
        body = client.get(
            f"/api/sessions/{created['session_id']}/killsheet"
        ).json()
        assert body["available"] is False
        assert "shut" in body["reason"].lower()
        assert "kill_mud_weight_ppg" not in body

    def test_a_shut_in_session_says_the_readings_were_given(self, client, session_id):
        body = client.get(f"/api/sessions/{session_id}/killsheet").json()
        assert body["available"] is True
        assert body["readings_are_the_students"] is False

    def test_the_snapshot_carries_the_lineup_and_schematic(self, client, session_id):
        body = client.get(f"/api/sessions/{session_id}").json()
        assert body["lineup"] and body["schematic"]


class TestAccumulator:
    def test_it_starts_full(self, client, session_id):
        gauges = client.get(f"/api/sessions/{session_id}").json()["gauges"]
        assert gauges["accumulator_ok"] is True
        assert gauges["accumulator_fraction"] == pytest.approx(1.0)

    def test_operating_the_stack_costs_pressure(self, client, session_id):
        before = client.get(
            f"/api/sessions/{session_id}"
        ).json()["gauges"]["accumulator_psi"]
        body = client.post(
            f"/api/sessions/{session_id}/valve",
            json={"name": "annular", "state": "open"},
        ).json()
        assert body["gauges"]["accumulator_psi"] < before

    def test_an_empty_accumulator_will_not_shift_an_element(self, client, session_id):
        """It simply does not move, in keeping with the rest of the lineup."""
        from wellcontrol.sim import api as api_module

        session = api_module.store.get(session_id)
        session.simulator.accumulator.pressure_psi = 0.0
        was_closed = session.simulator.flow_path.bop_is_closed
        client.post(
            f"/api/sessions/{session_id}/valve",
            json={"name": "annular", "state": "open"},
        )
        assert session.simulator.flow_path.bop_is_closed == was_closed


class TestDebrief:
    def test_debrief_is_available_immediately(self, client, session_id):
        body = client.get(f"/api/sessions/{session_id}/debrief").json()
        assert body["grade"] in ("excellent", "pass", "marginal", "fail")
        assert isinstance(body["metrics"], list)

    def test_requiring_a_kill_changes_the_verdict(self, client, session_id):
        lenient = client.get(f"/api/sessions/{session_id}/debrief").json()
        strict = client.get(
            f"/api/sessions/{session_id}/debrief?require_kill=true"
        ).json()
        assert strict["grade"] == "fail"
        assert lenient["grade"] != "fail"

    def test_metrics_name_their_limits(self, client, session_id):
        body = client.get(f"/api/sessions/{session_id}/debrief").json()
        named = {metric["name"] for metric in body["metrics"]}
        assert "Peak shoe pressure" in named


def _node() -> str | None:
    """Find node, including a winget install that is not yet on PATH."""
    import os
    import shutil
    from pathlib import Path

    found = shutil.which("node")
    if found:
        return found
    packages = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft/WinGet/Packages"
    if packages.is_dir():
        for candidate in packages.glob("OpenJS.NodeJS*/**/node.exe"):
            return str(candidate)
    return None


class TestThePanelScriptParses:
    """A syntax error in the page takes every screen down at once.

    It happened: a second ``const open`` in one block stopped the whole script
    parsing, so nothing initialised and every gauge on every screen read a dash
    -- while the API returned 200, the HTML was intact and the entire suite
    passed, because nothing in it runs the script.

    ``node --check`` is the real answer and is what this uses. It is skipped
    rather than approximated where node is absent: a hand-rolled substitute
    passed happily on the very error it was written for once the shape of the
    mistake changed.
    """

    def test_the_script_is_valid_javascript(self, client, tmp_path):
        node = _node()
        if node is None:
            pytest.skip("node not installed; winget install OpenJS.NodeJS.LTS")

        import subprocess

        script = client.get("/").text.split("<script>")[1].split("</script>")[0]
        path = tmp_path / "panel.js"
        path.write_text(script, encoding="utf-8")
        result = subprocess.run(
            [node, "--check", str(path)],
            capture_output=True, text=True, timeout=60,
        )
        assert result.returncode == 0, result.stderr

    def test_the_guard_would_catch_a_redeclaration(self, tmp_path):
        """The exact mistake that got through, so the guard is known to work."""
        node = _node()
        if node is None:
            pytest.skip("node not installed")

        import subprocess

        path = tmp_path / "bad.js"
        path.write_text(
            "function f(v) { const open = 1; const open = 2; return open; }",
            encoding="utf-8",
        )
        result = subprocess.run(
            [node, "--check", str(path)],
            capture_output=True, text=True, timeout=60,
        )
        assert result.returncode != 0
        assert "already been declared" in result.stderr


class TestScreens:
    """Every screen in the design doc is present and reachable."""

    def test_the_panel_is_served(self, client):
        response = client.get("/")
        assert response.status_code == 200
        assert "Well Control Simulator" in response.text

    def test_all_seven_screens_exist(self, client):
        text = client.get("/").text
        for screen in ("driller", "choke", "bop", "manifolds", "well",
                       "sheet", "debrief"):
            assert f'data-screen="{screen}"' in text
            assert f'id="s-{screen}"' in text

    def test_both_bop_panels_are_drawn(self, client):
        """A rig has two: a red remote panel, and a subsea monitoring screen."""
        text = client.get("/").text
        assert "function drawSurfaceBop(" in text
        assert "function drawSubseaBop(" in text
        assert "function drawBopPanel(" in text

    def test_the_panel_follows_the_well(self, client):
        """Surface wells get the remote panel; subsea wells get the screen."""
        surface = client.post(
            "/api/sessions", json={"bop": "surface"}
        ).json()["gauges"]
        subsea = client.post(
            "/api/sessions", json={"bop": "subsea"}
        ).json()["gauges"]
        assert surface["is_subsea"] is False
        assert subsea["is_subsea"] is True

    def test_both_manifolds_are_drawn(self, client):
        text = client.get("/").text
        assert "function drawStandpipeManifold(" in text
        assert "function drawChokeKillManifold(" in text
        assert 'id="standpipe"' in text
        assert 'id="ckmanifold"' in text

    def test_the_drillers_console_carries_its_instruments(self, client):
        text = client.get("/").text
        for element in ("d-spp", "d-spm", "d-pit", "d-flow", "d-hook", "d-tt"):
            assert element in text

    def test_stripping_is_operable(self, client):
        """The engine has supported it for a while; the panel now reaches it."""
        text = client.get("/").text
        assert 'id="strip"' in text
        assert 'data-strip="30"' in text

    def test_the_schematics_are_drawn(self, client):
        text = client.get("/").text
        assert 'id="pid"' in text
        assert 'id="schematic"' in text

    def test_the_accumulator_is_shown(self, client):
        assert "acc-psi" in client.get("/").text

    def test_the_pressure_gauges_are_dials(self, client):
        """A needle shows the rate and which way it is going without being read.

        The panel is built the way a rig builds it -- see simulator_screens/ for
        the references it is drawn from.
        """
        text = client.get("/").text
        assert "function dial(" in text
        for slot in ("dial-dp", "dial-csg", "dial-spm", "dial-choke"):
            assert slot in text

    def test_the_bop_stack_is_drawn_in_elevation(self, client):
        """Not a list of words: a student who shut the wrong element sees it.

        Both panels draw it -- the surface one alongside its selectors, the
        subsea one with position and health per pod.
        """
        text = client.get("/").text
        assert 'id="bop-panel"' in text
        for panel in ("function drawSurfaceBop(", "function drawSubseaBop("):
            assert panel in text
            body = text.split(panel)[1][:2600]
            # Rams that meet across the bore when shut and draw back when open.
            assert "shut ?" in body

    def test_the_guide_screen_is_present(self, client):
        text = client.get("/").text
        assert 'data-screen="guide"' in text
        assert 'id="s-guide"' in text
        assert "guide-checklist" in text
        assert "function renderGuide(" in text

    def test_mud_weight_and_schedule_controls_in_panel(self, client):
        text = client.get("/").text
        assert 'id="btn-set-mw"' in text
        assert 'id="btn-zero-pit"' in text
        assert 'id="btn-zero-tt"' in text
        assert 'id="sheet-schedule"' in text


class TestPanel:

    def test_the_panel_is_self_contained(self, client):
        """No CDN: the rig has no internet and neither should this."""
        text = client.get("/").text
        assert "http://" not in text.replace("http://127.0.0.1", "")
        assert "https://" not in text

    def test_the_panel_shows_the_instrument_scan(self, client):
        """Four gauges in one view -- the scan a student has to build."""
        text = client.get("/").text
        for element in ("g-dp", "g-csg", "g-stk", "g-chk"):
            assert element in text

    def test_the_panel_offers_the_exercise_picker(self, client):
        """Populated from the library rather than hard-coded."""
        text = client.get("/").text
        assert 'id="scenario"' in text
        assert "loadScenarios" in text


class TestMultiMonitorCockpit:
    """Multi-monitor detached cockpit and popout windows."""

    def test_multi_monitor_menu_and_actions(self, client):
        text = client.get("/").text
        assert "btn-multimonitor" in text
        assert "multimonitor-menu" in text
        assert "mm-launch-suite" in text
        for scr in ("choke", "driller", "manifolds", "well", "bop", "sheet"):
            assert f'data-pop="{scr}"' in text

    def test_popout_banner_and_station_controls(self, client):
        text = client.get("/").text
        assert "popout-banner" in text
        assert "popout-station-badge" in text
        assert "popout-live-sync" in text
        assert "popout-btn-fullscreen" in text
        assert "popout-btn-close" in text
        assert "btn-popout-current" in text

    def test_cross_window_sync_channel_present(self, client):
        text = client.get("/").text
        assert "wellcontrol_cockpit_sync" in text
        assert "BroadcastChannel" in text
        assert "launch3ScreenSuite" in text
        assert "popOutScreen" in text


class TestWhatTheStudentCanSee:
    """A rig has no bottomhole gauge; nor does the panel until it is earned."""

    def test_a_drilling_start_withholds_the_downhole_truth(self, client):
        body = client.post("/api/sessions", json={"start": "drilling"}).json()
        gauges = body["gauges"]
        assert gauges["downhole_visible"] is False
        assert gauges["bottomhole_psi"] is None
        assert gauges["formation_psi"] is None

    def test_a_drilling_start_still_shows_the_rig_instruments(self, client):
        gauges = client.post(
            "/api/sessions", json={"start": "drilling"}
        ).json()["gauges"]
        for key in ("drill_pipe_psi", "casing_psi", "pit_gain_bbl",
                    "flow_out_bpm"):
            assert gauges[key] is not None

    def test_a_shut_in_start_shows_it(self, client):
        gauges = client.post(
            "/api/sessions", json={"start": "shut_in"}
        ).json()["gauges"]
        assert gauges["downhole_visible"] is True
        assert gauges["bottomhole_psi"] is not None


class TestTeacherConsole:
    def test_teacher_page_is_served(self, client):
        r = client.get("/teacher")
        assert r.status_code == 200
        text = r.text
        assert "INSTRUCTOR MASTER STATION" in text
        assert "student-grid" in text
        assert "modal-fault" in text
        assert "modal-whiteboard" in text

    def test_multi_student_dashboard_endpoint(self, client):
        client.post("/api/sessions", json={"scenario": "drillers", "student_name": "Alice"})
        client.post("/api/sessions", json={"scenario": "wait_and_weight", "student_name": "Bob"})
        r = client.get("/api/teacher/sessions")
        assert r.status_code == 200
        data = r.json()
        assert data["total"] >= 2
        names = [s["student_name"] for s in data["sessions"]]
        assert "Alice" in names
        assert "Bob" in names

        # Verify key metrics are present
        alice = next(s for s in data["sessions"] if s["student_name"] == "Alice")
        assert "bottomhole_psi" in alice
        assert "shoe_margin_psi" in alice
        assert "status" in alice
        assert "alarms" in alice
        assert "speed" in alice
        assert "is_frozen" in alice

    def test_spawn_demo_class(self, client):
        r = client.post("/api/teacher/spawn-demo-class")
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert data["spawned"] == 5
        assert len(data["sessions"]) >= 5

    def test_live_fault_injection(self, client):
        created = client.post("/api/sessions", json={"scenario": "drillers"}).json()
        sid = created["session_id"]

        # Inject pump failure
        r = client.post(
            f"/api/teacher/sessions/{sid}/fault",
            json={"kind": "pump_failure", "message": "Fluid end cracked"},
        )
        assert r.status_code == 200
        res = r.json()
        assert res["ok"] is True
        assert any("pump" in a["text"].lower() or "fault" in a["text"].lower() for a in res["session"]["alarms"])

        # Inject choke plugged
        r2 = client.post(
            f"/api/teacher/sessions/{sid}/fault",
            json={"kind": "choke_plugged"},
        )
        assert r2.status_code == 200

        # Inject mud weight drop
        r3 = client.post(
            f"/api/teacher/sessions/{sid}/fault",
            json={"kind": "mud_weight_drop"},
        )
        assert r3.status_code == 200

    def test_master_freeze_and_resume_all(self, client):
        client.post("/api/sessions", json={"student_name": "S1"})
        client.post("/api/sessions", json={"student_name": "S2"})

        # Master freeze
        r = client.post("/api/teacher/freeze-all")
        assert r.status_code == 200
        assert all(s["is_frozen"] is True for s in r.json()["sessions"])
        assert all(s["speed"] == 0.0 for s in r.json()["sessions"])

        # Master resume
        r2 = client.post("/api/teacher/resume-all")
        assert r2.status_code == 200
        assert all(s["is_frozen"] is False for s in r2.json()["sessions"])

    def test_remote_freeze_individual_student(self, client):
        created = client.post("/api/sessions", json={"student_name": "Target"}).json()
        sid = created["session_id"]

        # Freeze
        r = client.post(f"/api/teacher/sessions/{sid}/freeze", json={"freeze": True})
        assert r.status_code == 200
        assert r.json()["session"]["is_frozen"] is True
        assert r.json()["session"]["speed"] == 0.0

        # Resume
        r2 = client.post(f"/api/teacher/sessions/{sid}/freeze", json={"freeze": False})
        assert r2.status_code == 200
        assert r2.json()["session"]["is_frozen"] is False

    def test_rename_student_session(self, client):
        created = client.post("/api/sessions", json={}).json()
        sid = created["session_id"]

        r = client.post(f"/api/teacher/sessions/{sid}/name", json={"name": "Captain Morgan"})
        assert r.status_code == 200
        assert r.json()["session"]["student_name"] == "Captain Morgan"

    def test_ai_debrief_endpoint(self, client):
        created = client.post("/api/sessions", json={"scenario": "wait_and_weight"}).json()
        sid = created["session_id"]
        r = client.get(f"/api/sessions/{sid}/ai-debrief")
        assert r.status_code == 200
        data = r.json()
        assert "score" in data
        assert "letter_grade" in data
        assert "iwcf_standard" in data
        assert "executive_summary" in data
        assert len(data["categories"]) == 4
        assert isinstance(data["strengths"], list)
        assert isinstance(data["deductions"], list)
        assert isinstance(data["coaching_timeline"], list)

    def test_ai_debrief_with_drilling_kick(self, client):
        created = client.post("/api/sessions", json={"start": "drilling"}).json()
        sid = created["session_id"]
        # Induce kick and leave un-shut in
        client.post(f"/api/sessions/{sid}/pump", json={"spm": 60.0})
        client.post(f"/api/sessions/{sid}/speed", json={"speed": 10.0})
        r = client.get(f"/api/sessions/{sid}/ai-debrief")
        assert r.status_code == 200
        data = r.json()
        # Should have point deductions for kick detection or shut-in
        assert len(data["deductions"]) > 0
        assert data["score"] < 100

    def test_session_replay_endpoint(self, client):
        created = client.post("/api/sessions", json={"scenario": "drillers"}).json()
        sid = created["session_id"]
        # Advance slightly to log samples
        client.post(f"/api/sessions/{sid}/pump", json={"spm": 30.0})
        client.post(f"/api/sessions/{sid}/speed", json={"speed": 10.0})
        client.get(f"/api/sessions/{sid}")
        r = client.get(f"/api/sessions/{sid}/replay")
        assert r.status_code == 200
        data = r.json()
        assert data["session_id"] == sid
        assert "trace" in data
        assert "events" in data
        assert isinstance(data["trace"], list)

    def test_gradebook_endpoints(self, client):
        client.post("/api/sessions", json={"scenario": "drillers", "student_name": "Gradebook Test"})
        # JSON gradebook
        r = client.get("/api/teacher/gradebook")
        assert r.status_code == 200
        data = r.json()
        assert "entries" in data
        assert len(data["entries"]) >= 1
        entry = next(e for e in data["entries"] if e["student_name"] == "Gradebook Test")
        assert "score" in entry
        assert "letter_grade" in entry
        assert "iwcf_standard" in entry

        # CSV export
        r_csv = client.get("/api/teacher/gradebook.csv")
        assert r_csv.status_code == 200
        assert "text/csv" in r_csv.headers["content-type"]
        assert "Gradebook Test" in r_csv.text
        assert "student_name" in r_csv.text
