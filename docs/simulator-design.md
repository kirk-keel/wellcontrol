# Well control simulator — design

A training simulator where a student plans a kill, lines up the rig, brings the
pump online, and works the choke to circulate the influx out — with the well
responding to what they actually do rather than what they intended.

**Status: stages 1–3 done — headless engine, lineup, validation, event log and
assessment, and the choke panel running on FastAPI. The full drilling → kick →
detection → shut-in sequence is in. Remaining: the other screens, the other kill
methods as things you operate rather than plan, and the scenario library.**

**Scope agreed: a true simulator, not a choke trainer.** The student drills
ahead, takes a kick they have to *notice*, shuts in on their own initiative, and
reads their own shut-in pressures. Physics stays behaviourally right — the
documented idealisations (single bubble, ideal isothermal gas, kill-sheet
friction convention) are kept, because every lesson a student must feel already
emerges from them.

**UI decision taken (§9.1): FastAPI + browser.** Streamlit reruns the whole
script on every interaction and has no game loop, so gauges would be widgets
rather than instruments and the choke would feel laggy — the wrong trade for the
one control the whole exercise turns on. The planner stays on Streamlit; the two
apps share the library and nothing else.

Decisions taken:

| Decision | Choice |
| --- | --- |
| Build order | Engine first, headless. UI decided later, once there is something to drive. |
| Lineup fidelity | Simplified — about a dozen key valves, not the full manifold. |
| Audience | Both, self-study first. Instructor fault-injection comes later. |

---

## 1. Why the existing engine cannot be reused

The library already simulates a kill. It solves the wrong direction.

| | Existing `simulate_circulation` | What the simulator needs |
| --- | --- | --- |
| Question | "What pressure must the driller hold to keep BHP constant?" | "The student set the choke to 35%. What does BHP do?" |
| Direction | Inverse — assumes the target is met | Forward — computes the consequence |
| Failure | Cannot represent it | Must represent it faithfully |
| Time | Volume-stepped, quasi-static | Time-stepped, dynamic |
| Driver | The plan | The student's hands |

The existing engine is still used — it produces the *plan* the student works to,
and the *target* the debrief scores them against. But the thing under the
student's hands is new.

**This is the main body of work and the main risk.** Everything else is
plumbing around it.

---

## 2. The forward engine

### State

```
time, dt
annulus:  ordered fluid zones (volume, density, is_gas)
string:   ordered fluid zones
influx:   volume, top/bottom position, pressure, temperature
surface:  casing pressure, standpipe pressure
pits:     active volume, trip tank volume, gain/loss vs baseline
equipment: pump spm, choke position, valve states, BOP states
```

### Each timestep

1. **Resolve the flow path** from the valve graph (§3). No path from pump to
   well → the pump deadheads. No path from well to pits → closed system.
2. **Pump delivers** `Q_in = spm × output × efficiency`, or zero if deadheaded.
3. **Choke passes** `Q_out = Cd · A(position) · √(2ΔP / ρ)` — the standard
   orifice relation. A closed choke passes nothing regardless of pressure.
4. **Volume balance** drives surface pressure through system compressibility:

   ```
   dP_casing/dt = (Q_in + q_influx − Q_out − q_loss) / (C_system · V_system)
   ```

   `C_system` combines mud compressibility, free gas, and casing expansion.
   This single equation is what makes the choke *feel* right: with little gas
   in the hole the system is stiff and a small choke movement swings pressure
   hard; with gas near surface it is soft and sluggish. Learning that
   difference is most of what choke operation is.

5. **BHP** `= P_casing + annulus hydrostatic + annular friction`.
6. **Influx** enters on underbalance, via a productivity index:
   `q_influx = PI · (Pf − BHP)` when `BHP < Pf`, else zero.
7. **Losses** when the shoe is over-pressured:
   `q_loss = LI · (P_shoe − P_frac)` when `P_shoe > P_frac`.
8. **Gas expands** per Boyle as it rises and pressure falls.
9. **Positions advance** by displaced volume.

### Why this shape

Every failure mode a student must feel emerges from the model rather than being
scripted:

- Choke too open → BHP falls → **influx takes another kick** (step 6)
- Choke too closed → BHP rises → **shoe breaks down** (step 7)
- Shut the choke with the pump running → **pressure spikes** (step 4)
- Gas near surface → **choke gets violent** (step 4 via `C_system`)
- Pump up with the choke shut → **deadhead** (step 1)

Nothing is a canned animation. That matters: students learn the *coupling*, not
a sequence.

### Numerical notes

