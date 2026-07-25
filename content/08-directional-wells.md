# 8. Directional and horizontal wells

## One rule

> **Pressure calculations take TVD. Circulation calculations take MD.**

Hydrostatic pressure comes from the weight of the fluid column, and weight acts
vertically — so pressure depends on **true vertical depth**. Volumes, strokes and
displacement depend on the actual length of hole the mud has to travel through —
so they depend on **measured depth**.

On a vertical well the two are the same number and the distinction never
surfaces. On a horizontal well they differ by a factor of two.

## The reference well

```python
from wellcontrol import examples

survey = examples.horizontal_survey()

survey.total_md     # 12000 ft
survey.total_tvd    # 5910 ft
```

Kick-off at 4,000 ft, building 3°/100 ft to horizontal, then 5,000 ft of
lateral. The build finishes at 7,000 ft MD and 5,910 ft TVD — and the entire
lateral adds measured depth without a single foot of TVD.

```python
survey.tvd_at(4000)     # 4000 ft — still vertical
survey.tvd_at(5500)     # 5350 ft — mid-build, 45 degrees
survey.tvd_at(7000)     # 5910 ft — end of build
survey.tvd_at(12000)    # 5910 ft — 5000 ft of lateral, no TVD gained
```

## What the error costs

Take a kick with SIDPP 350 psi in 10.2 ppg mud.

**Correct**, using TVD:

```
KMW = 10.2 + 350 / (0.052 × 5910) = 10.2 + 1.14 = 11.34 ppg
```

**Wrong**, using MD:

```
KMW = 10.2 + 350 / (0.052 × 12000) = 10.2 + 0.56 = 10.76 ppg
```

```python
sheet = examples.horizontal_well_kill_sheet()
sheet.kill_mud_weight_ppg                       # 11.34 ppg
10.2 + 350 / (0.052 * 12000)                    # 10.76 ppg
```

The mud is **0.58 ppg too light**. Circulating it around leaves the well roughly
180 psi underbalanced at the formation. The well does not die, it keeps flowing,
and the crew has just spent three hours confirming that their kill sheet was
wrong.

The error scales with `MD/TVD`. On this well that ratio is 2.03. On a modern
extended-reach well it can exceed 3.

## Influx behaviour in a lateral

This is where horizontal wells stop being "a vertical well with a correction
factor" and become genuinely different.

```python
from wellcontrol.kick import ShutInAnalysis

annulus, survey = examples.horizontal_well()
analysis = ShutInAnalysis(350, 380, 15, 10.2, annulus, survey)

analysis.influx_height_md_ft     # 903 ft of measured length
analysis.influx_height_tvd_ft    # 0 ft of vertical height
analysis.influx_top_md_ft        # 11097 ft — still well inside the lateral
```

A 15 bbl influx occupies over 900 ft of the lateral — the annulus out there is
narrow, only 0.0194 bbl/ft around 4in pipe in a 6in hole — and it contributes
**no hydrostatic head whatsoever**.

Three consequences follow.

### 1. The influx barely shows up on the casing gauge

The difference between SICP and SIDPP is caused entirely by the influx
displacing mud *vertically*. An influx lying in the lateral displaces nothing
vertically, so the two gauges read almost the same.

A near-zero difference between SICP and SIDPP does not mean a small kick on a
horizontal well. It means the kick is in the lateral.

### 2. The influx cannot be identified from the pressures

```python
analysis.influx_gradient_psi_per_ft
# ValueError: The influx has essentially no vertical height (0.00 ft), so its
# density cannot be resolved from the shut-in pressures...
```

The standard formula divides by influx height. In a lateral that height is zero
and the calculation is undefined — not approximately undefined, genuinely
undefined.

Identify the influx from returns at the gas trap instead, and plan for gas until
proven otherwise.

### 3. The influx does not migrate

Gas migrates because it is buoyant, and buoyancy needs a vertical direction to
act in. Gas in a horizontal lateral has nowhere to rise to. It sits there.

This cuts both ways. A shut-in horizontal well does **not** show steadily rising
surface pressure, which removes the time pressure that drives method selection
on a vertical well — Wait and Weight becomes more attractive because waiting
costs nothing.

But it also means gas accumulates in the lateral without announcing itself, and
when circulation starts it all arrives at the build section together. The
casing pressure profile during the kill can be much less gradual than on a
vertical well.

## Where the influx actually sits

The influx does not necessarily sit at the bit. It sits at the **highest point
it can reach**, which in a lateral with any undulation means the local high
spots, not total depth. Real laterals are rarely perfectly straight.

The library places influx from the bottom of the hole upward, which is the
standard planning assumption. On a well with a known undulating profile, treat
the result as indicative.

## Kill sheets on deviated wells

Everything else follows from the one rule:

| Quantity | Depth to use |
| --- | --- |
| Formation pressure | TVD |
| Kill mud weight | TVD |
| Hydrostatic, MAASP, kick tolerance | TVD |
| String volume, annulus volume | MD |
| Strokes to bit, strokes to surface | MD |
| Influx height | MD, then convert to TVD for pressure |

```python
sheet = examples.horizontal_well_kill_sheet()

sheet.bit_md_ft      # 12000 ft — used for volumes and strokes
sheet.bit_tvd_ft     # 5910 ft  — used for every pressure
```

The library takes a `Survey` and does the conversion internally, so the two
never get mixed up. Working by hand, the discipline is to write MD and TVD in
separate columns and never let a number cross over.

## The depth-accurate schedule earns its keep here

On a vertical well the straight-line pressure schedule is a good approximation.
On a deviated well it is less good, because equal stroke increments no longer buy
equal *vertical* depth — most of the TVD is gained in the vertical and build
sections, and none at all in the lateral.

```python
linear = sheet.schedule_linear(steps=10)
exact  = sheet.schedule_by_depth(steps=10)

for a, b in zip(linear, exact):
    print(f"{a.strokes:7.0f}  {a.drill_pipe_pressure_psi:6.0f}  "
          f"{b.drill_pipe_pressure_psi:6.0f}  "
          f"{a.drill_pipe_pressure_psi - b.drill_pipe_pressure_psi:+5.0f}")
```

Both agree at ICP and FCP. In between, the straight line calls for pressure
reductions the well has not actually earned yet.

## Building a survey

```python
from wellcontrol.survey import Survey, SurveyStation

# From a real survey
survey = Survey([
    SurveyStation(md=0,     tvd=0,    inclination_deg=0),
    SurveyStation(md=4000,  tvd=4000, inclination_deg=0),
    SurveyStation(md=7000,  tvd=5910, inclination_deg=90),
    SurveyStation(md=12000, tvd=5910, inclination_deg=90),
])

# Or generate a build-and-hold trajectory
survey = Survey.build_and_hold(
    kop_md=4000,
    build_rate_deg_per_100ft=3.0,
    final_inclination_deg=90,
    total_md=12000,
)
```

The constructor rejects physically impossible surveys — TVD gaining faster than
MD, or TVD decreasing — which catches transcription errors before they reach a
kill sheet.

---

Previous: [Kick tolerance and MAASP](07-kick-tolerance.md) · Next: [Subsea wells](09-subsea-wells.md)
