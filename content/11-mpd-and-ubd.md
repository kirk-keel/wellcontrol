# 11. MPD and underbalanced drilling

## The problem MPD solves

Conventional drilling controls bottomhole pressure with one lever: mud weight.
That lever is coarse and slow. Worse, bottomhole pressure swings every time the
pumps start or stop, because annular friction appears and disappears with them.

```python
from wellcontrol.hydrostatics import equivalent_circulating_density

equivalent_circulating_density(12.0, annular_pressure_loss_psi=400, tvd_ft=15000)
# 12.51 ppg circulating — vs 12.0 ppg static
```

A 0.5 ppg swing, every connection. If the window between pore pressure and
fracture gradient is narrower than that, **no single mud weight is safe both
circulating and static**:

```python
from wellcontrol.mpd import DrillingWindow

narrow = DrillingWindow(pore_pressure_ppg=12.0, frac_gradient_ppg=12.3,
                        tvd_ft=15000)
narrow.width_psi              # 234 psi
narrow.needs_mpd(annular_friction_psi=400)   # True
```

The ECD swing is 400 psi and the entire window is 234 psi. Conventional drilling
cannot thread that.

## The second lever

MPD closes the annulus with a **rotating control device** and adds surface
backpressure through a choke:

```
BHP = hydrostatic + annular friction + surface backpressure
```

```python
from wellcontrol.mpd import bottomhole_pressure, required_backpressure

bottomhole_pressure(mud_weight_ppg=12.0, tvd_ft=15000,
                    annular_friction_psi=400, surface_backpressure_psi=150)
# 9910 psi
```

The value of the choke is that it moves in **seconds**, where mud weight takes
hours.

## Constant bottomhole pressure through a connection

The classic application. As the pumps come down, friction falls roughly with the
square of the rate. The choke closes to replace it, so bottomhole pressure never
moves.

```python
from wellcontrol.mpd import connection_schedule

schedule = connection_schedule(
    target_bhp_psi=9700,
    mud_weight_ppg=11.9,
    tvd_ft=15000,
    full_rate_gpm=600,
    full_rate_friction_psi=300,
    steps=4,
)

for s in schedule:
    print(f"{s.flow_rate_gpm:>5.0f} gpm   friction {s.annular_friction_psi:>5.0f}   "
          f"choke {s.surface_backpressure_psi:>5.0f}   BHP {s.bottomhole_pressure_psi:>6.0f}")
```

```
  600 gpm   friction   300   choke   118   BHP   9700
  450 gpm   friction   169   choke   249   BHP   9700
  300 gpm   friction    75   choke   343   BHP   9700
  150 gpm   friction    19   choke   399   BHP   9700
    0 gpm   friction     0   choke   418   BHP   9700
```

Bottomhole pressure constant to the psi, all the way to pumps off. Conventionally
that same connection would have dropped it by the full 300 psi.

### Checking the RCD

The choke can only push pressure on, and the RCD has a rating:

```python
from wellcontrol.mpd import max_backpressure_check

max_backpressure_check(schedule, rcd_rating_psi=2000)   # []
```

Two failure modes get flagged:

- **Peak backpressure above the RCD rating.** The mud weight has to come up so
  less backpressure is needed.
- **Negative backpressure required.** A choke cannot pull pressure *off* a well.
  If the mud alone already exceeds the target, the mud weight has to come down.

```python
heavy = connection_schedule(9700, 12.4, 15000, 600, 300, steps=4)
max_backpressure_check(heavy, rcd_rating_psi=2000)
# ['The schedule calls for negative backpressure at some point, ...']
```

That is the design constraint of MPD in one line: **MPD works with mud that is
deliberately slightly too light**, and makes up the difference with the choke.

## MPD is not UBD

They share hardware and share almost none of their risk profile.

| | MPD | UBD |
| --- | --- | --- |
| Intent | Stay overbalanced, precisely | Stay underbalanced, deliberately |
| Influx | Unwanted; circulated out | The point; produced at surface |
| Surface equipment | Choke and RCD | Full separation package |
| Reason | Narrow window, wellbore stability | Reservoir productivity, no formation damage |

**MPD is a drilling technique.** UBD is a production operation that happens to
involve a drill bit.

A well being drilled with MPD still needs a conventional well control plan. The
RCD and choke manifold are a drilling tool with a limited pressure rating; **the
BOP stack remains the barrier.** When an MPD system runs out of capability, the
response is the same as any other well: shut in on the BOP and kill it
conventionally.

## Underbalanced drilling

```python
from wellcontrol.mpd import underbalance_psi, lightened_fluid_density

underbalance_psi(pore_pressure_psi=5000, mud_weight_ppg=9.6, tvd_ft=10000)
# +8 psi — the well is flowing, by design
```

Reaching bottomhole pressures below pore pressure usually means lightening the
fluid with injected nitrogen:

```python
lightened_fluid_density(base_fluid_ppg=9.0, gas_fraction=0.30)
# 6.33 ppg
```

`gas_fraction` is the **downhole** volume fraction, which is far smaller than the
surface injection ratio because the gas is compressed. A real UBD design needs
multiphase flow modelling; this is a first estimate.

The underbalance has to be maintained inside a band. Too little and the well
stops producing and may take formation damage — losing the whole reason for
drilling underbalanced. Too much and the surface separation package is
overwhelmed.

## Variants worth knowing

**Constant Bottomhole Pressure (CBHP)** — the connection case above. The most
common MPD variant by a wide margin.

**Pressurised Mud Cap Drilling (PMCD)** — for severe losses in fractured
carbonates, where returns are simply not coming back. A light annular fluid is
held under pressure while drilling fluid and cuttings are sacrificed to the
formation. Counter-intuitive, and very effective where it applies.

**Dual Gradient Drilling** — mostly deepwater. Two different fluid densities in
the well, typically by lifting mud from the seabed with a separate return line,
so the pressure profile better follows the pore pressure curve. Removes the
riser's contribution to the fracture problem.

**Returns Flow Control / HSE MPD** — using an RCD purely to contain returns
safely rather than to manage pressure. The lowest-complexity application.

## When to reach for MPD

```python
from wellcontrol.mpd import DrillingWindow

for pore, frac in ((12.0, 12.3), (12.0, 12.8), (12.0, 14.0)):
    w = DrillingWindow(pore, frac, 15000, safety_margin_ppg=0.1)
    print(f"{pore}-{frac} ppg: window {w.width_psi:>4.0f} psi, "
          f"MPD needed: {w.needs_mpd(400)}")
```

The honest test is whether the ECD swing fits inside the window. If it does,
conventional drilling is simpler, cheaper and better understood. If it does not,
the choice is MPD or another casing string.

---

Previous: [HPHT wells](10-hpht-wells.md) · Back to [index](../README.md)