Mud is nearly incompressible, so the pressure equation is stiff. Fixed small
steps (~0.05 s) with the compressibility term are stable enough and cheap; an
implicit step is the fallback if it is not. Simulation time is decoupled from
wall time by a speed multiplier (§6).

---

## 3. Lineup as a graph

"Lining up the standpipe, choke/kill manifold, trip tank, BOP" becomes a
directed graph. Nodes are equipment, edges are valves.

```
mud pumps → standpipe manifold → standpipe → topdrive → drill string
      → bit → annulus → BOP stack → ┬ choke line → choke manifold → MGS → pits
                                    ├ kill line
                                    └ flowline (BOP open) → shakers → pits
trip tank ↔ annulus
```

Each valve is open or closed. Each timestep, the engine asks:

- Is there a path **pump → well**? If not, the pump deadheads.
- Is there a path **well → pits**? If not, the system is closed.
- Which route are returns taking — flowline, choke line, or kill line?

This gives lineup practice with real consequences, and it is honest: a student
who opens the wrong manifold valve gets no returns and has to work out why,
exactly as on a rig. Wrong lineups are not scored as "incorrect" — they simply
do not work.

**Open question (§9.2): how many valves.** A real choke manifold has a dozen.
Modelling all of them is more realistic and more tedious.

---

## 4. Screens

The student switches between panels; an instructor can see all of them.

| Screen | Shows | Controls |
| --- | --- | --- |
| **Driller's console** | Standpipe pressure, SPM, pit volume, flow out, stroke counters, hookload | Pump start/stop, SPM |
| **Choke panel** | Casing and drill pipe pressure, stroke counter, pump rate, choke position | Choke open/close, choke select |
| **BOP panel** | Annular and ram status, accumulator pressure | Open/close each element |
| **Manifold lineup** | Schematic of the circulating system | Click valves open/closed |
| **Well schematic** | Cross-section: mud, kill mud, influx position, shoe, bit | — |
| **Kill sheet** | The plan the student made, target vs actual | — |
| **Debrief** | BHP trace vs target, event log, verdict | — |

The choke panel is where the kill is executed and deserves the most care: it
needs the drill pipe gauge, the casing gauge, the stroke counter and the choke
in one view, because that is the instrument scan the student must build.

---

## 5. Scenario and assessment

**A scenario** defines the well (reusing `WellState`), the kick, the starting
lineup, and the objective. Scenarios are data, so instructors can add them.

```
scenario:
  well:            an existing WellState
  kick:            influx volume, pore pressure, PI
  initial_lineup:  which valves start open
  objective:       "kill the well using the Driller's Method"
  faults:          optional — a plugged choke at stroke 2,000, a pump failure
```

**Assessment** is computed from the recorded trace, not from following a script:

- Time spent with BHP outside a ±50 psi band around formation pressure
- Peak shoe pressure against the fracture pressure
- Peak casing pressure against MAASP
- Additional influx taken (bbl)
- Whether the well was killed, and the time taken
- Event log with timestamps for the debrief

Scoring on **outcome and margin**, not on procedure order, so a student who
achieves constant bottomhole pressure by a slightly unusual route is not
penalised.

### As built (`sim/assessment.py`)

Three things the design did not anticipate:

**The shoe is the limit, not MAASP.** MAASP is a surface proxy that exists
because nobody can read a gauge at 7,000 ft. The simulator computes shoe
pressure directly from the fluid column, so the hard limit is shoe against
fracture pressure; peak casing against MAASP is reported because it is what the
student was watching, but it is informational.

**Conditions need hysteresis or the log is unreadable.** Losses, influx and
off-target are conditions true for thousands of timesteps, so the log records
their edges — but a value sitting *on* its threshold then logs every crossing. A
well-flown kill produced 111 entries, mostly "bottomhole pressure 50 psi off
target" toggling. `EventLog.set_level()` is a Schmitt trigger: it needs a
separate set point and reset point. The same run now logs 2. The *metrics* still
integrate against the true band — the hysteresis is for the log alone.

**Not every exercise ends with a dead well.** A Driller's *first* circulation,
flown perfectly, leaves the well live and shut in. `Standard.require_kill`
carries that; it becomes the scenario's objective at stage 5.

Two quantities are time integrals — seconds off target, and barrels of extra
influx — so the engine accumulates them at every timestep rather than letting
the assessor sample them off the trace, where a short excursion between two
samples would vanish. The trace itself is sampled on an interval: a three-hour
kill at `dt=0.1 s` is over a hundred thousand steps and no debrief needs that.

---

## 6. Time

A real kill runs three to five hours. The simulator needs:

