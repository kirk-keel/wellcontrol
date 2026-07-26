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
        body = client.post("/api/sessions", json={"shut_in": True}).json()
        assert "choke" in body["gauges"]["returns"]

    def test_drilling_start_is_available(self, client):
        body = client.post("/api/sessions", json={"shut_in": False}).json()
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


class TestPanel:
    def test_the_panel_is_served(self, client):
        response = client.get("/")
        assert response.status_code == 200
        assert "Choke Panel" in response.text

    def test_the_panel_is_self_contained(self, client):
        """No CDN: the rig has no internet and neither should this."""
        text = client.get("/").text
        assert "http://" not in text.replace("http://127.0.0.1", "")
        assert "https://" not in text

    def test_the_panel_shows_the_instrument_scan(self, client):
        """Drill pipe, casing, strokes and choke in one view -- the whole point."""
        text = client.get("/").text
        for element in ("g-dp", "g-csg", "g-stk", "g-chk"):
            assert element in text
