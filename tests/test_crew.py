"""Tests for Crew CRM & Collaborative Multi-user Well Control."""

from __future__ import annotations

import pytest

fastapi = pytest.importorskip("fastapi", reason="pip install -e '.[sim]'")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from wellcontrol.sim import api  # noqa: E402
from wellcontrol.sim.crew import (  # noqa: E402
    CrewManager,
    CrewMember,
    CrewRole,
    CrewRoom,
    STANDARD_CALLOUTS,
    can_operate,
)


@pytest.fixture
def client():
    with TestClient(api.app) as test_client:
        yield test_client


@pytest.fixture
def session_id(client):
    response = client.post("/api/sessions", json={})
    assert response.status_code == 201
    return response.json()["session_id"]


class TestCrewRolesAndPermissions:
    def test_crew_roles_attributes(self):
        assert CrewRole.DRILLER.title == "Driller"
        assert CrewRole.CHOKE_OPERATOR.title == "Choke Operator"
        assert CrewRole.TOOLPUSHER.title == "Toolpusher / Rig Superintendent"
        assert CrewRole.MUD_ENGINEER.title == "Mud Engineer / Derrickman"
        assert CrewRole.OBSERVER.title == "Instructor / Observer"

        for role in CrewRole:
            assert role.badge_color.startswith("#")

    def test_standard_callouts_defined(self):
        assert len(STANDARD_CALLOUTS) >= 5
        codes = [c["code"] for c in STANDARD_CALLOUTS]
        assert "SPACE_OUT" in codes
        assert "WELL_SHUT_IN" in codes
        assert "PRESSURES_STABILIZED" in codes
        assert "RAMPING_PUMP" in codes
        assert "WELL_DEAD" in codes

    def test_driller_permissions(self):
        assert can_operate(CrewRole.DRILLER, "pump")
        assert can_operate(CrewRole.DRILLER, "strip")
        assert can_operate(CrewRole.DRILLER, "zero_pit")
        assert can_operate(CrewRole.DRILLER, "zero_tt")
        assert can_operate(CrewRole.DRILLER, "callout")
        assert not can_operate(CrewRole.DRILLER, "choke")
        assert not can_operate(CrewRole.DRILLER, "bop")
        assert not can_operate(CrewRole.DRILLER, "mud_weight")

    def test_choke_operator_permissions(self):
        assert can_operate(CrewRole.CHOKE_OPERATOR, "choke")
        assert can_operate(CrewRole.CHOKE_OPERATOR, "choke_valve")
        assert can_operate(CrewRole.CHOKE_OPERATOR, "callout")
        assert not can_operate(CrewRole.CHOKE_OPERATOR, "pump")
        assert not can_operate(CrewRole.CHOKE_OPERATOR, "bop")
        assert not can_operate(CrewRole.CHOKE_OPERATOR, "mud_weight")

    def test_toolpusher_permissions(self):
        assert can_operate(CrewRole.TOOLPUSHER, "bop")
        assert can_operate(CrewRole.TOOLPUSHER, "speed")
        assert can_operate(CrewRole.TOOLPUSHER, "freeze")
        assert can_operate(CrewRole.TOOLPUSHER, "callout")
        assert not can_operate(CrewRole.TOOLPUSHER, "pump")
        assert not can_operate(CrewRole.TOOLPUSHER, "choke")

    def test_mud_engineer_permissions(self):
        assert can_operate(CrewRole.MUD_ENGINEER, "mud_weight")
        assert can_operate(CrewRole.MUD_ENGINEER, "kill_mud")
        assert can_operate(CrewRole.MUD_ENGINEER, "pit_valve")
        assert can_operate(CrewRole.MUD_ENGINEER, "zero_pit")
        assert can_operate(CrewRole.MUD_ENGINEER, "zero_tt")
        assert can_operate(CrewRole.MUD_ENGINEER, "callout")
        assert not can_operate(CrewRole.MUD_ENGINEER, "choke")
        assert not can_operate(CrewRole.MUD_ENGINEER, "bop")

    def test_observer_permissions(self):
        assert can_operate(CrewRole.OBSERVER, "callout")
        assert not can_operate(CrewRole.OBSERVER, "pump")
        assert not can_operate(CrewRole.OBSERVER, "choke")
        assert not can_operate(CrewRole.OBSERVER, "bop")
        assert not can_operate(CrewRole.OBSERVER, "mud_weight")

    def test_string_role_coercion(self):
        assert can_operate("driller", "pump")
        assert not can_operate("driller", "choke")


class TestCrewRoomAndManager:
    def test_room_membership(self):
        room = CrewRoom("test-session")
        m1 = CrewMember(name="Alice", role=CrewRole.DRILLER)
        m2 = CrewMember(name="Bob", role=CrewRole.CHOKE_OPERATOR)

        room.add_member(m1)
        room.add_member(m2)
        assert len(room.roster()) == 2
        assert room.get_member(m1.member_id) is m1

        removed = room.remove_member(m1.member_id)
        assert removed is m1
        assert len(room.roster()) == 1

    def test_callouts_capacity(self):
        room = CrewRoom("test-session")
        room._max_callouts = 5
        for i in range(10):
            room.post_callout("Alice", CrewRole.DRILLER, f"Msg {i}")
        assert len(room.callouts) == 5
        assert room.callouts[-1].message == "Msg 9"

    def test_manager_lifecycle(self):
        mgr = CrewManager()
        assert mgr.active_rooms_count() == 0
        r1 = mgr.get_or_create_room("s1")
        assert mgr.active_rooms_count() == 1
        assert mgr.get_room("s1") is r1
        assert mgr.get_room("s2") is None

        mgr.drop_room("s1")
        assert mgr.active_rooms_count() == 0


