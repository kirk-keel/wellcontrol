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
KMW = 10.2 + 350 / (0.052 × 5910) = 10.2 + 1.14 = 11.339 → mixed as 11.4 ppg
```

**Wrong**, using MD:

```
KMW = 10.2 + 350 / (0.052 × 12000) = 10.2 + 0.56 = 10.761 → mixed as 10.8 ppg
```

```python
sheet = examples.horizontal_well_kill_sheet()
sheet.kill_mud_weight_ppg                       # 11.4 ppg
rounding.kill_mud_weight(10.2 + 350/(0.052*12000))   # 10.8 ppg
```

The mud is **0.6 ppg too light**. Circulating it around leaves the well roughly
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

## One schedule is not enough

On a vertical well with a uniform string, the straight line from ICP to FCP is
correct. On a directional well it is not — and not merely imprecise. **The
schedule needs a separate segment for each section, and in the lateral it
reverses.**

```python
print(sheet.format_segments())
```

```
Section       From MD    To MD   Strokes          DP psi  psi/100 stk
------------------------------------------------------------------------
Vertical            0     4000       370    1100 -> 880      59.3 down
Build            4000     7000       278     880 -> 784      34.8 down
Lateral          7000    11600       426     784 -> 818       8.1 UP
Lateral         11600    12000        17     818 -> 819       8.1 UP
```

Three regimes, and note the sign in the lateral. **Drill pipe pressure has to be
taken UP through the lateral, after coming down for the whole build.**

The reason: drill pipe pressure is `Pf − hydrostatic + friction`. Once the kill
mud front is in the lateral it gains no TVD, so the hydrostatic term stops
increasing — but friction keeps climbing toward FCP as more kill mud fills the
string. Net effect: pressure rises.

A driller following a single straight line from ICP to FCP would be **bleeding
pressure off through the lateral at exactly the point he should be adding it.**

### The schedule also breaks at every pipe size change

Look at the split at 11,600 ft — that is the top of the drill collars, not a
trajectory change. A stroke of the pump moves the kill mud front a different
distance above and below it, so the strokes-to-depth relationship changes.

Even the vertical reference well needs two segments for this reason:

```
Vertical            0     9400      1427    1000 -> 658      24.0 down
Vertical         9400    10000        39     658 -> 634      60.0 down
```

The last 600 ft of collars takes 39 strokes and needs pressure coming down two
and a half times as fast. On a tapered string there is a break at every size
change.

```python
sheet.schedule_segments()          # the breakdown
sheet.drill_pipe_pressure_at(md)   # pressure with the front at any depth
```

## Import the real survey

Everything above uses a generated build-and-hold trajectory: a constant build
rate and a perfectly straight lateral. Real wells are neither, and kill mud
weight comes straight off TVD.

```python
from wellcontrol.importers import import_survey

outcome = import_survey("samples/survey_horizontal.csv")
outcome.survey.total_tvd                 # 5,909 ft
outcome.survey.max_inclination_deg       # 90.3
outcome.survey.max_dogleg_severity       # 3.0 deg/100 ft
outcome.tvd_was_computed                 # True
```

The file needs measured depth and inclination. Headers are matched loosely, so
`MD`, `Measured Depth`, `Depth` and `Hole Depth` all work.

**TVD is computed by minimum curvature** — the industry standard, which fits a
circular arc between stations rather than assuming the hole runs straight
between them. Through a build the difference accumulates: over a 0-to-90°
build in 1,000 ft of hole, straight-line averaging gives 500 ft of TVD where
the arc gives 637 ft. If the file carries its own TVD column that is used
instead, because the surveyor's TVD is authoritative.

### A real lateral goes uphill

The sample survey has stations at 90.1°, 89.8°, 90.2° — the hole wanders either
side of horizontal, which is what real laterals do. Two consequences worth
knowing:

**TVD comes back up in places.** A well control library that insists TVD only
increases will reject a perfectly ordinary horizontal well. Only a TVD change
*faster* than the measured depth change is impossible.

**A point ahead of the kill mud front can be deeper than the bit.** The
hydrostatic contribution of that interval is genuinely negative. Anywhere both
ends of a span come from a survey, the span is signed:

```python
from wellcontrol.hydrostatics import signed_hydrostatic

signed_hydrostatic(11.4, -40.0)    # -23.7 psi — the hole rose
```

## Import the pipe tally

The same argument applies to the string. Strokes to bit comes off string
volume, and a real tally has eight or ten components across several sizes:

```python
from wellcontrol.importers import import_tally

outcome = import_tally("samples/pipe_tally.csv", expected_bit_depth_ft=12000)
len(outcome.components)          # 8
outcome.total_length_ft          # 11,985
outcome.internal_volume_bbl      # 125.2
outcome.warnings                 # the 15 ft gap to the bit
```

A `Joints` or `Count` column multiplies the length, so a tally can say "12
joints at 30.5 ft" rather than 366.

Importing both changes the schedule breakdown from four segments to five on
this well, because the real BHA introduces its own pipe size changes. Segments
shorter than a few strokes are merged — a 4.5 ft bit sub is technically a break
in the schedule, but not one a driller can work to.

**The string must fit the hole.** An 8 in collar in a 6 in lateral is rejected
by name:

```
'8in Drill Collars' has an outside diameter of 8.0 in, which does not fit
inside '6in Lateral' at 6.0 in. They overlap between 9,500 and 10,000 ft MD.
Check the pipe tally is for this hole section.
```

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
