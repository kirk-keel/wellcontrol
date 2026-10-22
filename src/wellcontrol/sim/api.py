"""HTTP interface to the simulator.

Stage 3. **The UI is a client of the engine, not part of it.** Everything here
is transport: it parses a request, calls a :class:`~wellcontrol.sim.session.Session`
method, and serialises the result. No physics, no well control decisions, no
state beyond the session store. If a rule ever needs to live here, it belongs in
the library instead.

Why a web app rather than Streamlit: Streamlit reruns the whole script on every
interaction and has no game loop, so gauges would be widgets rather than
instruments and the choke would feel laggy. The choke is the instrument the
whole exercise turns on, so that is the wrong trade.

Run it with::

    .venv/Scripts/python.exe -m uvicorn wellcontrol.sim.api:app --reload

then open http://127.0.0.1:8000/. Binds to localhost only by default, as the
Streamlit launcher does.

FastAPI is an optional dependency: ``pip install -e ".[sim]"``. Nothing in the
core library imports this module, so the dependency-free suite is unaffected.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .session import SESSION_SPEEDS_DOC, SPEEDS, Session, SessionStore

STATIC = Path(__file__).resolve().parent / "static"

app = FastAPI(
    title="Well Control Simulator",
    description=(
        "Forward model of a rig under a student's hands. The well responds to "
        "what the student actually does, not what they intended."
    ),
    version="0.1.0",
)

store = SessionStore()


# --------------------------------------------------------------------------
# Request bodies
# --------------------------------------------------------------------------

class NewSession(BaseModel):
    scenario: str | None = Field(
        default=None,
        description=(
            "Key of a named exercise from /api/scenarios. When given it "
            "decides the well, the lineup and any faults, and the rest of "
            "this body is ignored."
        ),
    )
    student_name: str | None = Field(
        default=None,
        description="Optional name or callsign for the student session.",
    )
    bop: str = Field(default="surface", description="surface or subsea")
    trajectory: str = Field(
        default="vertical", description="vertical, deviated or horizontal"
    )
    start: str = Field(
        default="shut_in",
        description=(
            "shut_in hands over a kick already in the hole, with the well "
            "closed on it and the pressures on the gauges. drilling starts on "
            "a well that is behaving; the kick arrives later and the student "
            "has to spot it and shut in themselves."
        ),
    )


class ChokeCommand(BaseModel):
    percent: float = Field(ge=0.0, le=100.0)


class PumpCommand(BaseModel):
    spm: float = Field(ge=0.0, le=200.0)


class ValveCommand(BaseModel):
    name: str
    state: str = Field(description="open or closed")


class SpeedCommand(BaseModel):
    speed: float = Field(ge=0.0, le=240.0, description=SESSION_SPEEDS_DOC)


class StripCommand(BaseModel):
    feet_per_min: float = Field(
        ge=-120.0, le=120.0,
        description="Pipe speed through the stripping element. Positive runs in.",
    )


class MudWeightCommand(BaseModel):
    ppg: float = Field(
        ge=5.0, le=25.0,
        description="Mud weight in active pits (ppg).",
    )


class FaultInjectionCommand(BaseModel):
    kind: str = Field(
        description="Fault kind: pump_failure, choke_plugged, choke_washout, accumulator_leak, weak_shoe, mud_weight_drop"
    )
    message: str = Field(default="", description="Optional custom rig alert message")


class FreezeCommand(BaseModel):
    freeze: bool = Field(default=True, description="True to freeze (pause) session; False to resume")


class StudentNameCommand(BaseModel):
    name: str = Field(min_length=1, max_length=60)


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _session(session_id: str) -> Session:
    try:
        return store.get(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


# --------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------

@app.get("/", include_in_schema=False)
def choke_panel() -> FileResponse:
    return FileResponse(STATIC / "choke_panel.html")


@app.get("/teacher", include_in_schema=False)
def teacher_console() -> FileResponse:
    return FileResponse(STATIC / "teacher.html")


@app.get("/api/speeds")
def speeds() -> dict:
    return {"speeds": list(SPEEDS)}


@app.get("/api/scenarios")
def scenarios() -> dict:
    """The exercise library.

    Faults are reported only as a flag, never as a list. A student who knows
    the choke is going to plug at stroke 2,000 is not being tested on noticing
    that the choke has plugged.
    """
    from .scenario import scenario_list

    return {"scenarios": scenario_list()}


@app.post("/api/sessions", status_code=201)
def create_session(body: NewSession) -> dict:
    try:
        session = store.create(
            scenario=body.scenario,
            student_name=body.student_name,
            **({} if body.scenario else {
                "bop": body.bop,
                "trajectory": body.trajectory,
                "start": body.start,
            }),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        # An unknown BOP location or trajectory: the enum says what is valid.
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "session_id": session.session_id,
        "student_name": session.student_name,
        "gauges": session.gauges(),
        "lineup": session.lineup(),
        "scenario": (
            None if session.scenario is None else session.scenario.summary()
        ),
    }


@app.get("/api/sessions/{session_id}")
def snapshot(session_id: str, since_event: int = 0, trace_limit: int = 240) -> dict:
    """The panel's poll: gauges, new events and the strip chart, one instant."""
    return _session(session_id).snapshot(
        since_event=since_event, trace_limit=trace_limit
    )