- **Speed multiplier** — 1×, 10×, 60×, and pause
- **Physics decoupled from wall clock** — the engine advances by simulated `dt`
  regardless of how fast that is displayed
- **Automatic slow-down at the interesting moments** — optional: drop to 1×
  when gas reaches the choke, which is when the student most needs the time

### As built (`sim/session.py`)

**Time advances on demand, not on a background thread.** Each call looks at how
much wall time has passed, multiplies by the speed, and steps the engine that
far. No timers, nothing running when nobody is watching. Two consequences:

* **The well only evolves while somebody is looking at it.** For a self-study
  trainer that is right — a student who walks away has not lost the kick — and it
  makes every test deterministic without sleeping.
* **Catch-up is clamped** (`MAX_CATCHUP_S`). Without it, ten minutes away at 60×
  returns ten hours of simulated well integrated in a single request.

The clock is injected, defaulting to `time.monotonic`, so the whole time model is
tested with a fake clock. Monotonic rather than wall clock: the simulation must
not jump when the machine's clock is adjusted.

Changing speed advances first, then changes — otherwise time that elapsed at the
old speed gets integrated at the new one. The same applies to every control
change, which is why `set_choke`, `set_pump` and `set_valve` all advance before
acting.

---

## 7. Where it sits

```
src/wellcontrol/sim/
  state.py       simulation state
  flowpath.py    valve graph and path resolution
  equipment.py   pump, choke, BOP, trip tank models
  engine.py      the timestep integrator
  scenario.py    scenario definitions
  assessment.py  event log and scoring
```

Pure Python, no UI dependency, fully testable headless — the same discipline as
the rest of the library. The UI is a client of the engine, not part of it.

---

## 8. Proposed build order

Each stage is useful on its own and de-risks the next.

1. ~~**Engine, headless.**~~ **Done.** Flow path, pump, choke, volume balance,
   influx and loss response. Driven by a script. Tested against the invariants:
   a perfectly-executed kill must reproduce the existing quasi-static solver's
   answer to within a few psi.
2. ~~**Assessment and event log.**~~ **Done.** Still headless. A scripted "good
   kill" and a scripted "bad kill" produce sensibly different verdicts — the
   well-flown kill grades *excellent*; a choke left at a fixed position fails on
   shoe pressure and losses; a choke left wide open fails on additional influx;
   a kill attempted with the BOP open fails on influx and logs the critical
   "the choke has no effect".
3. ~~**One screen — the choke panel.**~~ **Done.** `sim/session.py` owns the
   wall-clock-to-simulated-time mapping, `sim/api.py` is the HTTP transport, and
   `sim/static/choke_panel.html` is the panel. Launch it with
   *Launch Simulator.bat*.
4. **The rest of the screens**, lineup schematic last since it is the most UI-heavy.
5. **Scenario library** and instructor debrief.

Stage 1 is where the real risk is. If the engine is right, everything else is
presentation.

---

## 9. Decisions needed before building

### 9.1 UI stack

Streamlit reruns the entire script on every interaction and has no game loop.
It is a poor fit for real-time gauges and clickable schematics — workable with
fragments and auto-refresh, but it will feel laggy and the panels will be
widgets rather than instruments.

| Option | For | Against |
| --- | --- | --- |
| **Streamlit** | One stack, reuses everything, fastest to build | Laggy, crude panels, fights the use case |
| **Web app** (FastAPI + browser) | Proper real-time, real gauges and P&ID schematics, multiple windows | New stack, considerably more work |
| **Desktop** (Qt) | Best control | Not shareable, wrong for training |

**Recommendation: defer.** Build the engine headless first — it is UI-agnostic
and the hard part. Decide the UI when there is something to drive.

### 9.2 Lineup fidelity

- **Simplified** — a dozen key valves. Teaches the concept, less tedious.
- **Full manifold** — every valve. Realistic, and closer to a real rig's
  lineup drill.

### 9.3 Physics fidelity

Two places where more realism costs a lot of complexity:

- **Gas** — single bubble (as now) versus dispersed/slug flow. Single bubble
  is defensible for training and much simpler.
- **Oil-based mud** — gas going into solution and breaking out near surface is
  a genuinely different and important behaviour, but a large modelling job.

### 9.4 Who uses it

Whether this is for **self-study** (student alone, automatic debrief) or
**instructor-led** (instructor injects faults, watches all screens) changes the
priority of the debrief and fault-injection features.

---

## 10. What this does not attempt

Stated so the scope is honest:

- Not a certified training device. No IWCF or IADC accreditation is implied.
- Not a rig-floor visual simulator — no 3D, no crew, no tripping mechanics
  beyond volumes.
- Not a substitute for hands-on time on a real choke.
