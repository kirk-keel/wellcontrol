"""
Generate realistic well control test data:
  - Joint-by-joint drill pipe tally
  - Directional survey (minimum curvature)
Well: land well, build-and-hold, 12,500 ft MD.
Field units throughout.
"""
import math
import random
import json
import pandas as pd

random.seed(20260724)

# ----------------------------------------------------------------------------
# WELL CONFIGURATION
# ----------------------------------------------------------------------------
TD_MD = 12500.00          # bit depth, ft MD
KOP = 2000.0              # kick-off point, ft MD
BUILD_RATE = 2.5          # deg / 100 ft
TARGET_INC = 35.0         # deg
EOB = KOP + (TARGET_INC / BUILD_RATE) * 100.0   # end of build, ft MD

SURF_SHOE_MD = 1800.0     # 13-3/8" shoe
INT_SHOE_MD = 8200.0      # 9-5/8" shoe  <- the shoe that governs MAASP
CSG_ID = 8.681            # 9-5/8" 47.0 ppf N-80 drift/ID, in
OH_DIA = 8.5              # open hole diameter, in

MW = 12.2                 # current mud weight, ppg
LOT_EMW = 15.8            # leak-off / formation integrity at shoe, ppg EMW
SCR_PRESS = 320.0         # slow circulating pressure, psi @ kill rate
SCR_SPM = 30.0            # kill rate, spm
PUMP_LINER = 6.5          # in
PUMP_STROKE = 12.0        # in
PUMP_EFF = 0.95
SURFACE_LINE_VOL = 11.5   # bbl, standpipe + rotary hose + kelly

# Shut-in kick data (the scenario the planner should solve)
SIDPP = 480.0             # psi
PIT_GAIN = 22.0           # bbl
INFLUX_GRADIENT = 0.12    # psi/ft, gas influx
# SICP is derived from the influx height so the scenario is self-consistent.

VS_AZIMUTH = 144.0        # vertical section reference azimuth, deg


def bbl_per_ft(id_in):
    """Internal capacity, bbl/ft."""
    return id_in ** 2 / 1029.4


def ann_bbl_per_ft(hole_id, pipe_od):
    """Annular capacity, bbl/ft."""
    return (hole_id ** 2 - pipe_od ** 2) / 1029.4


def steel_disp_bbl_per_ft(od_in, id_in):
    """Closed-end steel displacement, bbl/ft."""
    return (od_in ** 2 - id_in ** 2) / 1029.4


# ----------------------------------------------------------------------------
# DRILL STRING  (defined bottom-up, as a rig tally is written)
# ----------------------------------------------------------------------------
# (description, type, n_joints, OD in, ID in, nominal ppf, connection, nominal len ft)
bha_spec = [
    ("8-1/2in PDC bit, 5x13 nozzles",        "Bit",          1,  8.500, 3.000,   None, "4-1/2 REG",  1.02),
    ("6-3/4in PD motor, 1.5 deg bent hsg",   "Mud Motor",    1,  6.750, 3.000,  None, "NC50",      28.47),
    ("8-1/4in near-bit stabilizer",          "Stabilizer",   1,  8.250, 2.813,  None, "NC50",       5.52),
    ("6-3/4in MWD / gamma collar",           "MWD",          1,  6.750, 3.250,  None, "NC50",      31.18),
    ("6-3/4in non-mag drill collar",         "NMDC",         1,  6.750, 2.813,  None, "NC50",      30.14),
    ("8-1/4in string stabilizer",            "Stabilizer",   1,  8.250, 2.813,  None, "NC50",       5.38),
    ("6-3/4in drill collar",                 "Drill Collar", 12, 6.750, 2.813,  99.0, "NC50",      30.20),
    ("6-1/2in hydraulic drilling jar",       "Jar",          1,  6.500, 2.750,  None, "NC50",      31.05),
    ("5in HWDP, 49.3 ppf",                   "HWDP",         21, 5.000, 3.000,  49.3, "NC50",      30.50),
]

DP_OD, DP_ID, DP_PPF, DP_CONN = 5.000, 4.276, 19.50, "NC50 (5-1/2 FH)"

rows = []
item = 0
cum = 0.0          # length from bit


