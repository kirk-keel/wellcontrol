# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

**Bare `python` on this machine is a broken Microsoft Store alias stub** — it prints "Python was not found" and exits 49. Always invoke the venv interpreter by path.

```bash
.venv/Scripts/python.exe -m pytest                      # full suite (~60s, 595 tests)
.venv/Scripts/python.exe -m pytest tests/test_methods.py -q
.venv/Scripts/python.exe -m pytest -k "test_balance_point" -q      # single test
.venv/Scripts/python.exe -m pytest tests/test_stripping.py::TestForces -q
```

Setup from scratch (real interpreter lives at `%LOCALAPPDATA%\Programs\Python\Python313\python.exe`):

```bash
python -m venv .venv && .venv/Scripts/python.exe -m pip install -e ".[dev,app]"
```

Run the app — or double-click `Launch Kill Planner.bat`, which builds the venv on first run and binds to localhost only:

```bash
.venv/Scripts/python.exe -m streamlit run app/streamlit_app.py
```

`[dev]` is dependency-free (library + tests). `[app]` adds matplotlib, streamlit, pandas. `tests/test_streamlit_app.py` skips itself via `importorskip` when streamlit is absent, so the core suite stays dependency-free.

## Rounding is directional

Never use `round()` on a well control quantity. Every rule goes the way that adds margin, and `wellcontrol/rounding.py` implements them:

| Quantity | Direction | Places |
| --- | --- | :-: |
| Kill mud weight | **up** | 1 |
| Max allowable mud weight | **down** | 1 |
| MAASP / MASP | **down** | 0 |
| Pressure per step | **down** | 0 |
| Strokes | **up** | 0 |
| Volume | nearest | 1 |

Pressures and strokes carry no decimals; volumes carry exactly one.

**Where a quantity rounds to nearest, it rounds half away from zero** — 3.45 bbl is 3.5. Python's `round` uses banker's rounding, so `round(0.25, 1)` is 0.2 and `round(2.5)` is 2, which is not what anyone filling in a kill sheet does. `rounding._half_up` goes through `Decimal(str(value))` to get both the direction and the decimal representation right.

**Rounded values are the operational ones.** The rig mixes 10.4 ppg, so FCP is built from 10.4, not 10.369. Where the unrounded figure is useful, it is available under an `_exact` name (`kill_mud_weight_exact_ppg`).

A consequence worth knowing: rounding the kill weight up makes the mud heavier than the mud that exactly balances the formation, so `KillSheet.rounding_overbalance_psi` (16 psi on the reference well) is real extra margin. It also means the depth-accurate schedule, which solves for exactly balanced, finishes *below* the nominal FCP by that amount. Not a bug — work to FCP.

The float handling matters: `10.4 * 10` is `104.00000000000001`, so a naive `ceil` would give 10.5. Every function snaps to a tolerance first.

## The invariant that governs everything

**Pressure calculations take TVD. Circulation calculations take MD.**

Hydrostatic pressure comes from the weight of the fluid column, so it depends on true vertical depth. Volumes, strokes and displacement depend on the measured length of hole. On a vertical well these are the same number and the distinction is invisible; on the horizontal reference well they differ by a factor of two, and mixing them produces a kill mud weight roughly half of what the well needs.

`Survey` owns the conversion. Any new calculation that touches depth must go through it rather than using a raw depth value.

## Architecture

Three layers, each depending only on the ones above it:

1. **Physics primitives** — `units`, `survey`, `geometry`, `hydrostatics`, `rheology`, `kick`, `killsheet`, `tolerance`, `subsea`, `hpht`, `mpd`, `stripping`. Pure functions and dataclasses, no cross-layer imports.
2. **Kill methods** — `methods/`. Composes the primitives into procedures.
3. **Presentation** — `plotting.py` and `app/`. Consume `KillPlan`, never recompute physics.

### App layout

`app/streamlit_app.py` is only a navigation entry. The pages are separate scripts under `app/views/` (`planner.py`, `learn.py`) with shared helpers in `app/shared.py`. They are separate files rather than functions so each can be run and tested on its own — `AppTest` cannot reach a function-based `st.Page`, and `switch_page` needs a file path.

Anything a page needs that isn't pure UI belongs in the library, not in `shared.py`. The chapter reading and link-rewriting live in `wellcontrol/content.py` for exactly this reason: they are testable without a Streamlit runtime, which is how `tests/test_content.py` checks that every method's `chapter` attribute names a file that exists.

