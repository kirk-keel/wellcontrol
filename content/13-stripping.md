# 13. Stripping and snubbing

## Where this fits

Stripping is not a kill method. It is the operation that makes a kill possible
when the bit is off bottom.

The sequence:

1. A kick is taken with the bit **off bottom** — mid-trip, or after pulling off
   to make a connection. There is no circulation path to the influx, so neither
   Driller's nor Wait and Weight can be run.
2. The [Volumetric Method](07-kick-tolerance.md) holds bottomhole pressure while
   gas migrates. It buys time and margin. **It does not kill the well.**
3. **Stripping** returns the bit to bottom through closed BOPs, restoring the
   circulation path.
4. A conventional circulating kill finishes the job.

Step 3 is where most of the risk sits: pipe is moving in a live well, the volume
balance is manual, and the pipe may be trying to eject itself.

## The one idea

Running pipe into a closed well adds steel to a fixed volume. That volume has to
come out, or the pressure spikes:

```
volume to bleed per foot = closed-end displacement = OD² / 1029.4
```

Bleed exactly that and the mud level — and therefore hydrostatic, and therefore
bottomhole pressure — does not move.

**Volume is the control variable, not pressure.** A calibrated trip tank is the
instrument that matters. Casing pressure is the confirmation, not the target.

## Closed end, always

Stripping is done with a **float** in the string. Without one, the well flows up
the inside of the pipe with nothing to stop it.

The float means the pipe does not fill as it goes, so it displaces its **full
outside diameter**, not just the steel:

```python
from wellcontrol.geometry import (
    closed_end_displacement_bbl_per_ft,
    metal_displacement_bbl_per_ft,
)

closed_end_displacement_bbl_per_ft(5.0)          # 0.02429 bbl/ft
metal_displacement_bbl_per_ft(5.0, 4.276)        # 0.00652 bbl/ft
```

**A factor of 3.72.** Bleeding to the open-ended figure would leave you removing
barely a quarter of what the well is taking, and bottomhole pressure would climb
toward the fracture pressure at the shoe with every stand.

## Bleed volume per stand

```python
from wellcontrol.stripping import StrippingOperation

operation = StrippingOperation(
    pipe_od_in=5.0, pipe_id_in=4.276, pipe_weight_lb_per_ft=19.5,
    stand_length_ft=93.0,
    start_depth_md_ft=8500.0, target_depth_md_ft=10000.0,
    annular_capacity_bbl_per_ft=0.070186,
    mud_weight_ppg=9.6, surface_pressure_psi=400.0,
    migration_rate_ft_per_hr=1000.0, minutes_per_stand=6.0,
)

operation.volume_per_stand_bbl              # 2.26 bbl  (pipe displacement)
operation.migration_bleed_per_stand_bbl     # 7.02 bbl  (gas migrating)
operation.total_bleed_per_stand_bbl         # 9.28 bbl
operation.stands_required                   # 17
operation.total_displacement_bbl            # 36.4 bbl
```

### The migration allowance usually dominates

Look at those two numbers again. The pipe displaces **2.26 bbl** per stand. Gas
migrating at 1,000 ft/hr during the six minutes a stand takes requires
**7.02 bbl** — three times as much.

The derivation is neat: gas rising a distance `d` raises surface pressure by
`0.052 × MW × d`. Removing that means bleeding a mud column of the same height,
which is `d × annular capacity` of volume. **The mud weight cancels** — the
answer is just the volume the gas swept:

```
100 ft × 0.070186 bbl/ft = 7.02 bbl
```

Bleeding only the pipe displacement, on a well where gas is migrating, means the
well gains pressure steadily and the shoe is doing the paying.

## The balance point — stripping versus snubbing

Well pressure pushes the pipe **up**, on the full cross-section of the closed
end. The pipe goes in under its own weight only while it outweighs that force:

```
force up = P × (π/4) × OD²
weight   = weight per foot × length × buoyancy factor
```

```python
operation.upward_force_lbf        # 7,854 lbf at 400 psi
operation.buoyancy_factor         # 0.853 at 9.6 ppg
operation.balance_point_ft        # 472 ft
operation.snubbing_required       # False — the bit is at 8,500 ft
```

Worked through: `400 × 19.635 = 7,854 lbf` against `19.5 × 0.853 = 16.64 lb/ft`,
so `7,854 / 16.64 = 472 ft`.

Below 472 ft of pipe in the hole, the string is lighter than the force trying to
eject it. That is **snubbing**, and it needs a snubbing unit — not a rig floor.

**The dangerous combination is a shallow bit and a high surface pressure**, and
the balance point scales directly with pressure:

```python
well = examples.well_state(config, bit_off_bottom_ft=9200.0)   # bit at 800 ft
well.sicp_psi = 900.0

plan = plan_kill(well, "stripping")
plan.summary["Upward force on pipe (lbf)"]   # 17,671
plan.summary["Balance point (ft)"]           # 1,062
plan.summary["Snubbing required"]            # 'yes'
```

