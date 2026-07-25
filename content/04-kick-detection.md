# 4. Kick detection and shut-in

## Detection is the whole game

The difficulty of killing a well scales with the size of the influx, and the
size of the influx scales with how long it took to notice. A 5 bbl kick is
arithmetic. A 100 bbl kick may exceed what the well can survive.

Everything about kick detection is therefore about **shortening the time between
the well starting to flow and someone noticing**.

## Flow check, then shut in

An indicator is not a conclusion. Pit gain can be a transfer. Flow increase can
be a pump speeding up. A drilling break is just soft rock.

The response to an indicator is a **flow check**: stop, pick up off bottom, and
watch the flowline with nothing moving. A well that flows with nothing pushing
it is flowing.

The response to a positive flow check is to **shut in**. Not to think about it,
not to circulate bottoms up first — shut in. Every barrel taken while deciding
makes the kill harder, and the influx is growing fastest at the start when the
underbalance is greatest.

## Hard shut-in vs soft shut-in

**Hard shut-in** closes the BOP with the choke already closed. Fastest, so the
influx is smallest. The objection is a pressure spike from stopping the flow
abruptly, which could damage the shoe.

**Soft shut-in** closes the BOP with the choke open, then closes the choke.
Avoids the spike but takes longer, so more influx enters.

Most operators now specify hard shut-in on most wells, on the reasoning that the
spike is modest and brief while the extra influx from a slow shut-in is
permanent. Follow the well-specific procedure — this is a decision made in the
drilling programme, not on the floor.

## The three numbers

Once shut in and the pressures have stabilised, you have everything you need:

| Reading | What it is |
| --- | --- |
| **SIDPP** | Shut-in drill pipe pressure |
| **SICP** | Shut-in casing pressure |
| **Pit gain** | Influx volume |

```python
from wellcontrol import examples
from wellcontrol.kick import ShutInAnalysis

annulus, survey = examples.vertical_land_well()

analysis = ShutInAnalysis(
    sidpp_psi=400,
    sicp_psi=660,
    pit_gain_bbl=20,
    mud_weight_ppg=9.6,
    annulus=annulus,
    survey=survey,
)
```

## Why SICP is always higher than SIDPP

Both gauges read the same bottomhole pressure by two different routes.

The **drill pipe** is full of clean mud of known weight. It is a reliable
pressure gauge reading the bottom of the hole.

The **annulus** contains mud *plus* an influx that is lighter than mud. Less
hydrostatic below means more pressure has to show at surface to balance the same
bottomhole pressure.

So `SICP > SIDPP`, always, and the difference is caused entirely by the influx.

**If SICP is not higher, stop.** Something is wrong: a plugged bit nozzle, a
float in the string preventing the drill pipe from reading, gas already up the
drill pipe, or a bad gauge. Do not fill in a kill sheet with numbers that fail
this check.

```python
analysis.validate()   # [] means the readings hang together
```

```python
ShutInAnalysis(400, 300, 20, 9.6, annulus, survey).validate()
# ['SICP (300 psi) is below SIDPP (400 psi). The influx is lighter than mud, ...',
#  'Computed influx density (12.54 ppg) is heavier than the mud (9.60 ppg). ...']
```

## Formation pressure

Read up the drill pipe, through clean mud:

```
Pf = SIDPP + 0.052 × MW × TVD
```

```python
analysis.formation_pressure_psi        # 5392.0 psi
analysis.formation_pressure_emw_ppg    # 10.369 ppg (unrounded — a
                                       # measurement, not a kill weight)
```

SIDPP *is* the underbalance — it is the exact amount by which the mud was too
light. That single reading tells you how much heavier the mud needs to be.

## Identifying the influx

The difference between the two gauges is the influx's signature.

Starting from the annulus pressure balance:

```
Pf = SICP + 0.052 × MW × (TVD − h) + G_influx × h
```

Substituting `Pf = SIDPP + 0.052 × MW × TVD` and solving:

```
G_influx = 0.052 × MW − (SICP − SIDPP) / h
```

where `h` is the **vertical** height of the influx.

```python
analysis.influx_height_md_ft        # 654.8 ft
analysis.influx_height_tvd_ft       # 654.8 ft (vertical well)
analysis.influx_gradient_psi_per_ft # 0.1021 psi/ft
analysis.influx_density_ppg         # 1.96 ppg
analysis.influx_type                # 'gas'
```

Rough density bands:

| Density | Influx |
| --- | --- |
| ≤ 4 ppg | Gas |
| 4–7 ppg | Oil, or a gas/liquid mix |
| 7–9.5 ppg | Salt water |

Treat anything ambiguous as gas. Mistaking gas for water is far more dangerous
than the reverse, because gas expands and water does not.

## Gas is the whole problem

Water and oil influxes are comparatively benign — they occupy roughly the same
volume at surface as they did at depth. Gas does not.

```python
from wellcontrol.kick import gas_expansion_boyle

gas_expansion_boyle(p1_psig=5000, v1_bbl=20, p2_psig=1000)   # 98.8 bbl
gas_expansion_boyle(p1_psig=100,  v1_bbl=1,  p2_psig=0)      # 7.8 bbl
```

Note that Boyle's law uses **absolute** pressure. Skipping that conversion is a
common mistake and it matters most near surface, where the ratio
`(100 + 14.7) / 14.7` is nearly 8.

The practical consequence: **gas expands most in the last few hundred feet.**
The choke is busiest, the casing pressure highest, and the pit gain fastest at
the very end of the circulation — long after the point where it feels like the
hard part is over.

## Migration

Gas that is not circulated migrates upward on its own. Shut in with the choke
closed, it cannot expand, so it carries its original pressure up the hole and
surface pressure rises:

```python
from wellcontrol.kick import gas_migration_rate_ft_per_hr

gas_migration_rate_ft_per_hr(pressure_rise_psi_per_hr=100, mud_weight_ppg=9.6)
# 200 ft/hr
```

Typical rates are 1,000–2,000 ft/hr in water-based mud. In oil-based mud gas
dissolves instead of migrating, which sounds better but is worse: it comes out
of solution suddenly and close to surface, with far less warning.

Steadily rising shut-in pressures mean gas is migrating, and the well is on a
clock — surface pressure will eventually reach the limit at the shoe. This is
the argument against long waits, and therefore an argument about which
[circulation method](06-circulation-methods.md) to use.

## Detection while tripping

Tripping has no flow to monitor and no pump pressure to watch. The only
indicator is **volume**, which is why the trip sheet is the primary safety
device during a trip.

Pulling pipe: the hole should take exactly the displacement of the steel
removed. Taking less means something is filling the space instead.

Running in: the hole should give back exactly what the steel displaces. Giving
back more means the same thing.

Measure every few stands against the calculated figure. The tolerance is small —
a few barrels — and the whole method depends on using the right displacement
figure for open-ended versus floated pipe.

---

Previous: [Wellbore volumes and strokes](03-volumes-and-strokes.md) · Next: [The kill sheet](05-kill-sheet.md)
