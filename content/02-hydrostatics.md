# 2. Hydrostatic pressure

## The equation

```
P = 0.052 × MW × TVD
```

- `P` — hydrostatic pressure, psi
- `MW` — mud weight, ppg
- `TVD` — **true vertical depth**, ft

That is the primary barrier, in one line.

### Where 0.052 comes from

One gallon of water weighs 8.33 lb. Spread over one square foot, a column of
fluid 1 ft tall with density 1 ppg weighs:

```
1 lb/gal × 7.48 gal/ft³ × 1 ft = 7.48 lb/ft²
```

Convert to per square inch (144 in² per ft²):

```
7.48 / 144 = 0.05194 psi/ft per ppg
```

Rounded to **0.052**. The exact value is 1/19.25 = 0.051948, a 0.1% difference —
far smaller than the uncertainty in the mud weight itself. Every kill sheet and
every certification exam uses 0.052.

```python
from wellcontrol.hydrostatics import hydrostatic_pressure

hydrostatic_pressure(9.6, 10000)              # 4992.0 psi
hydrostatic_pressure(9.6, 10000, exact=True)  # 4987.0 psi
```

## TVD, always

Hydrostatic pressure comes from the *weight* of the fluid column, and weight
acts vertically. A wellbore that goes sideways adds length but no weight.

This is worth stating starkly because it is the most consequential error in the
subject. See [Directional and horizontal wells](08-directional-wells.md) for
what it costs.

## Equivalent mud weight

Pressures at different depths cannot be compared directly. Converting them to
the mud weight that *would* produce them puts everything on one scale:

```
EMW = P / (0.052 × TVD)
```

```python
from wellcontrol.hydrostatics import equivalent_mud_weight

equivalent_mud_weight(4500, 9000)    # 9.615 ppg
equivalent_mud_weight(6000, 12000)   # 9.615 ppg
```

Two very different pressures, the same problem. Pore pressures, fracture
gradients and MAASP are all normally quoted as EMW for exactly this reason.

## Overbalance and trip margin

```python
from wellcontrol.hydrostatics import overbalance, trip_margin_mud_weight

overbalance(9.6, 4600, 10000)   # +392 psi — well is quiet
overbalance(9.0, 4992, 10000)   # -312 psi — well is flowing
```

Drilling at exactly balanced is not a plan. Any swab, any connection, any drop
in ECD puts the well underbalanced. Typical practice is 200–300 psi of
overbalance, or 0.2–0.5 ppg:

```python
trip_margin_mud_weight(4992, 10000, margin_psi=260)   # 10.1 ppg
trip_margin_mud_weight(4992, 10000, margin_ppg=0.3)   # 9.9 ppg
```

More overbalance is not automatically better. It costs rate of penetration, it
risks differential sticking, and it eats the margin to the fracture gradient —
see [Kick tolerance](07-kick-tolerance.md).

## Columns of more than one fluid

During a kick the annulus holds mud on top of influx. After a kill it holds two
mud weights. Subsea wells have seawater above mud.

```python
from wellcontrol.hydrostatics import FluidSegment, column_pressure

segments = [
    FluidSegment(9.6, 9000, "mud"),
    FluidSegment(2.0, 1000, "gas"),
]
column_pressure(segments)    # 4596.8 psi
```

Compare against 4992 psi for the same depth of pure mud. The gas has cost
395 psi of hydrostatic — which is precisely why the casing gauge reads higher
than the drill pipe gauge on a shut-in well.

```python
from wellcontrol.hydrostatics import equivalent_static_density

equivalent_static_density(segments, 10000)   # 8.84 ppg
```

## ECD — the pressure that appears when you start pumping

Circulating mud has to be pushed against friction in the annulus, and that
friction presses on the formation:

```
ECD = MW + APL / (0.052 × TVD)
```

```python
from wellcontrol.hydrostatics import equivalent_circulating_density

equivalent_circulating_density(9.6, 200, 10000)   # 9.985 ppg
```

Two consequences that shape a lot of operational practice:

- A well can be **stable while circulating and flow when the pumps stop**,
  because stopping removes the friction term. Every connection is a small
  reduction in bottomhole pressure.
- A well can be **static and start losing when the pumps come on**, because ECD
  can exceed the fracture gradient even when mud weight does not.

Where the gap between pore pressure and fracture gradient is narrower than the
ECD swing, no single mud weight is safe both circulating and static. That is the
textbook case for [MPD](11-mpd-and-ubd.md).

## Tripping

Pulling pipe removes steel from the hole. The volume has to be replaced or the
level falls.

```python
from wellcontrol.hydrostatics import (
    fill_volume_for_pipe_pulled,
    hydrostatic_drop_from_not_filling,
)

# Three stands (90 ft) of 5in x 4.276in drill pipe, open ended
fill_volume_for_pipe_pulled(0.0065242, 90)    # 0.587 bbl

hydrostatic_drop_from_not_filling(
    displacement_bbl_per_ft=0.0065242,
    length_pulled_ft=90,
    annular_capacity_bbl_per_ft=0.0489215,
    mud_weight_ppg=9.6,
)                                              # (12.0 ft, 5.99 psi)
```

Six psi sounds like nothing. Thirty stands without filling is 180 psi — more
than most trip margins.

**Open-ended vs closed-end matters.** Pipe run on a float does not fill as it
goes, so it displaces its full outside volume, not just the steel:

```python
from wellcontrol.geometry import (
    metal_displacement_bbl_per_ft,
    closed_end_displacement_bbl_per_ft,
)

metal_displacement_bbl_per_ft(5.0, 4.276)     # 0.00652 bbl/ft
closed_end_displacement_bbl_per_ft(5.0)       # 0.02429 bbl/ft — 3.7x more
```

Comparing the hole's actual fill against the wrong figure will either make a
quiet well look like it is flowing, or mask a real influx. The trip sheet exists
to make this comparison every few stands.

## Slugs

A heavy slug pumped into the string before a trip pushes the level inside the
pipe down, so stands come out dry instead of dumping mud on the floor.

```
0.052 × (SW − MW) × slug length in pipe  =  0.052 × MW × dry length
```

```python
from wellcontrol.hydrostatics import slug_volume_for_dry_pipe

slug_volume_for_dry_pipe(
    dry_length_ft=300,
    pipe_capacity_bbl_per_ft=0.0177620,
    mud_weight_ppg=9.6,
    slug_weight_ppg=12.5,
)    # 17.64 bbl
```

Note that a slug *reduces* the hydrostatic inside the string but leaves the
annulus alone, so it does not change bottomhole pressure once the well is
static — but it does mean the drill pipe gauge no longer reads the bottom of
the hole cleanly. Slug in the string is one of the reasons a SIDPP reading can
be misleading.

---

Previous: [Fundamentals](01-fundamentals.md) · Next: [Wellbore volumes and strokes](03-volumes-and-strokes.md)