@app.get("/api/sessions/{session_id}/lineup")
def lineup(session_id: str) -> dict:
    return {"valves": _session(session_id).lineup()}


@app.post("/api/sessions/{session_id}/choke")
def set_choke(session_id: str, body: ChokeCommand) -> dict:
    session = _session(session_id)
    session.set_choke(body.percent)
    return {"gauges": session.gauges()}


@app.post("/api/sessions/{session_id}/pump")
def set_pump(session_id: str, body: PumpCommand) -> dict:
    session = _session(session_id)
    session.set_pump(body.spm)
    return {"gauges": session.gauges()}


@app.post("/api/sessions/{session_id}/valve")
def set_valve(session_id: str, body: ValveCommand) -> dict:
    """Operate a valve.

    A wrong lineup is not an error -- it simply does not work -- so the only
    failures here are a valve that does not exist or a state that is not open
    or closed.
    """
    session = _session(session_id)
    try:
        session.set_valve(body.name, body.state)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"gauges": session.gauges(), "lineup": session.lineup()}


@app.post("/api/sessions/{session_id}/speed")
def set_speed(session_id: str, body: SpeedCommand) -> dict:
    session = _session(session_id)
    session.set_speed(body.speed)
    return {"gauges": session.gauges()}


@app.post("/api/sessions/{session_id}/strip")
def strip(session_id: str, body: StripCommand) -> dict:
    session = _session(session_id)
    session.strip(body.feet_per_min)
    return {"gauges": session.gauges()}


@app.post("/api/sessions/{session_id}/mud-weight")
def set_mud_weight(session_id: str, body: MudWeightCommand) -> dict:
    session = _session(session_id)
    session.set_mud_weight(body.ppg)
    return {"gauges": session.gauges()}


@app.post("/api/sessions/{session_id}/zero-trip-tank")
def zero_trip_tank(session_id: str) -> dict:
    session = _session(session_id)
    session.zero_trip_tank()
    return {"gauges": session.gauges()}


@app.post("/api/sessions/{session_id}/zero-pits")
def zero_pits(session_id: str) -> dict:
    session = _session(session_id)
    session.zero_pits()
    return {"gauges": session.gauges()}


@app.get("/api/sessions/{session_id}/schematic")
def schematic(session_id: str) -> dict:
    return _session(session_id).schematic()


@app.get("/api/sessions/{session_id}/killsheet")
def kill_sheet(session_id: str) -> dict:
    return _session(session_id).kill_sheet()


@app.get("/api/sessions/{session_id}/debrief")
def debrief(session_id: str, require_kill: bool | None = None) -> dict:
    """Grade the run. Omit require_kill to use the scenario's own standard."""
    return _session(session_id).debrief(require_kill=require_kill)


