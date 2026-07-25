# 5. The kill sheet

## The principle

Hold bottomhole pressure slightly above formation pressure at every instant, and
the formation stops flowing. That is **constant bottomhole pressure**, and both
standard kill methods are implementations of it.

The problem is that bottomhole pressure cannot be measured. So the kill sheet
converts it into something that can: a schedule of **drill pipe pressure**
against **pump strokes**.

## Why the drill pipe gauge

The drill pipe is full of clean mud of known weight, so it is a reliable gauge
reading the bottom of the hole.

The annulus contains mud plus an influx whose size and position change every
stroke. Reading bottomhole pressure through it is guesswork.

So the rule during a kill is:

> **Follow the drill pipe pressure schedule. Use the choke to make the drill
> pipe gauge match it. Let the casing pressure do whatever it does.**

Casing pressure will rise, sometimes alarmingly, as gas expands near surface.
That is expected and correct. Chasing it instead of the drill pipe gauge is how
people over-pressure the shoe or let the well go underbalanced again.

## The four numbers

### Kill mud weight

```
KMW = OMW + SIDPP / (0.052 × TVD)
```

SIDPP is exactly the amount the mud was too light. Convert it to a density and
add it.

```python
from wellcontrol import examples
sheet = examples.vertical_land_well_kill_sheet()

sheet.kill_mud_weight_exact_ppg    # 10.369 ppg — calculated
sheet.kill_mud_weight_ppg          # 10.4   ppg — as mixed
```