def add_row(desc, ctype, jt_no, stand, od, idd, ppf, conn, length):
    global item, cum
    item += 1
    bottom = TD_MD - cum
    cum += length
    top = TD_MD - cum
    rows.append(dict(
        Item_No=item,
        Joint_No=jt_no,
        Stand_No=stand,
        Description=desc,
        Component_Type=ctype,
        OD_in=od,
        ID_in=idd,
        Nominal_Weight_ppf=ppf,
        Connection=conn,
        Length_ft=round(length, 2),
        Cum_Length_ft=round(cum, 2),
        Top_Depth_ft=round(top, 2),
        Bottom_Depth_ft=round(bottom, 2),
    ))


# --- BHA -------------------------------------------------------------------
jt_counter = 0
for desc, ctype, n, od, idd, ppf, conn, nom in bha_spec:
    for k in range(n):
        if ctype in ("Drill Collar", "HWDP"):
            jt_counter += 1
            jt_no = jt_counter
            # measured lengths vary joint to joint
            length = round(nom + random.uniform(-0.22, 0.22), 2)
        else:
            jt_no = None
            length = nom
        label = desc if n == 1 else f"{desc} #{k+1}"
        add_row(label, ctype, jt_no, None, od, idd, ppf, conn, length)

bha_and_hwdp_len = cum

