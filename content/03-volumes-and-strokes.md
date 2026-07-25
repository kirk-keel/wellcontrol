# 3. Wellbore volumes and strokes

## Why strokes are the unit of position

During a kill nobody can see where the influx is. The only way to know is to
count pump strokes and convert them to a position in the hole. "The gas is 400
strokes from surface" is what lets the choke operator anticipate rather than
react.

Every stroke calculation reduces to a volume divided by pump output, and every
volume reduces to one constant.

## Capacity

```
capacity (bbl/ft) = ID(in)² / 1029.4
```

The 1029.4 is unit bookkeeping. A cylinder of diameter D inches and length 1 ft
holds `(π/4) × D² × 12` cubic inches, and a 42-gallon barrel is 9702 cubic
inches:

```
(π/4 × 12) / 9702  =  1 / 1029.4
```

```python
from wellcontrol.geometry import capacity_bbl_per_ft, annular_capacity_bbl_per_ft

capacity_bbl_per_ft(4.276)               # 0.017762 bbl/ft — inside 5in DP
annular_capacity_bbl_per_ft(8.5, 5.0)    # 0.045900 bbl/ft — 8.5in hole / 5in DP
```

For an annulus, subtract the pipe occupying the space:

```
annular capacity (bbl/ft) = (hole ID² − pipe OD²) / 1029.4
```

## Three displacements, easily confused

| Quantity | Formula | Used for |
| --- | --- | --- |
| Capacity | `ID² / 1029.4` | Volume *inside* the pipe |
| Metal displacement | `(OD² − ID²) / 1029.4` | Open-ended pipe — hole fill |
| Closed-end displacement | `OD² / 1029.4` | Pipe on a float — hole fill |

For 5in × 4.276in drill pipe those are 0.01776, 0.00652 and 0.02429 bbl/ft.
Using the wrong one on a trip sheet is a well control error, not a bookkeeping
error.

## Building a well

The library models the hole and the string separately, then overlays them.

```python
from wellcontrol.geometry import (
    Annulus, DrillString, HoleSection, Pipe, Wellbore,
)

wellbore = Wellbore([
    HoleSection("9-5/8in Casing", id_in=8.681, top_md=0, bottom_md=7000),
    HoleSection("8-1/2in Open Hole", id_in=8.5, top_md=7000, bottom_md=10000,
                is_open_hole=True),
])

collars = Pipe("6-1/2in Drill Collars", od_in=6.5, id_in=2.8125, length_ft=600)
drill_pipe = Pipe("5in Drill Pipe", od_in=5.0, id_in=4.276, length_ft=0)

string = DrillString.from_bha([collars], drill_pipe, bit_depth_md=10000)
annulus = Annulus(wellbore, string)
```

`from_bha` computes the drill pipe length needed to reach surface, so you never
have to subtract BHA lengths by hand.

## Why the overlay matters

`Annulus` splits the well at **every** geometry change — casing shoes, bit
depth, and every change of pipe OD:

```python
for i in annulus.intervals:
    print(f"{i.top_md:>7.0f} - {i.bottom_md:>7.0f}  "
          f"{i.capacity_bbl_per_ft:.5f} bbl/ft  {i.description}")
```

```
      0 -    7000  0.04892 bbl/ft  9-5/8in Casing / string
   7000 -    9400  0.04590 bbl/ft  8-1/2in Open Hole / string
   9400 -   10000  0.02914 bbl/ft  8-1/2in Open Hole / string
```

The collar annulus holds about 64% of what the drill pipe annulus holds per
foot. This is the detail that decides how tall an influx is.

## Influx height

A 20 bbl influx sitting on bottom:

```python
annulus.height_of_volume_from_bottom(20.0)   # 654.8 ft
```

Worked through:

- Collar annulus: 600 ft × 0.029143 = **17.49 bbl**
- Remaining: 20 − 17.49 = **2.51 bbl**
- At 0.045900 bbl/ft that is **54.8 ft**
- Total: 600 + 54.8 = **654.8 ft**

Treating the annulus as uniformly 0.045900 bbl/ft gives 435.7 ft — a 33%
under-estimate. Since influx height feeds directly into the influx density
calculation and into kick tolerance, that error propagates into everything
downstream.

## Volumes and strokes

```python
from wellcontrol import examples

annulus, survey = examples.vertical_land_well()
pump = examples.standard_pump()

annulus.string.internal_volume_bbl    # 171.6 bbl
annulus.volume_bbl                    # 470.1 bbl
pump.output_bbl_per_stroke            # 0.11704 bbl/stk

pump.strokes_for(171.6)               # 1466 strokes to bit
pump.strokes_for(470.1)               # 4017 strokes bit to surface
```

## Pump output

**Triplex** (single acting, three cylinders):

```
bbl/stk = 0.000243 × liner ID² × stroke length × efficiency
```

**Duplex** (double acting, two cylinders — the rod occupies part of the
cylinder on the return stroke):

```
bbl/stk = 0.000162 × stroke length × (2 × liner ID² − rod OD²) × efficiency
```

```python
from wellcontrol.geometry import Pump

Pump(liner_id_in=6.5, stroke_length_in=12, efficiency=0.95).output_bbl_per_stroke
# 0.11704 bbl/stk

Pump(liner_id_in=6.0, stroke_length_in=12, kind="duplex",
     rod_od_in=2.0).output_bbl_per_stroke
# 0.13219 bbl/stk
```

**Volumetric efficiency is not optional.** A pump at 95% delivers 5% less than
the geometry says. Over a 5,500 stroke kill that is 275 strokes of error — the
kill mud arrives at the bit later than the schedule expects, and the driller is
holding the wrong pressure for the last 300 strokes. Efficiency should be
measured, not assumed.

## A critical distinction: strokes to bit vs strokes to surface

```python
sheet = examples.vertical_land_well_kill_sheet()

sheet.strokes_to_bit             # 1466  — kill mud reaches the bit
sheet.strokes_bit_to_surface     # 4017  — influx reaches surface
sheet.total_strokes              # 5482  — one full circulation
```

These count from the same instant but measure different things. Mud is
incompressible, so **the annulus starts moving the moment the pump starts** —
the influx does not wait for kill mud to reach the bit.

- The **influx** reaches surface after 4,017 strokes.
- The **kill mud** reaches the bit after 1,466 strokes, and surface after 5,482.

Confusing the two is how people expect gas at the choke at the wrong time.

## Bottoms-up

The time for anything at the bit to reach surface:

```python
pump.minutes_for(annulus.volume_bbl, spm=30)    # 134 minutes
```

Bottoms-up is how you know whether a gas show is from the depth you are drilling
now or from something you drilled two hours ago.

---

Previous: [Hydrostatic pressure](02-hydrostatics.md) · Next: [Kick detection and shut-in](04-kick-detection.md)