**Restart Streamlit after changing anything under `src/`.** Hot reload re-runs the page script but leaves imported modules cached in `sys.modules`, so library edits do not reach a running app. This has twice produced a "bug" in the browser that did not exist in the code — verify against a fresh start before investigating.

**`st.switch_page` cannot be called from an `on_click` callback.** It is a rerun, and Streamlit makes reruns no-ops inside callbacks, so the click silently does nothing. Handle navigation on the button's return value instead. A test that only asserts the button *exists* will not catch this — click it and assert the resulting state.

### The `KillMethod` contract (`methods/base.py`)

Every method takes a `WellState` (well + string + pump + the three shut-in readings) and returns a `KillPlan` carrying: an `Applicability` verdict, headline `summary` numbers, ordered `stages` with actions, and a `TracePoint` series for plotting.

Two design decisions worth preserving:

**Applicability is part of the answer, not a precondition.** Not every method works on every well — Volumetric and Lube-and-Bleed depend on gas migrating, and gas in a horizontal lateral has no upward direction to migrate in. Methods return `blockers` (do not attempt) and `warnings` (proceed with care) rather than raising or silently producing plausible numbers for a procedure that would stall on the rig. Subclasses call `super().applicability(well)` and add their own checks.

**Pressures come from a fluid column, not a formula.** `FluidColumn` models the annulus as an explicit stack of `Zone`s — kill mud at the bottom, mud behind the influx, the influx, original mud above — and computes pressure at any depth from it. Casing pressure is derived as "whatever hydrostatic the column does not supply must appear at surface", and shoe pressure is read off the same column. This is what makes the shoe plot trustworthy rather than a correction applied to a surface reading.

### The circulation simulator (`methods/circulating.py`)

Driller's and Wait-and-Weight share `simulate_circulation()`. At each step it reconstructs the whole well: kill mud position in the string, the four-zone annulus, and the influx volume solved by Boyle's law against the pressure at its own depth so it expands as it rises.

Four invariants the tests enforce across every configuration — an arithmetic error anywhere breaks at least one:

- Zones tile the annulus exactly (mass conservation)
- Influx pressure × volume stays constant (Boyle)
- Drill pipe pressure starts at ICP and reaches FCP when kill mud hits the bit
- Casing pressure ends near zero on a complete kill

### Documented approximations

Keep these stated wherever they apply; they are deliberate, not oversights.

- **Annular friction while circulating is neglected.** System friction is carried on the drill pipe side as the measured slow circulating rate. Standard kill sheet convention.
- **Gas is ideal and isothermal** unless temperatures and z-factors are supplied. Slightly over-estimates expansion, which errs toward caution for kick tolerance.
- **The influx is one continuous bubble.** Real influxes disperse, and in oil-based mud dissolve entirely.
- **HPHT density uses a linear PVT model** with representative coefficients, not lab data.

## The simulator (`wellcontrol/sim/`)

A training simulator where a student lines the rig up, brings the pump on and works the choke. Design and staged plan in `docs/simulator-design.md`.

**It solves the opposite direction to the rest of the library, and that is the whole point.** `simulate_circulation` asks "what pressure must the driller hold?" and assumes success. `sim.Simulator` asks "the student set the choke to 35% — what does the well do?" and must represent failure as faithfully as success. Do not try to merge them.

Everything turns on one equation in `engine.py`:

```
dP/dt = (Q_in + q_influx − Q_out − q_loss) / capacitance
capacitance = V_mud × c_mud + V_gas / P_gas_absolute
```

Mud contributes almost nothing, so with little gas the system is **stiff** and a small choke movement swings casing pressure hundreds of psi; as gas rises and expands the capacitance grows by an order of magnitude and it goes **soft**. On the reference well: 0.0056 bbl/psi with gas deep, 0.038 shallow. That contrast is what makes a choke teachable, so **do not damp it out** to make the sim easier to fly.

Every failure mode emerges from that balance rather than being scripted — extra influx, shoe breakdown, deadhead, pressure spike, and the BOP-left-open case where returns take the flowline and the choke does nothing at all. If a future change makes any of those need special-casing, the model has drifted.

Lineup is a directed graph in `flowpath.py`: equipment are nodes, valves are edges, and each step asks whether a path exists pump→well and well→pits. **Wrong lineups are not scored as errors; they simply do not work.** BOP elements are inverted — closing one removes a route — so they are not ordinary edges.

