# 7. Kick tolerance and MAASP

## The window

A well has two limits.

**Below:** formation pressure sets how heavy the mud must be.
**Above:** fracture pressure at the casing shoe sets how heavy it can get before
the well breaks down and starts losing.

Everything in well control happens between them.

The shoe is the weak point because it is the shallowest exposed formation —
shallow rock is weaker, and pressure applied at surface adds to the pressure
everywhere below it. Breaking down the shoe during a kill produces an
**underground blowout**: the kicking formation flows into the shoe formation
inside the well, with no surface indication and no easy cure. It is a far worse
problem than the kick that caused it.

## Measuring formation strength

A **leak-off test (LOT)** pumps against a closed well until the formation below
the shoe starts to take fluid. The surface pressure at that point, converted to
a mud weight and added to the mud in the hole, is the formation's strength:

```
FG = MW_test + LOT / (0.052 × TVD_shoe)
```

```python
from wellcontrol.tolerance import frac_gradient_from_leak_off

frac_gradient_from_leak_off(
    test_mud_weight_ppg=9.0,
    leak_off_pressure_psi=1400,
    shoe_tvd_ft=7000,
)   # 12.85 ppg
```

A **formation integrity test (FIT)** stops at a predetermined pressure without
breaking down. It gives a *lower bound* — the well is at least that strong.
Feeding an FIT into the formula above tells you a minimum, not the strength.

## MAASP

Maximum Allowable Annular Surface Pressure — the most casing pressure the well
can be held at before the shoe breaks down:

```
MAASP = (FG − MW) × 0.052 × TVD_shoe
```

```python
from wellcontrol.tolerance import maasp

maasp(frac_gradient_ppg=12.8462, current_mud_weight_ppg=9.6, shoe_tvd_ft=7000)
# 1181 psi
```

**MAASP rounds down.** 1,181.6 is written as 1,181 — it is a limit, and
rounding up would claim margin the well does not have. The related figure
**MAMW**, the maximum allowable mud weight, rounds down to a tenth for the same
reason: a 12.85 ppg fracture gradient gives an MAMW of 12.8.

Two things about MAASP catch people out.

**It falls as mud weight rises.** Weighting up to kill the well eats into the
very margin needed to kill it:

```python
maasp(12.8462, 9.6, 7000)     # 1181 psi with original mud
maasp(12.8462, 10.4, 7000)    #  890 psi with kill mud
```

291 psi of margin gone, purely from the weight-up. Any MAASP figure written on a
kill sheet must state which mud weight it applies to, and the one that matters
during the kill is the **kill** mud weight.

**It is not a hard stop.** MAASP is a planning number. If holding below it means
letting the well go underbalanced and take a bigger influx, the shoe is not the
most urgent problem. Exceeding MAASP is bad; losing control of the well is
worse. This is a judgement call, which is why it belongs to a competent person
and not to a formula.

## Kick tolerance

Kick tolerance answers: **how big a kick can this well survive?**

It is not one number. It is a trade-off between two:

- **Kick intensity** — how much heavier than the mud the pore pressure turns out
  to be, in ppg.
- **Kick volume** — how much came in, in bbl.

A well can tolerate a large volume of a weak kick, or a small volume of an
intense one.

```python
from wellcontrol import examples
kt = examples.vertical_land_well_kick_tolerance()

for key, value in kt.summary(formation_pressure_psi=5392).items():
    print(f"{key:.<42} {value}")
```

```
Mud weight (ppg).......................... 9.6
Fracture gradient (ppg)................... 12.85
Fracture pressure at shoe (psi)........... 4676.0
MAASP (psi)............................... 1181
Kick intensity tolerance (ppg)............ 2.27
Max formation pressure (psi).............. 6174.0
Max influx height at shoe (ft)............ 1957.9
Max influx volume at shoe (bbl)........... 95.8
Max influx volume when taken (bbl)........ 84.8
```

### Kick intensity tolerance

With the annulus still full of mud — the instant of shut-in on a negligible
kick — the highest pore pressure that can be contained is:

```
Pf_max = P_frac + 0.052 × MW × (TVD_hole − TVD_shoe)
```

Expressed as a mud weight margin, that is **2.27 ppg** here. Read it as: the
pore pressure prediction could be 2.27 ppg light and the well would still
survive shutting in on it.

### Kick volume tolerance

The critical moment while circulating a gas kick out is when **the top of the
influx reaches the shoe**. Everything above it is mud, the gas has expanded on
the way up, and the shoe carries the most pressure it ever will.

Holding bottomhole pressure at formation pressure:

```
P_shoe = Pf − 0.052 × MW × (TVD_hole − TVD_shoe) + h × (0.052 × MW − G_influx)
```

Setting `P_shoe = P_frac` and solving for `h` gives the tallest tolerable influx
— 1,958 ft here, or **95.8 bbl at the shoe**.

Then work backwards with Boyle's law to find what that was **when it was
taken**: **84.8 bbl**. Gas expands on the way up, so the volume that is safe at
bottom is always smaller than the volume that is safe at the shoe.

```python
kt.max_influx_volume_at_shoe_bbl(5392)   # 95.8 bbl
kt.max_influx_volume_at_td_bbl(5392)     # 84.8 bbl
```

The 84.8 bbl figure is the one that matters on the rig floor, because the pit
gain indicator measures the influx at the moment it comes in.

### The trade-off, directly

```python
for intensity in (0.5, 1.0, 1.5, 2.0):
    print(f"{intensity:.1f} ppg kick -> {kt.max_pit_gain_bbl(intensity):.0f} bbl")
```

A more intense kick means less tolerable volume, because a heavier formation
pressure leaves less margin at the shoe before the influx even arrives.

## What it is for

Kick tolerance is a **planning** calculation, run before drilling ahead and
recomputed as the open hole lengthens. It answers questions like:

- Can we drill this next section safely, or do we need to set casing first?
- Is our kick detection good enough to catch an influx before it exceeds
  tolerance?
- What is the shallowest we can set the next shoe?

When the answer comes back too small — when the tolerable influx is smaller than
what the rig can realistically detect — the well needs a casing point, not a
better procedure.

## Assumptions worth knowing

The calculations here assume:

- The influx is a single continuous bubble sitting at the bottom of the annulus.
  Real influxes disperse and channel.
- Gas is ideal and isothermal. Real gas cools as it expands and is not ideal.
  Ignoring both slightly **over**-estimates expansion, so the result errs toward
  caution.
- Bottomhole pressure is held exactly at formation pressure throughout.
- The shoe is the only weak point. In a long open hole section that may not be
  true.

These are the standard planning assumptions and they are reasonable. But kick
tolerance is a number with a wide error bar, and it should not be used to
justify operating right at the edge of it.

---

Previous: [Circulation methods](06-circulation-methods.md) · Next: [Directional and horizontal wells](08-directional-wells.md)
