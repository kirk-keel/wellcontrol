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

## The invariant that governs everything

**Pressure calculations take TVD. Circulation calculations take MD.**

Hydrostatic pressure comes from the weight of the fluid column, so it depends on true vertical depth. Volumes, strokes and displacement depend on the measured length of hole. On a vertical well these are the same number and the distinction is invisible; on the horizontal reference well they differ by a factor of two, and mixing them produces a kill mud weight roughly half of what the well needs.

`Survey` owns the conversion. Any new calculation that touches depth must go through it rather than using a raw depth value.

## Architecture

Three layers, each depending only on the ones above it:

1. **Physics primitives** — `units`, `survey`, `geometry`, `hydrostatics`, `rheology`, `kick`, `killsheet`, `tolerance`, `subsea`, `hpht`, `mpd`, `stripping`. Pure functions and dataclasses, no cross-layer imports.
2. **Kill methods** — `methods/`. Composes the primitives into procedures.
3. **Presentation** — `plotting.py` and `app/streamlit_app.py`. Consume `KillPlan`, never recompute physics.

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

## Adding a kill method

Subclass `KillMethod` in `methods/`, set the class attributes (`key`, `name`, `summary`, `circulates`, `requires_migration`), implement `plan()`, and register it in the `METHODS` tuple in `methods/__init__.py`. The Streamlit app iterates that tuple, so it appears automatically — but check whether the app needs new sidebar inputs, and add the method name to `METHOD_LABELS` in `tests/test_streamlit_app.py` so it stays in the rendered matrix.

`plot_kill()` chooses panels from what the trace actually contains, so a method with no drill pipe reading gets fewer panels rather than an empty one.

## Off-bottom pressures

`formation_pressure_psi` is **not** simply `SIDPP + 0.052 × MW × TVD_bit`. SIDPP reads pressure at the *bit*; when the bit is off bottom the formation is deeper and `hydrostatic_below_bit_psi` accounts for what lies between (635 psi on the reference well). A related consequence: with the influx entirely below the bit, SICP equals SIDPP, because both gauges read through identical fluids. A difference means the influx has risen above the bit.

## Content and verified numbers

`content/` is teaching material where every worked example runs and **every quoted number has been checked against actual output**. When changing a calculation, re-run the affected examples and update the prose — several numbers in the content are load-bearing claims, not illustrations.

Two findings in the content contradict the textbook and are deliberate:

- **Wait-and-Weight's shoe-pressure advantage is conditional.** It only holds when kill mud reaches the annulus before the influx reaches the shoe, i.e. string volume < annular volume from shoe to TD. On the reference well it does not hold, and both methods give an identical peak. `WaitAndWeight._shoe_advantage_note()` computes which case applies.
- **The migration allowance usually dominates stripping bleed volumes** — 7.02 bbl against 2.26 bbl of pipe displacement at 1,000 ft/hr.

## Plots

Follow the `dataviz` skill's rules, which the current plots already satisfy: no dual-axis charts (influx volume and depth are separate panels, never twin y-axes), solid hairline gridlines with dashing reserved for threshold lines, categorical slots 1–3 of the reference palette only, and legends only when a panel has two or more series. Both light and dark themes are defined; the app auto-detects which to use.

## Scope

These are engineering aids, not a substitute for certification, a company well control manual, or the judgement of a competent person on the rig. Where a measured value exists (slow circulating rate, choke line friction, PVT data), prefer it over anything computed here, and say so in the docstring.
