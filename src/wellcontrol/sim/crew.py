"""Crew Resource Management (CRM) & collaborative multi-user well control.

Enables multi-student team training conforming to IADC WellSharp and IWCF
standards. A session's well can be flown collaboratively by multiple crew
members with distinct rig roles:

* **Driller**: Controls mud pumps (SPM), drawworks (pipe movement/stripping),
  and monitors standpipe pressure, pit gain, and hookload.
* **Choke Operator**: Works the remote hydraulic choke, aligns the choke
  manifold, and holds casing/drill pipe pressure constant during circulation.
* **Toolpusher / Company Man**: Oversees well integrity, operates BOP stack
  elements (annular, rams), monitors MAASP and shoe fracture margin.
* **Mud Engineer / Derrickman**: Operates pit weighting, kill mud mixing,
  trip tank alignment, and mud-gas separator (MGS) seal leg.
* **Observer**: Read-only oversight for instructors and peer trainees.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class CrewRole(str, Enum):
    """Rig crew roles for collaborative well control simulation."""

    DRILLER = "driller"
    CHOKE_OPERATOR = "choke_operator"
    TOOLPUSHER = "toolpusher"
    MUD_ENGINEER = "mud_engineer"
    OBSERVER = "observer"

    @property
    def title(self) -> str:
        titles = {
            CrewRole.DRILLER: "Driller",
            CrewRole.CHOKE_OPERATOR: "Choke Operator",
            CrewRole.TOOLPUSHER: "Toolpusher / Rig Superintendent",
            CrewRole.MUD_ENGINEER: "Mud Engineer / Derrickman",
            CrewRole.OBSERVER: "Instructor / Observer",
        }
        return titles.get(self, self.value.replace("_", " ").title())

    @property
    def badge_color(self) -> str:
        colors = {
            CrewRole.DRILLER: "#3b82f6",       # Blue
            CrewRole.CHOKE_OPERATOR: "#f59e0b", # Amber
            CrewRole.TOOLPUSHER: "#ef4444",    # Red
            CrewRole.MUD_ENGINEER: "#10b981",  # Emerald
            CrewRole.OBSERVER: "#8b5cf6",      # Purple
        }
        return colors.get(self, "#64748b")


#: Standard rig-floor callouts per IADC / IWCF protocol
STANDARD_CALLOUTS = [
    {
        "code": "SPACE_OUT",
        "text": "Space out tool joint above rotary table, shut down pump!",
        "role": CrewRole.DRILLER.value,
    },
    {
        "code": "WELL_SHUT_IN",
        "text": "Annular preventer closed. Choke is shut. Well is shut in.",
        "role": CrewRole.TOOLPUSHER.value,
    },
    {
        "code": "PRESSURES_STABILIZED",
        "text": "Shut-in pressures stabilized. Recording SIDPP and SICP.",
        "role": CrewRole.CHOKE_OPERATOR.value,
    },
    {
        "code": "RAMPING_PUMP",
        "text": "Ramping pump to kill rate. Hold casing pressure constant!",
        "role": CrewRole.DRILLER.value,
    },
    {
        "code": "HOLDING_PRESSURE",
        "text": "Feathering choke. Casing pressure steady at target.",
        "role": CrewRole.CHOKE_OPERATOR.value,
    },
    {
        "code": "KILL_MUD_MIXED",
        "text": "Active pit weighted to kill mud density. Ready to pump.",
        "role": CrewRole.MUD_ENGINEER.value,
    },
    {
        "code": "GAS_AT_SURFACE",
        "text": "Gas breaking out at surface choke! Expect rapid expansion.",
        "role": CrewRole.CHOKE_OPERATOR.value,
    },
    {
        "code": "MUD_AT_BIT",
        "text": "Kill mud arrived at drill bit! Switching to DP schedule.",
        "role": CrewRole.DRILLER.value,
    },
    {
        "code": "WELL_DEAD",
        "text": "Kill mud to surface. Zero shut-in pressure. Well is dead.",
        "role": CrewRole.TOOLPUSHER.value,
    },
]


def can_operate(role: CrewRole | str, action: str) -> bool:
    """Check if the given crew role is authorized to perform an action."""
    r = CrewRole(role) if isinstance(role, str) else role

    if r == CrewRole.OBSERVER:
        return action == "callout"

    permissions: dict[CrewRole, set[str]] = {
        CrewRole.DRILLER: {
            "pump",
            "strip",
            "zero_pit",
            "zero_tt",
            "callout",
        },
        CrewRole.CHOKE_OPERATOR: {
            "choke",
            "choke_valve",
            "callout",
        },
        CrewRole.TOOLPUSHER: {
            "bop",
            "speed",
            "freeze",
            "callout",
        },
        CrewRole.MUD_ENGINEER: {
            "mud_weight",
            "kill_mud",
            "pit_valve",
            "zero_pit",
            "zero_tt",
            "callout",
        },
    }

    allowed = permissions.get(r, set())
    return action in allowed or action == "callout"


@dataclass
class CalloutMessage:
    """A rig intercom radio callout broadcast to the crew."""

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    timestamp: float = field(default_factory=time.time)
    sender_name: str = "Crew"
    role: CrewRole = CrewRole.DRILLER
    message: str = ""
    is_standard: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "timestamp": round(self.timestamp, 1),
            "time_str": time.strftime("%H:%M:%S", time.localtime(self.timestamp)),
            "sender_name": self.sender_name,
            "role": self.role.value,
            "role_title": self.role.title,
            "badge_color": self.role.badge_color,
            "message": self.message,
            "is_standard": self.is_standard,
        }


@dataclass
class CrewMember:
    """An active student/instructor participant in a crew room."""

    member_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    name: str = "Trainee"
    role: CrewRole = CrewRole.DRILLER
    joined_at: float = field(default_factory=time.time)
    websocket: Any = None  # WebSocket connection

    def to_dict(self) -> dict[str, Any]:
        return {
            "member_id": self.member_id,
            "name": self.name,
            "role": self.role.value,
            "role_title": self.role.title,
            "badge_color": self.role.badge_color,
            "joined_at": round(self.joined_at, 1),
        }


class CrewRoom:
    """A collaborative rig crew operating a specific session well."""

    def __init__(self, session_id: str) -> None:
        self.session_id: str = session_id
        self.members: dict[str, CrewMember] = {}
        self.callouts: list[CalloutMessage] = []
        self._max_callouts: int = 50

    def add_member(self, member: CrewMember) -> None:
        self.members[member.member_id] = member

    def remove_member(self, member_id: str) -> CrewMember | None:
        return self.members.pop(member_id, None)

    def get_member(self, member_id: str) -> CrewMember | None:
        return self.members.get(member_id)

    def post_callout(
        self,
        sender_name: str,
        role: CrewRole | str,
        message: str,
        is_standard: bool = False,
    ) -> CalloutMessage:
        r = CrewRole(role) if isinstance(role, str) else role
        callout = CalloutMessage(
            sender_name=sender_name,
            role=r,
            message=message,
            is_standard=is_standard,
        )
        self.callouts.append(callout)
        if len(self.callouts) > self._max_callouts:
            self.callouts = self.callouts[-self._max_callouts :]
        return callout

    def roster(self) -> list[dict[str, Any]]:
        return [m.to_dict() for m in self.members.values()]

    async def broadcast(self, message: dict[str, Any], exclude_id: str | None = None) -> None:
        """Broadcast JSON message to all connected members in room."""
        for m_id, member in list(self.members.items()):
            if exclude_id and m_id == exclude_id:
                continue
            ws = member.websocket
            if ws is not None:
                try:
                    await ws.send_json(message)
                except Exception:
                    # Stale or disconnected socket
                    pass


class CrewManager:
    """Manages multi-student crew rooms across active simulator sessions."""

    def __init__(self) -> None:
        self._rooms: dict[str, CrewRoom] = {}

    def get_or_create_room(self, session_id: str) -> CrewRoom:
        if session_id not in self._rooms:
            self._rooms[session_id] = CrewRoom(session_id)
        return self._rooms[session_id]

    def get_room(self, session_id: str) -> CrewRoom | None:
        return self._rooms.get(session_id)

    def drop_room(self, session_id: str) -> None:
        self._rooms.pop(session_id, None)

    def active_rooms_count(self) -> int:
        return len(self._rooms)
