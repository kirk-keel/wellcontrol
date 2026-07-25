# 9. Subsea wells

Three things change when the BOP sits on the seabed instead of under the rig
floor. Each has its own arithmetic and each has caught people out.

## 1. Choke line friction

On a surface stack the choke line is a few tens of feet. On a subsea well it
runs the full water depth in a 2–3 inch line.

Circulating a kill through that line costs real friction pressure — commonly
200–500 psi, and more in deep water with heavy mud. That friction acts on the
**annulus**, which means it lands directly on the formation.

```python
from wellcontrol.subsea import choke_line_friction_measured

choke_line_friction_measured(
    scr_through_riser_psi=900,
    scr_through_choke_line_psi=1250,
)   # 350 psi
```

**Measure it, do not calculate it.** Take a slow circulating rate reading through
the riser, then the same rate through the choke line. The difference is the
friction. This is part of the pre-drill test programme on every subsea well.

### Correcting the kill sheet

Because that friction is already pressing on the formation, holding the normal
ICP on top of it would over-pressure the well by the whole amount:

```
ICP_subsea = SIDPP + SCR − CLF
```

```python
from wellcontrol import examples

with_clf = examples.deepwater_kill_sheet(choke_line_friction_psi=350)
without   = examples.deepwater_kill_sheet(choke_line_friction_psi=0)

with_clf.initial_circulating_pressure_psi   # 1050 psi
without.initial_circulating_pressure_psi    # 1400 psi
```

350 psi of over-pressure, applied for every stroke of a very long circulation.
On a well with a narrow margin that is enough to break down the shoe.

The alternative — used where reducing the drill pipe target is awkward — is to
hold the extra pressure off with the choke instead. One or the other must be
done.

### The second alternative: circulate up the riser

Some operations circulate the influx up the riser rather than the choke line,
avoiding the friction entirely. This puts gas inside the riser, above the BOP,
where it will expand rapidly and where there is no way to close anything below
it. It is done only with a diverter system and clear procedures, and generally
only for small, known-water influxes. Gas up the riser is not a decision made
casually.

## 2. The reference depth is the seabed

The BOP is at the mudline. Between the mudline and the rig floor there is water
and air gap — not formation.

```python
from wellcontrol.subsea import SubseaGeometry

geom = SubseaGeometry(air_gap_ft=75, water_depth_ft=5000, seawater_ppg=8.55)

geom.mudline_tvd_ft              # 5075 ft below the rotary table
geom.seawater_hydrostatic_psi    # 2223 psi at the mudline
```

Every depth used in a pressure calculation is a TVD **below the rotary table**,
including the 5,075 ft that is not rock.

### Gauge pressure vs stack pressure

Wellhead and BOP equipment ratings are quoted at the stack. The gauge is at the
rig floor. Between them sits a mud column:

```python
from wellcontrol.subsea import pressure_at_wellhead

pressure_at_wellhead(surface_gauge_psi=1000, mud_weight_ppg=12.5, geometry=geom)
# 4298.75 psi
```

A comfortable-looking 1,000 psi at the gauge is nearly 4,300 psi at the stack.
Checking a surface reading against a stack rating is a category error.

## 3. The riser can be disconnected

If the riser is disconnected — deliberately in a storm or a drive-off, or
accidentally — the mud above the mudline is replaced by seawater. Seawater is
much lighter than mud, so hydrostatic at the formation drops instantly.

```python
from wellcontrol.subsea import hydrostatic_loss_on_disconnect

hydrostatic_loss_on_disconnect(
    mud_weight_ppg=12.5, formation_tvd_ft=15000, geometry=geom
)   # 1076 psi
```

Over a thousand psi, gone the moment the connector releases. If the well was
carrying less than that in overbalance, it starts flowing — with the riser
disconnected and the rig moving off.

### Riser margin

Riser margin is the extra mud weight that keeps the well overbalanced through a
disconnect.

With the riser connected:

```
P = 0.052 × MW × TVD
```

After disconnect, mud fills only from the mudline down, with seawater above:

```
P = 0.052 × MW_new × (TVD − air gap − water depth) + 0.052 × SW × water depth
```

Setting them equal and solving:

```python
from wellcontrol.subsea import riser_margin_ppg

riser_margin_ppg(mud_weight_ppg=12.5, formation_tvd_ft=15000, geometry=geom)
# 2.08 ppg
```

**2.08 ppg.** On a well whose drilling window might be 1 ppg wide, carrying full
riser margin is simply impossible — the mud that survives a disconnect would
fracture the shoe while drilling.

This is not an edge case. Most deepwater wells are drilled **without** full riser
margin, as a conscious decision, relying instead on keeping the riser connected
and on procedures for a controlled disconnect. Riser margin is calculated so
that everyone knows how much exposure they are accepting, not because it can
always be carried.

```python
# Riser margin grows steeply with water depth
for wd in (500, 2000, 5000, 8000):
    g = SubseaGeometry(air_gap_ft=75, water_depth_ft=wd)
    print(f"{wd:>5} ft water -> {riser_margin_ppg(12.5, 15000, g):.2f} ppg")
```

## MAASP subsea

The formula is unchanged, as long as every depth is a TVD below the rotary table
and the annulus above the shoe is full of mud:

```
MAASP = (FG − MW) × 0.052 × TVD_shoe
```

```python
from wellcontrol.subsea import subsea_maasp

subsea_maasp(frac_gradient_ppg=14.0, mud_weight_ppg=12.5, shoe_tvd_ft=11000)
# 858 psi
```

The subsea complication is not the formula — it is remembering that the gauge
and the stack are 5,000 ft apart.

## Other differences worth knowing

**Long kills.** A deepwater well has a much larger total volume, so circulations
take far longer. The reference well here is 15,000 ft TVD with 5,000 ft of
riser; the total circulation runs to many thousands of strokes and several
hours.

**Trapped gas below the BOP.** Gas that migrates up to a closed subsea BOP sits
there. Bleeding it off means bleeding through the choke line, and the gas expands
violently on the way up.

**Shallow gas.** Before the BOP is installed there is no secondary barrier at
all. Shallow gas is handled by diverting, not shutting in — closing in on a
shallow gas flow with no casing set risks broaching to the seabed. This is a
genuinely different procedure with a different philosophy.

**Hydrates.** Cold seawater plus gas plus pressure forms hydrates, which plug
choke lines and BOP cavities at exactly the wrong moment. Managed with glycol or
methanol injection.

---

Previous: [Directional and horizontal wells](08-directional-wells.md) · Next: [HPHT wells](10-hpht-wells.md)