# --- Drill pipe, joint by joint, run in stands of 3 ------------------------
dp_target = TD_MD - cum
n_dp = int(dp_target // 31.2)
dp_lengths = [round(random.gauss(31.20, 0.26), 2) for _ in range(n_dp)]
# top joint is a pup to make the tally close exactly on 12,500.00 ft
remainder = round(dp_target - sum(dp_lengths), 2)
while remainder < 5.0:            # keep the pup a sane length
    n_dp -= 1
    dp_lengths.pop()
    remainder = round(dp_target - sum(dp_lengths), 2)
while remainder > 31.5:
    extra = round(random.gauss(31.20, 0.26), 2)
    dp_lengths.append(extra)
    n_dp += 1
    remainder = round(dp_target - sum(dp_lengths), 2)

for i, L in enumerate(dp_lengths):
    jt_counter += 1
    stand = i // 3 + 1
    add_row("5in 19.50 ppf S-135 drill pipe", "Drill Pipe", jt_counter, stand,
            DP_OD, DP_ID, DP_PPF, DP_CONN, L)

jt_counter += 1
add_row(f"5in drill pipe pup joint ({remainder:.2f} ft)", "Pup Joint", jt_counter,
        None, DP_OD, DP_ID, DP_PPF, DP_CONN, remainder)

tally = pd.DataFrame(rows)
assert abs(tally.Length_ft.sum() - TD_MD) < 0.005, tally.Length_ft.sum()

# capacity / displacement per row
tally["Capacity_bbl_per_ft"] = (tally.ID_in ** 2 / 1029.4).round(5)
tally["Capacity_bbl"] = (tally.Capacity_bbl_per_ft * tally.Length_ft).round(3)
tally["Displacement_bbl_per_ft"] = ((tally.OD_in ** 2 - tally.ID_in ** 2) / 1029.4).round(5)
tally["Displacement_bbl"] = (tally.Displacement_bbl_per_ft * tally.Length_ft).round(3)

# ----------------------------------------------------------------------------
# DIRECTIONAL SURVEY
# ----------------------------------------------------------------------------
stations = []

# vertical section
md = 0.0
while md < KOP - 1e-9:
    stations.append((md, 0.0, 0.0))
    md += 200.0
stations.append((KOP, 0.0, 142.0))

# build section, surveyed every joint (~30 ft)
md = KOP + 30.0
while md < EOB - 1e-9:
    inc = (md - KOP) * BUILD_RATE / 100.0
    frac = (md - KOP) / (EOB - KOP)
    azi = 142.0 + 1.4 * frac + random.uniform(-0.12, 0.12)
    stations.append((round(md, 2), round(inc, 2), round(azi, 2)))
    md += 30.0
stations.append((EOB, TARGET_INC, 143.40))

# tangent section, surveyed every stand (~93 ft)
LAST_SURVEY = 12460.0
md = EOB + 93.0
while md <= LAST_SURVEY - 1e-9:
    frac = (md - EOB) / (LAST_SURVEY - EOB)
    inc = 35.0 - 0.40 * frac + random.uniform(-0.30, 0.30)
    azi = 143.40 + 2.50 * frac + random.uniform(-0.25, 0.25)
    stations.append((round(md, 2), round(inc, 2), round(azi, 2)))
    md += 93.0
stations.append((LAST_SURVEY, 34.62, 145.93))

# A survey station is taken at the casing shoe, as it would be on a real well.
_f = (INT_SHOE_MD - EOB) / (LAST_SURVEY - EOB)
stations.append((INT_SHOE_MD,
                 round(35.0 - 0.40 * _f, 2),
                 round(143.40 + 2.50 * _f, 2)))

stations = sorted(set(stations), key=lambda s: s[0])
# drop any station that duplicates the shoe depth
stations = [s for i, s in enumerate(stations)
            if i == 0 or abs(s[0] - stations[i - 1][0]) > 1e-6]


def minimum_curvature(sts):
    out = []
    tvd = n = e = 0.0
    prev = None
    for md, inc, azi in sts:
        if prev is None:
            out.append(dict(MD_ft=md, Inclination_deg=inc, Azimuth_deg=azi,
                            TVD_ft=0.0, Northing_ft=0.0, Easting_ft=0.0,
                            DLS_deg_per_100ft=0.0, Course_Length_ft=0.0))
            prev = (md, inc, azi)
            continue
        md1, i1, a1 = prev
        dmd = md - md1
        I1, I2 = math.radians(i1), math.radians(inc)
        A1, A2 = math.radians(a1), math.radians(azi)
        cos_dl = (math.cos(I2 - I1)
                  - math.sin(I1) * math.sin(I2) * (1 - math.cos(A2 - A1)))
        cos_dl = max(-1.0, min(1.0, cos_dl))
        dl = math.acos(cos_dl)
        rf = 1.0 if abs(dl) < 1e-12 else (2.0 / dl) * math.tan(dl / 2.0)
        tvd += dmd / 2.0 * (math.cos(I1) + math.cos(I2)) * rf
        n += dmd / 2.0 * (math.sin(I1) * math.cos(A1) + math.sin(I2) * math.cos(A2)) * rf
        e += dmd / 2.0 * (math.sin(I1) * math.sin(A1) + math.sin(I2) * math.sin(A2)) * rf
        out.append(dict(MD_ft=md, Inclination_deg=inc, Azimuth_deg=azi,
                        TVD_ft=round(tvd, 2), Northing_ft=round(n, 2),
                        Easting_ft=round(e, 2),
                        DLS_deg_per_100ft=round(math.degrees(dl) * 100.0 / dmd, 2),
                        Course_Length_ft=round(dmd, 2)))
        prev = (md, inc, azi)
    return out


srv = pd.DataFrame(minimum_curvature(stations))
srv["Closure_Distance_ft"] = (srv.Northing_ft ** 2 + srv.Easting_ft ** 2) ** 0.5
srv["Closure_Azimuth_deg"] = [
    round(math.degrees(math.atan2(e_, n_)) % 360.0, 2) if (abs(n_) + abs(e_)) > 1e-9 else 0.0
    for n_, e_ in zip(srv.Northing_ft, srv.Easting_ft)
]
srv["Vertical_Section_ft"] = [
    round(c * math.cos(math.radians(ca - VS_AZIMUTH)), 2)
    for c, ca in zip(srv.Closure_Distance_ft, srv.Closure_Azimuth_deg)
]
srv["Closure_Distance_ft"] = srv.Closure_Distance_ft.round(2)
srv = srv[["MD_ft", "Inclination_deg", "Azimuth_deg", "TVD_ft", "Northing_ft",
           "Easting_ft", "DLS_deg_per_100ft", "Course_Length_ft",
           "Vertical_Section_ft", "Closure_Distance_ft", "Closure_Azimuth_deg"]]


def tvd_at(md_target):
    """TVD at an arbitrary MD, by minimum curvature from the bracketing stations."""
    s = stations
    if md_target <= s[0][0]:
        return 0.0
    for k in range(1, len(s)):
        if s[k][0] >= md_target:
            md1, i1, a1 = s[k - 1]
            md2, i2, a2 = s[k]
            f = (md_target - md1) / (md2 - md1)
            inc = i1 + f * (i2 - i1)
            azi = a1 + f * (a2 - a1)
            sub = minimum_curvature(s[:k] + [(md_target, inc, azi)])
            return round(sub[-1]["TVD_ft"], 2)
    # beyond last station: extend on last inclination
    md1, i1, a1 = s[-1]
    base = srv.TVD_ft.iloc[-1]
    return round(base + (md_target - md1) * math.cos(math.radians(i1)), 2)


TVD_SHOE = tvd_at(INT_SHOE_MD)
TVD_TD = tvd_at(TD_MD)
TVD_LAST_SURVEY = float(srv.TVD_ft.iloc[-1])

# ----------------------------------------------------------------------------
# VOLUMES  (walk the string from the bit up, splitting at the casing shoe)
# ----------------------------------------------------------------------------
def hole_id_at(depth):
    return OH_DIA if depth > INT_SHOE_MD else CSG_ID


ann_oh = 0.0        # annulus volume, open hole, bbl
ann_csg = 0.0       # annulus volume, inside casing, bbl
string_int = 0.0    # string internal volume, bbl
for r in rows:
    top, bot, od, idd = r["Top_Depth_ft"], r["Bottom_Depth_ft"], r["OD_in"], r["ID_in"]
    string_int += bbl_per_ft(idd) * (bot - top)
    lo, hi = top, bot
    if hi > INT_SHOE_MD:
        seg = min(hi, TD_MD) - max(lo, INT_SHOE_MD)
        if seg > 0:
            ann_oh += ann_bbl_per_ft(OH_DIA, od) * seg
    if lo < INT_SHOE_MD:
        seg = min(hi, INT_SHOE_MD) - lo
        if seg > 0:
            ann_csg += ann_bbl_per_ft(CSG_ID, od) * seg

PUMP_OUTPUT = 0.000243 * PUMP_LINER ** 2 * PUMP_STROKE * PUMP_EFF   # bbl/stk

strokes_surf_to_bit = string_int / PUMP_OUTPUT
strokes_bit_to_shoe = ann_oh / PUMP_OUTPUT
strokes_bit_to_surf = (ann_oh + ann_csg) / PUMP_OUTPUT
strokes_total_circ = strokes_surf_to_bit + strokes_bit_to_surf

# ----------------------------------------------------------------------------
# INFLUX GEOMETRY -> SICP  (so the shut-in data is internally consistent)
# ----------------------------------------------------------------------------
# Fill the annulus from the bit upward with PIT_GAIN barrels.
remaining = PIT_GAIN
influx_top_md = TD_MD
for r in rows:                     # rows are ordered bit -> surface
    top, bot, od = r["Top_Depth_ft"], r["Bottom_Depth_ft"], r["OD_in"]
    seg_cap = ann_bbl_per_ft(hole_id_at((top + bot) / 2.0), od)
    seg_vol = seg_cap * (bot - top)
    if seg_vol >= remaining:
        influx_top_md = bot - remaining / seg_cap
        remaining = 0.0
        break
    remaining -= seg_vol
    influx_top_md = top
assert remaining == 0.0, "pit gain exceeds annulus volume"

INFLUX_HEIGHT_MD = TD_MD - influx_top_md
INFLUX_TOP_TVD = tvd_at(influx_top_md)
INFLUX_HEIGHT_TVD = TVD_TD - INFLUX_TOP_TVD

# SICP = SIDPP + (mud hydrostatic the influx displaced) - (influx hydrostatic)
SICP = SIDPP + (0.052 * MW - INFLUX_GRADIENT) * INFLUX_HEIGHT_TVD

# ----------------------------------------------------------------------------
# KILL SHEET FIGURES
# ----------------------------------------------------------------------------
KMW = MW + SIDPP / (0.052 * TVD_TD)
ICP = SCR_PRESS + SIDPP
FCP = SCR_PRESS * KMW / MW
MAASP_now = (LOT_EMW - MW) * 0.052 * TVD_SHOE
MAASP_kill = (LOT_EMW - KMW) * 0.052 * TVD_SHOE
BHP = SIDPP + 0.052 * MW * TVD_TD
hydrostatic = 0.052 * MW * TVD_TD

summary = {
    "Well_Name": "Test-1H (synthetic)",
    "Rig": "Land rig, triples",
    "Units": "Field (ft, in, ppg, psi, bbl)",
    "Bit_Depth_MD_ft": TD_MD,
    "Bit_Depth_TVD_ft": TVD_TD,
    "Last_Survey_MD_ft": LAST_SURVEY,
    "Last_Survey_TVD_ft": TVD_LAST_SURVEY,
    "KOP_ft_MD": KOP,
    "Build_Rate_deg_per_100ft": BUILD_RATE,
    "EOB_ft_MD": EOB,
    "Hold_Inclination_deg": TARGET_INC,
    "Surface_Casing": '13-3/8in 68.0 ppf K-55',
    "Surface_Shoe_MD_ft": SURF_SHOE_MD,
    "Intermediate_Casing": '9-5/8in 47.0 ppf N-80',
    "Intermediate_Shoe_MD_ft": INT_SHOE_MD,
    "Intermediate_Shoe_TVD_ft": TVD_SHOE,
    "Casing_ID_in": CSG_ID,
    "Open_Hole_Size_in": OH_DIA,
    "Mud_Weight_ppg": MW,
    "LOT_EMW_ppg": LOT_EMW,
    "Pump_Type": f"Triplex, {PUMP_LINER}in liner x {PUMP_STROKE}in stroke, {PUMP_EFF:.0%} eff",
    "Pump_Output_bbl_per_stk": round(PUMP_OUTPUT, 5),
    "Kill_Rate_spm": SCR_SPM,
    "Slow_Circulating_Pressure_psi": SCR_PRESS,
    "Surface_Line_Volume_bbl": SURFACE_LINE_VOL,
    "String_Internal_Volume_bbl": round(string_int, 2),
    "Annulus_OpenHole_bbl": round(ann_oh, 2),
    "Annulus_InCasing_bbl": round(ann_csg, 2),
    "Total_Annulus_bbl": round(ann_oh + ann_csg, 2),
    "Total_Hole_Volume_bbl": round(string_int + ann_oh + ann_csg, 2),
    "Strokes_Surface_to_Bit": round(strokes_surf_to_bit, 0),
    "Strokes_Bit_to_Shoe": round(strokes_bit_to_shoe, 0),
    "Strokes_Bit_to_Surface": round(strokes_bit_to_surf, 0),
    "Strokes_Full_Circulation": round(strokes_total_circ, 0),
    "SIDPP_psi": SIDPP,
    "SICP_psi": round(SICP, 0),
    "Pit_Gain_bbl": PIT_GAIN,
    "Influx_Gradient_psi_per_ft": INFLUX_GRADIENT,
    "Influx_Height_MD_ft": round(INFLUX_HEIGHT_MD, 1),
    "Influx_Height_TVD_ft": round(INFLUX_HEIGHT_TVD, 1),
    "Influx_Top_MD_ft": round(influx_top_md, 1),
    "Kill_Mud_Weight_ppg": round(KMW, 2),
    "ICP_psi": round(ICP, 0),
    "FCP_psi": round(FCP, 0),
    "MAASP_current_MW_psi": round(MAASP_now, 0),
    "MAASP_kill_MW_psi": round(MAASP_kill, 0),
    "Hydrostatic_at_TD_psi": round(hydrostatic, 0),
    "Bottomhole_Pressure_psi": round(BHP, 0),
}

tally.to_csv("/home/claude/wc/pipe_tally.csv", index=False)
srv.to_csv("/home/claude/wc/directional_survey.csv", index=False)
with open("/home/claude/wc/summary.json", "w") as f:
    json.dump(summary, f, indent=2)

print(f"tally rows      : {len(tally)}")
print(f"tally total len : {tally.Length_ft.sum():.2f} ft")
print(f"DP joints       : {int((tally.Component_Type=='Drill Pipe').sum())}")
print(f"pup joint       : {remainder:.2f} ft")
print(f"survey stations : {len(srv)}")
print(f"TVD @ TD        : {TVD_TD:.2f} ft")
print(f"TVD @ shoe      : {TVD_SHOE:.2f} ft")
print(f"max DLS         : {srv.DLS_deg_per_100ft.max():.2f} deg/100ft")
print(f"VS @ last stn   : {srv.Vertical_Section_ft.iloc[-1]:.2f} ft")
print(f"closure         : {srv.Closure_Distance_ft.iloc[-1]:.2f} ft @ {srv.Closure_Azimuth_deg.iloc[-1]:.2f} deg")
print(json.dumps({k: summary[k] for k in list(summary)[-14:]}, indent=2))