At 900 psi the balance point is 1,062 ft and the bit is at 800 ft — the string
would be pushed out of the hole.

## Missing a bleed

```python
from wellcontrol.stripping import pressure_rise_if_not_bled

pressure_rise_if_not_bled(
    volume_displaced_bbl=2.26, gas_volume_bbl=20.0, surface_pressure_psi=400.0
)   # 453 psi
```

One missed stand takes surface pressure from 400 to 453 psi, because the 2.26 bbl
has nowhere to go but into compressing the gas:

```
P2 = 414.7 × 20 / (20 − 2.26) − 14.7 = 453 psi
```

And the less gas there is to compress, the worse it gets. With no gas at all the
mud is effectively incompressible and the rise is limited only by the stiffness
of the mud and the casing. This is why the trip tank measurement is not optional.

## Annular or ram-to-ram

| Technique | When |
| --- | --- |
| **Through the annular preventer** | Up to roughly 1,500 psi. Continuous; closing pressure is reduced so tool joints can pass. |
| **Ram to ram (surge stripping)** | Higher pressures. Alternate between two sets of pipe rams. Slower. |

```python
operation.recommended_technique     # StripTechnique.ANNULAR
```

A rule of thumb only. The real limit is the annular element's rating and
condition, and the operator's procedure.

## Surge

Running pipe pushes mud up the annulus and drags some along with it. That
friction adds directly to bottomhole pressure:

```python
from wellcontrol.stripping import surge_pressure_estimate
from wellcontrol import examples

surge_pressure_estimate(
    pipe_speed_ft_per_min=60, hole_id_in=8.5, pipe_od_in=5.0,
    length_ft=8000, model=examples.standard_mud_rheology(), mud_weight_ppg=9.6,
)
```

A rough estimate, and deliberately so — it answers "is this fast enough to
matter?" On a well with little margin at the shoe, surge sets the stripping
speed.

## Stripping and the kill are one operation

Planning them separately hides what matters: the total time the well is open,
and which of the two phases actually puts the most pressure on the shoe.

```python
from wellcontrol.methods import strip_then_kill

sequence = strip_then_kill(well, "drillers")

sequence.total_hours              # 7.0  (1.7 stripping + 5.3 kill)
sequence.peak_shoe_pressure_psi   # highest across BOTH phases
sequence.worst_phase              # which one produced it
```

On the horizontal reference well the answer is **stripping, not the kill** —
the gas migrating up while the pipe goes back to bottom does more to the shoe
than the circulation that follows. Planning the kill in isolation would miss
that entirely.

Choosing the follow-on method changes the totals substantially:

| Follow-on | Stripping | Kill | Total |
| --- | ---: | ---: | ---: |
| Driller's Method | 1.7 hr | 5.3 hr | **7.0 hr** |
| Wait and Weight | 1.7 hr | 3.0 hr | **4.7 hr** |

Both reach the same 10.37 ppg kill mud weight and the same peak shoe pressure;
the difference is entirely in exposure time.

## Running it

```python
from wellcontrol import examples, plan_kill
from wellcontrol.wellconfig import WellConfiguration, BOPLocation, Trajectory

well = examples.well_state(
    WellConfiguration(BOPLocation.SURFACE, Trajectory.VERTICAL),
    bit_off_bottom_ft=1500.0,
)
plan = plan_kill(well, "stripping")

for stage in plan.stages:
    print(stage.name)
    for action in stage.actions:
        print("   -", action)
```

The plot adds a fifth panel — bit depth against stand number — alongside the
pressure, shoe and influx panels. On the reference well, surface pressure climbs
from 400 to 507 psi as gas migrates during the 17 stands, and there is a visible
kink where the gas top passes the bit into the narrower drill-pipe annulus.

## Off bottom, the drill pipe gauge does not read the formation

Worth stating on its own, because every kill sheet formula assumes otherwise.

SIDPP measures pressure at the **bit**. When the bit is on bottom, that is the
formation. When it is off bottom, the formation is deeper, and whatever lies
between adds hydrostatic that the standard formula omits:

```
Pf = SIDPP + 0.052 × MW × TVD_bit + hydrostatic below the bit
```

```python
well.hydrostatic_below_bit_psi     # 635 psi with the bit 1,500 ft off bottom
well.formation_pressure_psi        # 5,278 psi, including it
```

Six hundred psi is not a rounding error. And a related consequence: **with the
influx entirely below the bit, SICP equals SIDPP** — both gauges read through
the same clean mud to the bit and through the same fluids below it. A difference
between them means the influx has risen above the bit.

---

Previous: [Choosing a kill method](12-choosing-a-kill-method.md) · Back to [index](README.md)