Validated by a proportional autopilot in `tests/test_simulator.py` standing in for a driller who never errs: bottomhole pressure holds within 75 psi of formation pressure, no further influx, shoe under fracture. That is the check that the forward and inverse models describe the same well; keep it passing.

## A data invariant worth knowing

**With an influx that has no vertical height, SICP equals SIDPP.** A lateral influx displaces no hydrostatic, so both gauges read through the same mud to the same TVD. The same holds for an influx entirely below an off-bottom bit. The horizontal examples originally violated this and nothing caught it for a long time, because nothing except the simulator computes bottomhole pressure from the annulus column at shut-in — every other path starts from SIDPP and never cross-checks the annulus side. Any new example data should be checked against it.

## Where this is up to

- **Simulator**: stage 1 of 5 done (headless engine, lineup, validation). Next: assessment and event log, then the choke panel, then the remaining screens, then a scenario library. The UI stack is deliberately still undecided — decide it once the engine is driving something.
- **Importers**: done and validated against real-shaped files in `test_data/`, with an independent answer key. See *Importing real geometry* below.

## Adding a kill method

Subclass `KillMethod` in `methods/`, set the class attributes (`key`, `name`, `summary`, `circulates`, `requires_migration`, and `chapter` / `chapter_depth` pointing at the content that explains it), implement `plan()`, and register it in the `METHODS` tuple in `methods/__init__.py`. The Streamlit app iterates that tuple, so it appears automatically — but check whether the app needs new sidebar inputs, and add the method name to `METHOD_LABELS` in `tests/test_streamlit_app.py` so it stays in the rendered matrix.

`plot_kill()` chooses panels from what the trace actually contains, so a method with no drill pipe reading gets fewer panels rather than an empty one.

## Off-bottom pressures

`formation_pressure_psi` is **not** simply `SIDPP + 0.052 × MW × TVD_bit`. SIDPP reads pressure at the *bit*; when the bit is off bottom the formation is deeper and `hydrostatic_below_bit_psi` accounts for what lies between (635 psi on the reference well). A related consequence: with the influx entirely below the bit, SICP equals SIDPP, because both gauges read through identical fluids. A difference means the influx has risen above the bit.

## Content and verified numbers

`content/` is teaching material where every worked example runs and **every quoted number has been checked against actual output**. When changing a calculation, re-run the affected examples and update the prose — several numbers in the content are load-bearing claims, not illustrations.

Four findings in the content contradict the textbook and are deliberate:

- **The drill pipe schedule reverses in a lateral.** Pressure has to be taken *up*, not down: the kill mud front gains no TVD so hydrostatic stops rising, while friction keeps climbing toward FCP. A single ICP-to-FCP straight line would have the driller bleeding pressure off where he should be adding it. `KillSheet.schedule_segments()` breaks the schedule at trajectory boundaries *and* at every pipe size change; `ScheduleSegment.pressure_rises` flags the reversal.
- **Wait-and-Weight's shoe-pressure advantage is conditional** on open hole annular volume exceeding drill string volume. On the reference well it does not, and both methods give an identical peak. `WaitAndWeight._shoe_advantage_note()` computes which case applies.
- **Peak shoe pressure is often set at shut-in, not while circulating.** Shut-in is a property of the well and identical for every method, so comparing overall peaks can show two methods as identical when they differ. Use `peak_circulating_shoe_pressure_psi` to discriminate. The cause is that gas rising from the collar annulus into the wider casing annulus gets *shorter* despite expanding — the textbook "worst moment is gas at the shoe" assumes a uniform annulus.
- **The migration allowance usually dominates stripping bleed volumes** — 7.0 bbl against 2.3 bbl of pipe displacement at 1,000 ft/hr.
- **Wait and Weight on a horizontal well needs one drill pipe schedule per section**, four on the reference well, and the schedule reverses in the lateral. The Driller's Method is generally preferred there for that reason. `WaitAndWeight.applicability()` warns rather than blocks — the method is harder to execute, not impossible.

## Importing real geometry

`wellcontrol/importers.py` reads a directional survey and a pipe tally from CSV, with fuzzy header matching (`MD` / `Measured Depth` / `Depth`, and so on). `samples/` holds working examples of both formats. `Survey.from_minimum_curvature` builds TVD from MD/inclination/azimuth, which is what a real survey file contains — a file's own TVD column wins when present, because the surveyor's is authoritative.

