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

from fastapi import FastAPI, HTTPException
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


@app.get("/api/speeds")
def speeds() -> dict:
    return {"speeds": list(SPEEDS)}


@app.post("/api/sessions", status_code=201)
def create_session(body: NewSession) -> dict:
    try:
        session = store.create(
            bop=body.bop, trajectory=body.trajectory, start=body.start
        )
    except ValueError as exc:
        # An unknown BOP location or trajectory: the enum says what is valid.
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "session_id": session.session_id,
        "gauges": session.gauges(),
        "lineup": session.lineup(),
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


@app.get("/api/sessions/{session_id}/debrief")
def debrief(session_id: str, require_kill: bool = False) -> dict:
    return _session(session_id).debrief(require_kill=require_kill)


@app.delete("/api/sessions/{session_id}", status_code=204)
def end_session(session_id: str) -> None:
    _session(session_id)
    store.drop(session_id)
