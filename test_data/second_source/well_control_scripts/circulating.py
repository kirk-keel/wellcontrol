"""
Independent circulating model for the Test-1H dataset.

Built deliberately by a different route from a kill-sheet library: pressures
come from integrating the actual fluid column with bottomhole pressure pinned,
not from kill-sheet formulas.

Assumptions, all stated:
  * Wait-and-weight (engineer's) method, one circulation.
  * Bottomhole pressure held exactly constant at the shut-in value.
  * One continuous gas bubble; no slip, no migration relative to the mud, no
    solubility; isothermal ideal gas (Boyle's law) referenced to the pressure
    at the bottom of the bubble.
  * Gas gradient scales as 1/volume from 0.12 psi/ft at shut-in (mass is
    conserved), so the bubble lightens as it expands.
  * Friction is proportional to the volume fraction of kill mud in the string,
    which is the standard kill-sheet treatment.
  * Annular geometry taken from the tally, split at the 9-5/8in shoe.
"""
import json
import numpy as np
import pandas as pd

tally = pd.read_csv("/home/claude/wc/pipe_tally.csv")
srv = pd.read_csv("/home/claude/wc/directional_survey.csv")
S = json.load(open("/home/claude/wc/summary.json"))

TD = S["Bit_Depth_MD_ft"]
SHOE_MD = S["Intermediate_Shoe_MD_ft"]
OH = S["Open_Hole_Size_in"]
CSG_ID = S["Casing_ID_in"]
OMW = S["Mud_Weight_ppg"]
SIDPP = S["SIDPP_psi"]
SCR = S["Slow_Circulating_Pressure_psi"]
PUMP = S["Pump_Output_bbl_per_stk"]
PIT_GAIN = S["Pit_Gain_bbl"]
GAS_GRAD0 = S["Influx_Gradient_psi_per_ft"]
LOT = S["LOT_EMW_ppg"]

MD_GRID = np.array(list(srv.MD_ft) + [TD], float)
TVD_GRID = np.array(list(srv.TVD_ft) + [S["Bit_Depth_TVD_ft"]], float)


def tvd(md):
    return float(np.interp(md, MD_GRID, TVD_GRID))


TVD_TD = tvd(TD)
TVD_SHOE = tvd(SHOE_MD)

# recomputed here at full precision — do not read the rounded summary values
BHP = SIDPP + 0.052 * OMW * TVD_TD
KMW = OMW + SIDPP / (0.052 * TVD_TD)
ICP = SCR + SIDPP
FCP = SCR * KMW / OMW
MAASP = (LOT - OMW) * 0.052 * TVD_SHOE
FORM_P_SHOE = 0.052 * LOT * TVD_SHOE

# ---------------------------------------------- annular volume above the bit
segs = []
for _, r in tally.iterrows():
    top, bot, od = r.Top_Depth_ft, r.Bottom_Depth_ft, r.OD_in
    cuts = sorted({top, bot} | ({SHOE_MD} if top < SHOE_MD < bot else set()))
    for a, b in zip(cuts[:-1], cuts[1:]):
        hole = OH if (a + b) / 2 > SHOE_MD else CSG_ID
        segs.append((a, b, max(0.0, (hole ** 2 - od ** 2) / 1029.4)))
segs.sort(key=lambda s: s[0])

_md, _v = [TD], [0.0]
for a, b, cap in reversed(segs):
    _md.append(a)
    _v.append(_v[-1] + cap * (b - a))
ANN_V_ASC = np.array(_v)          # 0 -> V_ANN, ascending
ANN_MD_DESC = np.array(_md)       # TD -> 0, descending
V_ANN = float(_v[-1])


def md_from_annvol(v):
    """MD of the point lying v barrels of annulus above the bit."""
    return float(np.interp(min(max(v, 0.0), V_ANN), ANN_V_ASC, ANN_MD_DESC))


# ------------------------------------------- string volume below surface
s_sorted = tally.sort_values("Top_Depth_ft")
_smd, _sv = [0.0], [0.0]
for _, r in s_sorted.iterrows():
    _smd.append(r.Bottom_Depth_ft)
    _sv.append(_sv[-1] + r.Capacity_bbl_per_ft * r.Length_ft)
STR_MD = np.array(_smd)
STR_V = np.array(_sv)
V_STR = float(_sv[-1])


def md_from_strvol(v):
    return float(np.interp(min(max(v, 0.0), V_STR), STR_V, STR_MD))


def hydro(md_top, md_bot, ppg=None, grad=None):
    if md_bot <= md_top:
        return 0.0
    d = tvd(md_bot) - tvd(md_top)
    return 0.052 * ppg * d if ppg is not None else grad * d