Bad files are rejected with a message naming the row, never coerced. A well control calculation built on a misread file is worse than none, because it looks authoritative.

**Three assumptions real data broke, all now fixed — do not reintroduce them:**

- **TVD may decrease.** A real lateral undulates either side of 90°, so the hole goes uphill in places. `Survey` used to reject that outright. Only a TVD change *faster* than the MD change is impossible.
- **Vertical spans between two survey points are signed.** `hydrostatic_pressure` rejects a negative depth, which is right for a depth and wrong for a span — in an undulating lateral the kill mud front can be deeper than the bit. Use `signed_hydrostatic` wherever both ends come from a survey.
- **A real BHA has many short components.** Breaking the schedule at each gives 0-stroke segments nobody can work to, so `schedule_segments(min_strokes=5)` merges slivers.

`Annulus` validates that the string physically fits the hole at construction, naming the component and section. Pairing a tally with the wrong hole section is a plausible mistake and used to fail deep inside a volume calculation.

### Validated against `test_data/`

`test_data/` holds a rig-shaped survey (157 stations), a joint-by-joint pipe tally (405 components) and `well_control_test_data.xlsx`, whose `Well_Data` sheet is an **independently computed answer key** for the same well — expected TVDs, volumes, strokes and kill sheet. `tests/test_real_files.py` checks the library against it. Those numbers did not come from this library, so **when one of those tests fails, assume the library is wrong**. The data is synthetic but realistically shaped; it is committed, so the tests are portable.

Three more things real files broke:

- **`Item_No` is a row index, not a joint count.** The `count` alias list included `"no"`, which matched it, and the tally imported as 2,554,260 ft instead of 12,500 — a 200× error, silently. Fixed three ways, all worth keeping: the `count` aliases are now specific (`count`/`joints`/`jts`/`qty`…), `_looks_like_a_row_index()` rejects a 1,2,3… sequence, and `_cross_check_against_cumulative()` hard-fails on a >2% disagreement with the file's own cumulative column. **A tally must be cross-checked against something, not just parsed.**
- **Header matching is on token boundaries, not substrings.** The obvious fix above — requiring longer aliases — broke `MD_ft`, because `md` is two characters. `_resolve_columns` now runs three passes (exact header, then token, then substring for aliases of 4+ characters), so `MD_ft` → `["md","ft"]` matches `md` while `wood` → `["wood"]` does not match `od`. Widening an alias list is the thing most likely to reintroduce a silent misread; add a test to `test_real_files.py` when you do.
- **The survey stops behind the bit.** Surveys are taken at the MWD sensor, 40–100 ft up the BHA, so the deepest station is routinely short of TD — here 12,460 ft against a bit at 12,500 ft. This is normal, not a malformed file. `Survey.extended_to(md)` holds the last inclination and azimuth through the unsurveyed hole (a tangent projection, which is what a directional driller reports), and `build_well` calls it unconditionally. It refuses beyond 500 ft, where holding an angle stops being a projection and becomes a guess.

**Most real wells are deviated, not horizontal.** This one holds 35°. `trajectory_from_survey` can therefore return `DEVIATED` and override the sidebar selection, so `DEFAULTS` carries `surface_deviated` and `subsea_deviated` entries — all six `BOPLocation` × `Trajectory` keys exist, and a test pins that.

Expect the next real export to bring header spellings, unit rows, footers and merged cells this parser has not seen; extend `SURVEY_ALIASES` / `TALLY_ALIASES` and the validation rather than loosening the rejections.

## Stripping is half an operation

A kick with the bit off bottom needs stripping *then* a circulating kill. `strip_then_kill(well, "drillers" | "wait_and_weight")` returns a `KillSequence` pairing both phases, using `WellState.with_bit_at()` to rebuild the string with the bit on bottom for the second. It reports combined time and which phase peaks at the shoe — on the horizontal reference well that is the *stripping*, which planning the kill alone would miss.

## Plots

Follow the `dataviz` skill's rules, which the current plots already satisfy: no dual-axis charts (influx volume and depth are separate panels, never twin y-axes), solid hairline gridlines with dashing reserved for threshold lines, categorical slots 1–3 of the reference palette only, and legends only when a panel has two or more series. Both light and dark themes are defined; the app auto-detects which to use.

## Scope

These are engineering aids, not a substitute for certification, a company well control manual, or the judgement of a competent person on the rig. Where a measured value exists (slow circulating rate, choke line friction, PVT data), prefer it over anything computed here, and say so in the docstring.