class TestCrewRestApi:
    def test_crew_html_page_served(self, client):
        res = client.get("/crew")
        assert res.status_code == 200
        assert "Crew CRM" in res.text
        assert "Intercom" in res.text

    def test_get_roles(self, client):
        res = client.get("/api/crew/roles")
        assert res.status_code == 200
        roles = res.json()["roles"]
        role_names = [r["role"] for r in roles]
        assert "driller" in role_names
        assert "choke_operator" in role_names
        assert "toolpusher" in role_names
        assert "mud_engineer" in role_names
        assert "observer" in role_names

    def test_get_standard_callouts(self, client):
        res = client.get("/api/crew/callouts/standard")
        assert res.status_code == 200
        callouts = res.json()["callouts"]
        assert len(callouts) >= 5

    def test_roster_endpoint(self, client, session_id):
        res = client.get(f"/api/crew/{session_id}/roster")
        assert res.status_code == 200
        data = res.json()
        assert data["session_id"] == session_id
        assert isinstance(data["roster"], list)

    def test_roster_nonexistent_session(self, client):
        res = client.get("/api/crew/non-existent-id/roster")
        assert res.status_code == 404

    def test_post_and_get_callouts(self, client, session_id):
        post_res = client.post(
            f"/api/crew/{session_id}/callout",
            json={
                "sender_name": "Dave",
                "role": "toolpusher",
                "message": "Shut in confirmed on lower rams.",
                "is_standard": True,
            },
        )
        assert post_res.status_code == 200
        c = post_res.json()["callout"]
        assert c["sender_name"] == "Dave"
        assert c["role"] == "toolpusher"
        assert c["message"] == "Shut in confirmed on lower rams."

        get_res = client.get(f"/api/crew/{session_id}/callouts")
        assert get_res.status_code == 200
        callouts = get_res.json()["callouts"]
        assert len(callouts) >= 1
        assert any(x["message"] == "Shut in confirmed on lower rams." for x in callouts)


class TestCrewWebSocket:
    def test_websocket_join_and_init(self, client, session_id):
        with client.websocket_connect(
            f"/ws/crew/{session_id}?role=driller&name=Sarah"
        ) as ws:
            # 1st message: roster broadcast
            msg1 = ws.receive_json()
            assert msg1["type"] == "roster"
            assert "Sarah joined as Driller" in msg1["event"]

            # 2nd message: init payload
            msg2 = ws.receive_json()
            assert msg2["type"] == "init"
            assert msg2["member"]["name"] == "Sarah"
            assert msg2["member"]["role"] == "driller"
            assert "snapshot" in msg2

    def test_websocket_permitted_action(self, client, session_id):
        with client.websocket_connect(
            f"/ws/crew/{session_id}?role=driller&name=Sarah"
        ) as ws:
            # Consume initial handshake messages
            ws.receive_json()  # roster
            ws.receive_json()  # init

            # Driller adjusts pump SPM
            ws.send_json({"type": "action", "action": "pump", "params": {"spm": 35}})
            reply = ws.receive_json()
            assert reply["type"] == "telemetry"
            assert "Set pump rate to 35 SPM" in reply["event"]
            assert reply["snapshot"]["gauges"]["pump_commanded"] == 35

    def test_websocket_unauthorized_action(self, client, session_id):
        with client.websocket_connect(
            f"/ws/crew/{session_id}?role=driller&name=Sarah"
        ) as ws:
            ws.receive_json()  # roster
            ws.receive_json()  # init

            # Driller tries to adjust choke (unauthorized)
            ws.send_json(
                {"type": "action", "action": "choke", "params": {"position": 0.4}}
            )
            reply = ws.receive_json()
            assert reply["type"] == "error"
            assert "reserved for another rig role" in reply["message"]

    def test_websocket_multiplayer_callout_and_sync(self, client, session_id):
        with client.websocket_connect(
            f"/ws/crew/{session_id}?role=driller&name=Sarah"
        ) as ws_driller:
            ws_driller.receive_json()  # roster
            ws_driller.receive_json()  # init

            with client.websocket_connect(
                f"/ws/crew/{session_id}?role=choke_operator&name=Mike"
            ) as ws_choke:
                # ws_choke receives roster and init
                ws_choke.receive_json()  # roster
                ws_choke.receive_json()  # init

                # ws_driller receives notification of Mike joining
                join_msg = ws_driller.receive_json()
                assert join_msg["type"] == "roster"
                assert "Mike joined as Choke Operator" in join_msg["event"]

                # Mike sends an intercom radio callout
                ws_choke.send_json({
                    "type": "callout",
                    "message": "Holding casing pressure steady at 520 psi.",
                    "is_standard": False,
                })

                # Both should receive the callout broadcast
                callout_driller = ws_driller.receive_json()
                callout_choke = ws_choke.receive_json()
                assert callout_driller["type"] == "callout"
                assert callout_driller["callout"]["sender_name"] == "Mike"
                assert callout_driller["callout"]["message"] == (
                    "Holding casing pressure steady at 520 psi."
                )
                assert callout_choke["callout"]["message"] == (
                    "Holding casing pressure steady at 520 psi."
                )

                # Choke operator adjusts choke
                ws_choke.send_json({
                    "type": "action",
                    "action": "choke",
                    "params": {"percent": 30.0},
                })
                telemetry_driller = ws_driller.receive_json()
                telemetry_choke = ws_choke.receive_json()
                assert telemetry_driller["type"] == "telemetry"
                assert "Positioned choke to 30.0%" in telemetry_driller["event"]
                assert telemetry_choke["type"] == "telemetry"

                # Driller tests sync request
                ws_driller.send_json({"type": "sync"})
                sync_reply = ws_driller.receive_json()
                assert sync_reply["type"] == "telemetry"
                assert "snapshot" in sync_reply
