# wellcontrol

Well control calculations and teaching content, covering every common well type:
vertical land wells, directional and horizontal wells, subsea wells, HPHT wells,
and managed pressure / underbalanced operations.

Three parts that reference each other:

- **`src/wellcontrol/`** — a tested Python calculation library. The core has no
  dependencies outside the standard library.
- **`app/`** — a Streamlit kill planner: pick a well type and kill method, enter
  the data, get the procedure and diagnostic plots.
- **`content/`** — the theory behind each calculation, with worked examples that
  use the library.

## Install

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -e ".[dev,app]"
pytest
```

`[dev]` alone gives the library and tests with no third-party dependencies.
`[app]` adds matplotlib, streamlit and pandas for the planner.

## The kill planner

```bash
streamlit run app/streamlit_app.py
```

Or double-click **`Launch Kill Planner.bat`**, which builds the environment on
first run and binds to localhost only.

Two pages:

- **Kill Planner** — select one of four well configurations and one of seven
  kill methods. The app builds the geometry, plans the kill, and shows the
  step-by-step procedure with diagnostic plots: circulating pressures, pressure
  at the casing shoe against the fracture limit, influx volume, influx position,
  and bit depth while stripping. Each plan links through to the chapter
  explaining its method.
- **Learn** — the `content/` chapters rendered in the app, with a contents list
  and prev/next navigation.

Combinations that cannot work say so. Volumetric and Lube-and-Bleed both depend
on gas migrating upward, and gas in a horizontal lateral does not migrate, so
those are reported as blocked rather than producing numbers for a procedure that
would stall on the rig.

```python
from wellcontrol import examples, plan_kill
from wellcontrol.wellconfig import WellConfiguration, BOPLocation, Trajectory

well = examples.well_state(
    WellConfiguration(BOPLocation.SUBSEA, Trajectory.HORIZONTAL))

plan = plan_kill(well, "wait_and_weight")
print(plan.format_summary())
print(plan.peak_shoe_pressure_psi, "psi at the shoe")
```

## Five minutes in

```python
from wellcontrol import examples

sheet = examples.vertical_land_well_kill_sheet()

for key, value in sheet.summary().items():
    print(f"{key:.<40} {value}")

print()
print(sheet.format_schedule(sheet.schedule_by_depth(steps=10)))
```

Abridged output:

```
Original mud weight (ppg)............... 9.6
Kill mud weight, calculated (ppg)....... 10.369
Kill mud weight, as mixed (ppg)......... 10.4
Formation pressure (psi)................ 5392
ICP (psi)............................... 1000
FCP (psi)............................... 650
Pressure per step, 10 steps (psi)....... 35
Strokes to bit.......................... 1466
Total strokes........................... 5483
```

Rounding in well control is **directional** — every rule goes the way that adds
margin. Kill mud weight rounds up, limits like MAASP round down, strokes round
up. See [the rounding rules](content/05-kill-sheet.md#rounding-is-directional).

## What is covered

| Module | Covers |
| --- | --- |
| `units` | Oilfield unit constants and conversions |
| `rounding` | Directional rounding rules — up for targets, down for limits |
| `survey` | MD/TVD conversion, build-and-hold trajectories |
| `geometry` | Capacities, annular volumes, drill strings, pump output |
| `hydrostatics` | Hydrostatic pressure, ECD, tripping, slugs |
| `rheology` | Bingham plastic and power law friction losses |
| `kick` | Shut-in analysis, influx identification, gas expansion |
| `killsheet` | Kill mud weight, ICP/FCP, pressure schedules, both methods |
| `tolerance` | Leak-off tests, MAASP, kick tolerance |
| `subsea` | Choke line friction, riser margin, subsea corrections |
| `hpht` | PVT density correction, temperature profiles |
| `mpd` | Surface backpressure, drilling windows, connection schedules |
| `wellconfig` | Well configurations: BOP location × trajectory |
| `stripping` | Stripping and snubbing: bleed volumes, balance point, surge |
| `content` | Reads the teaching chapters for rendering in an app |
| `methods` | Seven kill methods with per-configuration applicability |
| `plotting` | Diagnostic kill plots (matplotlib) |

## Kill methods

| Method | Circulates? | Used when |
| --- | --- | --- |
| Driller's Method | Yes, twice | Standard. Start immediately, weight up later. |
| Wait and Weight | Yes, once | Standard. Weight up first, one circulation. |
| Volumetric Method | No | Cannot circulate; gas migrating. |
| Stripping to Bottom | No | Bit off bottom. Restores the circulation path. |
| Lube and Bleed | No | Cannot circulate; gas already at surface. |
| Reverse Circulation | Yes, backwards | Keeping the influx away from the casing shoe. |
| Bullheading | No | Cannot, or must not, bring the influx up. |

Each is planned against any of four configurations — Surface/Subsea BOP ×
Vertical/Horizontal. See [Choosing a kill method](content/12-choosing-a-kill-method.md)
for the applicability matrix and why two cells are empty.

## Content

Read in order, or jump to the well type you are working on.

1. [Fundamentals](content/01-fundamentals.md)
2. [Hydrostatic pressure](content/02-hydrostatics.md)
3. [Wellbore volumes and strokes](content/03-volumes-and-strokes.md)
4. [Kick detection and shut-in](content/04-kick-detection.md)
5. [The kill sheet](content/05-kill-sheet.md)
6. [Circulation methods](content/06-circulation-methods.md)
7. [Kick tolerance and MAASP](content/07-kick-tolerance.md)
8. [Directional and horizontal wells](content/08-directional-wells.md)
9. [Subsea wells](content/09-subsea-wells.md)
10. [HPHT wells](content/10-hpht-wells.md)
11. [MPD and underbalanced drilling](content/11-mpd-and-ubd.md)
12. [Choosing a kill method](content/12-choosing-a-kill-method.md)
13. [Stripping and snubbing](content/13-stripping.md)

## Reference wells

Three wells run through the tests and the content, chosen because they fail in
different ways:

| Well | Depth | Why it is here |
| --- | --- | --- |
| Vertical land | 10,000 ft MD/TVD | The textbook case where every simple formula works |
| Horizontal | 12,000 ft MD / 5,910 ft TVD | Anywhere MD and TVD are confused, this well gives a badly wrong answer |
| Deepwater subsea | 15,000 ft TVD in 5,000 ft of water | Choke line friction and riser margin dominate |

```python
from wellcontrol import examples

annulus, survey = examples.horizontal_well()
sheet = examples.horizontal_well_kill_sheet()
```

## A note on the constant 0.052

Every gradient in this library uses the field-standard rounded constant:

```
gradient (psi/ft) = 0.052 × mud weight (ppg)
```

The unrounded value is 1/19.25 = 0.051948. The gradient functions accept
`exact=True` if you want it, but 0.052 is what appears on every kill sheet and
every exam, and the 0.1% difference is far smaller than the uncertainty in the
mud weight itself.

## Scope and limits

- Friction correlations are approximations. Where a **measured** slow
  circulating rate pressure exists, use it in preference to anything computed
  here.
- Gas is treated as ideal and isothermal unless you supply temperatures and
  z-factors. This slightly over-estimates expansion, which errs toward caution
  for kick tolerance.
- HPHT density uses a linear PVT model with representative coefficients.
  Real HPHT work needs lab-measured PVT data for the actual mud.

**These are engineering aids, not a substitute for certification, a company
well control manual, or the judgement of a competent person on the rig.**
Verify against your own procedures before using any of it operationally.

## License

MIT