9.6 + 400/(0.052 × 10,000) = 9.6 + 0.77 = 10.369, mixed as **10.4 ppg**.
Kill mud weight always rounds **up** to a tenth — see
[the rounding rules](#rounding-is-directional) below.

**TVD, not MD.** On a deviated well this is where kills fail — see
[Directional wells](08-directional-wells.md).

### Slow circulating rate pressure

The standpipe pressure at kill rate. **This is measured, not calculated**, and
it must be measured *before* it is needed — once a kick is in the hole there is
no way to take the reading without disturbing the well.

Taken every tour, at every rate that might be used, on every pump, and after
every change of mud weight or bit.

```python
from wellcontrol.killsheet import SlowCirculatingRate

scr = SlowCirculatingRate(spm=30, pressure_psi=600)
scr.scaled_to(60)     # 2400 psi — friction goes as rate squared
```

The scaling is for planning only. Measure the rate you intend to use.

### Initial circulating pressure

```
ICP = SIDPP + SCR
```

What the gauge should read once you are up to kill rate with the original mud
still in the string. The SIDPP part holds the formation back; the SCR part
pushes mud around the system.

```python
sheet.initial_circulating_pressure_psi    # 1000 psi
```

### Final circulating pressure

```
FCP = SCR × KMW / OMW
```

Once kill mud reaches the bit there is no SIDPP left to add — the mud balances
the formation on its own. But the heavier mud costs more friction, so FCP is
above the original SCR.

```python
sheet.final_circulating_pressure_psi      # 650 psi
```

600 × 10.4/9.6 = **650 psi** — built from the mud **as mixed**, not as
calculated. Scaling friction linearly with density is the
standard assumption and holds well at kill rates, where flow is
turbulent-dominated.

## The schedule

Between ICP and FCP, pressure comes down as kill mud displaces original mud down
the string. The classic kill sheet interpolates in a straight line:

```python
print(sheet.format_schedule(sheet.schedule_linear(steps=10)))
```

```
  Strokes  Volume bbl  Kill mud MD    DP psi  Note
------------------------------------------------------------
        0         0.0            0      1000
      147        17.2          969       965
      294        34.4         1937       930
      441        51.6         2906       895
      588        68.8         3875       860
      735        86.0         4843       825
      882       103.2         5812       790
     1029       120.4         6781       755
     1176       137.6         7749       720
     1323       154.8         8718       685
     1466       171.6        10000       650  Kill mud at the bit
```

**35 psi per step**, in whole psi — `(1000 − 650) / 10 = 35`. If the span had
not divided evenly the step would be rounded **down**, so the schedule finishes
slightly above FCP rather than below it.

This library also computes a **depth-accurate** schedule, which tracks where the
kill mud front actually is, converts that MD to TVD, and solves for the drill
pipe pressure that holds bottomhole pressure constant:

```
P_dp = Pf − [0.052 × KMW × TVD_front + 0.052 × OMW × (TVD_bit − TVD_front)]
          + friction
```

```python
print(sheet.format_schedule(sheet.schedule_by_depth(steps=10)))
```

Look at where it lands. The final 10% of the volume covers 1,306 ft of depth,
because the drill collars hold only 4.6 bbl over their 600 ft while drill pipe
holds 10.7 bbl over the same length. Equal stroke increments do not buy equal
depth. See [Directional wells](08-directional-wells.md) for the full breakdown
by section.

Both start at ICP. They no longer both finish at FCP — see the rounding note
below.

## Rounding is directional

Every rounding rule in well control goes the way that **adds margin**. None of
them is round-to-nearest.

| Quantity | Direction | Places | Why |
| --- | --- | :-: | --- |
| Kill mud weight | **up** | 1 | Heavier mud, more overbalance |
| Max allowable mud weight | **down** | 1 | Lower ceiling, less chance of fracturing |
| MAASP / MASP | **down** | 0 | Lower limit, more margin before breakdown |
| Pressure per step | **down** | 0 | Smaller decrement, pressure stays higher longer |
| Strokes | **up** | 0 | Stopping short of a target is the failure mode |

Pressures carry no decimals — no gauge on a rig resolves better than a few psi.
Strokes carry none either; there is no such thing as a fraction of a stroke.

```python
from wellcontrol import rounding

rounding.kill_mud_weight(10.37)          # 10.4
rounding.max_allowable_mud_weight(12.87) # 12.8
rounding.pressure_limit(1181.6)          # 1181
rounding.pressure_step(51.6)             # 51
rounding.strokes(1465.1)                 # 1466
```

**The rounded values are the operational ones.** The rig mixes 10.4 ppg, so FCP
is `600 × 10.4/9.6 = 650`, not `600 × 10.369/9.6 = 648`.

### Rounding up buys real overbalance

The mud actually mixed is heavier than the mud that exactly balances the
formation:

```
0.052 × (10.4 − 10.369) × 10,000 = 16 psi
```

```python
sheet.rounding_overbalance_psi      # 16.0
sheet.balanced_final_pressure_psi   # 634 — holds BHP exactly at Pf
sheet.final_circulating_pressure_psi # 650 — the number you hold
```

So holding FCP leaves the well **16 psi overbalanced**. That is the margin the
rounding rule exists to create, and it is why the depth-accurate schedule
finishes at 634 rather than 650: it solves for exactly balanced, while FCP
carries the margin. **Work to FCP.**

## Volumes and timing

```python
sheet.strokes_to_bit          # 1466
sheet.strokes_bit_to_surface  # 4017
sheet.total_strokes           # 5483
sheet.total_minutes()         # 183 minutes at 30 spm
```

Three hours. Kills are slow, and the crew has to hold concentration on a gauge
for all of it.

## Filling one in

The whole sequence:

1. Shut in. Record SIDPP, SICP, pit gain.
2. Check `SICP > SIDPP`. If not, stop and find out why.
3. `Pf = SIDPP + 0.052 × MW × TVD`
4. `KMW = MW + SIDPP / (0.052 × TVD)`
5. `ICP = SIDPP + SCR`
6. `FCP = SCR × KMW / MW`
7. Strokes to bit = string volume / pump output
8. Strokes bit to surface = annulus volume / pump output
9. Build the schedule between ICP and FCP over strokes to bit
10. Compute [MAASP](07-kick-tolerance.md) for the **kill** mud weight

Step 10 is the one most often skipped, and it is the one that tells you whether
the plan is survivable.

```python
for key, value in sheet.summary().items():
    print(f"{key:.<40} {value}")
```

## Bringing the pump up

Getting from shut-in to kill rate is its own small operation. Bottomhole
pressure must not change while it happens.

Hold **casing pressure constant** with the choke while bringing the pump slowly
to kill rate. As friction appears in the system, the choke opens to compensate.
Once at kill rate, the drill pipe gauge should read ICP — and from that point
you switch to following the drill pipe schedule.

If the gauge does not read ICP when you get there, the SCR was wrong. Adjust the
whole schedule by the difference rather than pretending the original number was
right.

---

Previous: [Kick detection and shut-in](04-kick-detection.md) · Next: [Circulation methods](06-circulation-methods.md)