@app.get("/api/sessions/{session_id}/ai-debrief")
def ai_debrief(session_id: str) -> dict:
    """AI-powered qualitative assessment, score, and instructor coaching notes."""
    return _session(session_id).ai_debrief()


@app.delete("/api/sessions/{session_id}", status_code=204)
def end_session(session_id: str) -> None:
    _session(session_id)
    store.drop(session_id)


# --------------------------------------------------------------------------
# Teacher / Instructor endpoints
# --------------------------------------------------------------------------

@app.get("/api/teacher/sessions")
def teacher_sessions() -> dict:
    """Multi-student overview for the teacher dashboard."""
    return {
        "sessions": [s.summary() for s in store.list()],
        "total": len(store),
    }


@app.post("/api/teacher/sessions/{session_id}/fault")
def inject_fault(session_id: str, body: FaultInjectionCommand) -> dict:
    """Inject an unexpected live equipment failure onto a student's session."""
    session = _session(session_id)
    try:
        session.inject_fault(body.kind, body.message)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"ok": True, "session": session.summary()}


@app.post("/api/teacher/sessions/{session_id}/freeze")
def freeze_session(session_id: str, body: FreezeCommand) -> dict:
    """Remotely freeze/unfreeze a specific student for whiteboard review."""
    session = _session(session_id)
    session.freeze(body.freeze)
    return {"ok": True, "session": session.summary()}


@app.post("/api/teacher/sessions/{session_id}/name")
def rename_student(session_id: str, body: StudentNameCommand) -> dict:
    """Rename a student session."""
    session = _session(session_id)
    session.student_name = body.name
    return {"ok": True, "session": session.summary()}


@app.post("/api/teacher/freeze-all")
def freeze_all() -> dict:
    """Master freeze across all active sessions simultaneously."""
    store.freeze_all(True)
    return {"ok": True, "sessions": [s.summary() for s in store.list()]}


@app.post("/api/teacher/resume-all")
def resume_all() -> dict:
    """Master resume across all active sessions simultaneously."""
    store.freeze_all(False)
    return {"ok": True, "sessions": [s.summary() for s in store.list()]}


@app.post("/api/teacher/spawn-demo-class")
def spawn_demo_class() -> dict:
    """Spawn a representative cohort of students for immediate training & demonstration."""
    demos = [
        ("Alex M.", "drillers", 10.0),
        ("Elena R.", "wait_and_weight", 10.0),
        ("Carlos D.", "bullhead", 10.0),
        ("Priya S.", "reverse", 10.0),
        ("Tom H.", "find_the_kick", 1.0),
    ]
    spawned = []
    for name, scenario, spd in demos:
        s = store.create(scenario=scenario, student_name=name)
        s.set_speed(spd)
        spawned.append(s.summary())
    return {
        "ok": True,
        "spawned": len(spawned),
        "sessions": [s.summary() for s in store.list()],
    }


@app.get("/api/sessions/{session_id}/replay")
def replay_session(session_id: str) -> dict:
    """Full flight-recorder telemetry sequence and events for second-by-second scrubbing."""
    return _session(session_id).replay_data()


@app.get("/api/teacher/gradebook")
def teacher_gradebook() -> dict:
    """Cohort gradebook entries with AI scores and metrics."""
    return {"entries": store.gradebook()}


@app.get("/api/teacher/gradebook.csv")
def teacher_gradebook_csv() -> Response:
    """Export cohort gradebook as downloadable CSV for Excel / LMS."""
    import csv
    import io

    entries = store.gradebook()
    output = io.StringIO()
    if entries:
        writer = csv.DictWriter(output, fieldnames=list(entries[0].keys()))
        writer.writeheader()
        writer.writerows(entries)
    else:
        writer = csv.writer(output)
        writer.writerow(["session_id", "student_name", "scenario", "score", "letter_grade", "iwcf_standard"])
    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="wellcontrol_gradebook.csv"'},
    )