def p_gas_bottom(V):
    """Pressure at the bottom of the bubble after V bbl pumped."""
    v_below = min(V, V_ANN)
    md_gb = md_from_annvol(v_below)
    v_kill = max(0.0, V - V_STR)
    if v_kill > 0:
        md_k = md_from_annvol(min(v_kill, V_ANN))
        below = hydro(md_k, TD, ppg=KMW) + hydro(md_gb, md_k, ppg=OMW)
    else:
        below = hydro(md_gb, TD, ppg=OMW)
    return BHP - below


def state(V):
    V = max(0.0, V)
    # ---- string side
    v_str = min(V, V_STR)
    md_front = md_from_strvol(v_str)
    frac = v_str / V_STR
    friction = SCR + (FCP - SCR) * frac
    hyd = 0.052 * KMW * tvd(md_front) + 0.052 * OMW * (TVD_TD - tvd(md_front))
    dpp_rig = BHP + friction - hyd
    s_bit = V_STR / PUMP
    strokes = V / PUMP
    dpp_lin = ICP - (ICP - FCP) * min(strokes, s_bit) / s_bit

    # ---- annulus side
    v_below = min(V, V_ANN)
    md_gb = md_from_annvol(v_below)
    v_kill = max(0.0, V - V_STR)
    md_k = md_from_annvol(min(v_kill, V_ANN)) if v_kill > 0 else None

    p_gb = p_gas_bottom(V)
    v_space = max(0.0, V_ANN - v_below)
    # Boyle's law, but the bubble can never occupy more than the space above the
    # pumped mud, and p_gb -> 0 at the very end of the kill must not blow up.
    v_gas_free = (BHP * PIT_GAIN / p_gb) if p_gb > 1e-6 else float("inf")
    v_gas = 0.0 if v_space <= 1e-9 else max(0.0, min(v_gas_free, v_space))
    venting = v_gas_free > v_space + 1e-9
    md_gt = md_from_annvol(v_below + v_gas)
    grad = GAS_GRAD0 * PIT_GAIN / v_gas if v_gas > 1e-9 else 0.0
    v_above = max(0.0, V_ANN - v_below - v_gas)

    column = []
    if v_above > 1e-9:
        column.append((0.0, md_gt, dict(ppg=OMW)))
    if v_gas > 1e-9:
        column.append((md_gt, md_gb, dict(grad=grad)))
    if v_kill > 0:
        column.append((md_gb, md_k, dict(ppg=OMW)))
        column.append((md_k, TD, dict(ppg=KMW)))
    else:
        column.append((md_gb, TD, dict(ppg=OMW)))

    def p_at(md):
        tot = 0.0
        for a, b, kw in column:
            lo, hi = max(a, md), b
            if hi > lo:
                tot += hydro(lo, hi, **kw)
        return BHP - tot

    return dict(
        Strokes=round(strokes),
        Pumped_bbl=round(V, 2),
        DPP_Conventional_psi=round(dpp_lin, 1),
        DPP_Rigorous_psi=round(dpp_rig, 1),
        Choke_Pressure_psi=round(p_at(0.0), 1),
        Shoe_Pressure_psi=round(p_at(SHOE_MD), 1),
        Gas_Volume_bbl=round(v_gas, 2),
        Gas_Pressure_psi=round(p_gb, 1),
        Gas_Bottom_MD_ft=round(md_gb, 1),
        Gas_Top_MD_ft=round(md_gt, 1),
        Gas_Height_MD_ft=round(md_gb - md_gt, 1),
        Gas_At_Surface=bool(v_gas > 1e-9 and v_above <= 1e-9),
        Gas_Venting=bool(venting and v_gas > 1e-9),
        Kill_Mud_String_MD_ft=round(md_front, 1),
        Kill_Mud_Annulus_MD_ft=round(md_k, 1) if md_k is not None else None,
        _vol_closure=round(v_below + v_gas + v_above - V_ANN, 9),
        _p_bit=round(p_at(TD), 4),
    )


def bisect(f, lo, hi, n=300):
    for _ in range(n):
        mid = 0.5 * (lo + hi)
        if f(mid) > 0:
            hi = mid
        else:
            lo = mid
    return 0.5 * (lo + hi)


# gas top reaches surface when v_below + v_gas_free = V_ANN  (increasing in V)
V_GAS_SURF = bisect(lambda v: v + BHP * PIT_GAIN / p_gas_bottom(v) - V_ANN,
                    0.0, V_ANN)

grid = sorted(set([round(x, 6) for x in np.arange(0, V_STR + V_ANN, 2.0)] +
                  [V_STR, V_ANN, V_GAS_SURF, V_STR + V_ANN]))
prof = pd.DataFrame([state(v) for v in grid])
diag = prof[["_vol_closure", "_p_bit"]]
prof = prof.drop(columns=["_vol_closure", "_p_bit"])
prof.to_csv("/home/claude/wc/circulating_profile.csv", index=False)

peak_shoe = prof.loc[prof.Shoe_Pressure_psi.idxmax()]
peak_choke = prof.loc[prof.Choke_Pressure_psi.idxmax()]
st0 = state(0.0)
st_bit = state(V_STR)
st_surf = state(V_GAS_SURF)
st_end = state(V_STR + V_ANN)

print("=== constants (recomputed at full precision) ===")
print(f"  BHP                  {BHP:9.2f} psi")
print(f"  KMW                  {KMW:9.4f} ppg")
print(f"  ICP / FCP            {ICP:9.2f} / {FCP:.2f} psi")
print(f"  MAASP                {MAASP:9.2f} psi")
print(f"  formation P at shoe  {FORM_P_SHOE:9.2f} psi")
print(f"  V_string / V_annulus {V_STR:9.2f} / {V_ANN:.2f} bbl")
print(f"  strokes to bit       {V_STR/PUMP:9.0f}")

print("\n=== endpoint checks against independently derived values ===")
print(f"  choke at 0 strokes   {st0['Choke_Pressure_psi']:9.1f} psi   "
      f"vs SICP {S['SICP_psi']:.0f} psi (from the generator's influx calc)")
print(f"  DPP at 0 strokes     {st0['DPP_Rigorous_psi']:9.1f} psi   vs ICP {ICP:.1f}")
print(f"  DPP at bit           {st_bit['DPP_Rigorous_psi']:9.1f} psi   vs FCP {FCP:.1f}")
print(f"  choke at kill        {st_end['Choke_Pressure_psi']:9.1f} psi   vs 0")
print(f"  bit pressure spread  {diag._p_bit.max()-diag._p_bit.min():9.4f} psi (must be 0)")
print(f"  volume-book closure  {diag._vol_closure.abs().max():9.2e} bbl")

pre = prof[(~prof.Gas_Venting) & (prof.Gas_Volume_bbl > 0)]
boyle = (pre.Gas_Pressure_psi * pre.Gas_Volume_bbl) / (BHP * PIT_GAIN)
print(f"  Boyle P*V/P0*V0      min {boyle.min():.5f}  max {boyle.max():.5f}")

print("\n=== results ===")
print(f"  max |rigorous DPP - straight line| : "
      f"{(prof.DPP_Rigorous_psi-prof.DPP_Conventional_psi).abs().max():.1f} psi")
print(f"  gas top reaches surface  : {V_GAS_SURF/PUMP:.0f} strokes "
      f"({V_GAS_SURF:.1f} bbl), gas volume {st_surf['Gas_Volume_bbl']:.1f} bbl "
      f"(x{st_surf['Gas_Volume_bbl']/PIT_GAIN:.2f})")
print(f"  peak choke pressure      : {peak_choke.Choke_Pressure_psi:.0f} psi at "
      f"{peak_choke.Strokes:.0f} strokes")
print(f"  peak shoe pressure       : {peak_shoe.Shoe_Pressure_psi:.0f} psi at "
      f"{peak_shoe.Strokes:.0f} strokes")
print(f"  shoe margin at peak      : {FORM_P_SHOE-peak_shoe.Shoe_Pressure_psi:.0f} psi "
      f"below formation integrity")
print(f"  gas fully out            : {V_ANN/PUMP:.0f} strokes")
print(f"  kill complete            : {(V_STR+V_ANN)/PUMP:.0f} strokes")

json.dump(dict(
    BHP_psi=round(BHP, 1), KMW_ppg=round(KMW, 4),
    ICP_psi=round(ICP, 1), FCP_psi=round(FCP, 1),
    MAASP_psi=round(MAASP, 1), formation_pressure_at_shoe_psi=round(FORM_P_SHOE, 1),
    V_string_bbl=round(V_STR, 2), V_annulus_bbl=round(V_ANN, 2),
    strokes_to_bit=round(V_STR / PUMP),
    strokes_gas_top_to_surface=round(V_GAS_SURF / PUMP),
    gas_volume_at_surface_bbl=round(st_surf["Gas_Volume_bbl"], 1),
    gas_expansion_ratio=round(st_surf["Gas_Volume_bbl"] / PIT_GAIN, 2),
    strokes_gas_fully_out=round(V_ANN / PUMP),
    strokes_kill_complete=round((V_STR + V_ANN) / PUMP),
    peak_choke_psi=round(float(peak_choke.Choke_Pressure_psi)),
    peak_choke_strokes=int(peak_choke.Strokes),
    peak_shoe_psi=round(float(peak_shoe.Shoe_Pressure_psi)),
    peak_shoe_strokes=int(peak_shoe.Strokes),
    shoe_margin_at_peak_psi=round(FORM_P_SHOE - float(peak_shoe.Shoe_Pressure_psi)),
    max_dpp_schedule_deviation_psi=round(
        float((prof.DPP_Rigorous_psi - prof.DPP_Conventional_psi).abs().max()), 1),
), open("/home/claude/wc/circulating_summary.json", "w"), indent=2)
print("\nwrote circulating_profile.csv  (%d rows)" % len(prof))
