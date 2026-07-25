"""Append the circulating answer key and the external validation to the workbook."""
import json
import pandas as pd
from openpyxl import load_workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

ARIAL = "Arial"
BLUE = Font(name=ARIAL, size=10, color="0000FF")
BLACK = Font(name=ARIAL, size=10)
BOLD = Font(name=ARIAL, size=10, bold=True)
TITLE = Font(name=ARIAL, size=14, bold=True)
SECTION = Font(name=ARIAL, size=11, bold=True, color="FFFFFF")
NOTE = Font(name=ARIAL, size=9, italic=True, color="595959")
HDR_FILL = PatternFill("solid", fgColor="1F3864")
SEC_FILL = PatternFill("solid", fgColor="2E5C8A")
WARN_FILL = PatternFill("solid", fgColor="FFF2CC")
THIN = Side(style="thin", color="BFBFBF")
BOX = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)

prof = pd.read_csv("/home/claude/wc/circulating_profile.csv")
C = json.load(open("/home/claude/wc/circulating_summary.json"))

wb = load_workbook("/home/claude/wc/well_control_test_data.xlsx")

# ===================================================== Circulating_Key
ws = wb.create_sheet("Circulating_Key")
ws["A1"] = "CIRCULATING ANSWER KEY — one circulation, wait and weight"
ws["A1"].font = TITLE
ws["A2"] = ("Output of an independent model (circulating.py), NOT of in-cell formulas. "
            "Read Notes_Circulating before trusting any of it.")
ws["A2"].font = NOTE
for c, h in enumerate(["Figure", "Value", "Units", "Confidence / Note"], start=1):
    cell = ws.cell(row=4, column=c, value=h)
    cell.font = Font(name=ARIAL, size=10, bold=True, color="FFFFFF")
    cell.fill = HDR_FILL
    cell.border = BOX

row = 5


def section(t):
    global row
    ws.cell(row=row, column=1, value=t).font = SECTION
    for c in range(1, 5):
        ws.cell(row=row, column=c).fill = SEC_FILL
    row += 1


def put(label, val, units, note, fmt=None, warn=False):
    global row
    ws.cell(row=row, column=1, value=label).font = BLACK
    c = ws.cell(row=row, column=2, value=val)
    c.font = BLUE
    if fmt:
        c.number_format = fmt
    ws.cell(row=row, column=3, value=units).font = BLACK
    ws.cell(row=row, column=4, value=note).font = NOTE
    for cc in range(1, 5):
        ws.cell(row=row, column=cc).border = BOX
        if warn:
            ws.cell(row=row, column=cc).fill = WARN_FILL
    row += 1


section("EXTERNALLY VALIDATED — the schedule method matches a published worked example")
put("Strokes to bit", C["strokes_to_bit"], "stk",
    "Volume/pump output. Also on Well_Data.", "0")
put("ICP", C["ICP_psi"], "psi", "Verified: matches the model endpoint exactly.", "0")
put("FCP", C["FCP_psi"], "psi", "Verified: matches the model endpoint exactly.", "0")
put("Max deviation, rigorous schedule vs straight line",
    C["max_dpp_schedule_deviation_psi"], "psi",
    "Genuine effect of the tapered string and the 35 deg hold — not rounding. "
    "Collapses to zero in a uniform vertical well, which is how it was checked "
    "against the published example.", "0.0")

section("MODEL OUTPUT — self-consistent and endpoint-checked, but not externally sourced")
put("Strokes, gas top reaches surface", C["strokes_gas_top_to_surface"], "stk",
    "Isothermal single-bubble assumption.", "0")
put("Gas volume on arrival at surface", C["gas_volume_at_surface_bbl"], "bbl",
    f"Expansion ratio x{C['gas_expansion_ratio']:.2f} from {22} bbl.", "0.0")
put("Peak choke pressure", C["peak_choke_psi"], "psi",
    "Occurs as the gas top reaches surface, which is the textbook expectation.",
    "0")
put("Strokes at peak choke pressure", C["peak_choke_strokes"], "stk", "", "0")
put("Peak casing shoe pressure", C["peak_shoe_psi"], "psi",
    "Occurs at shut-in, before circulating. Falls thereafter, because kill mud "
    "entering the annulus raises hydrostatic below the shoe.", "0")
put("Shoe margin at peak", C["shoe_margin_at_peak_psi"], "psi",
    f"Below formation integrity of {C['formation_pressure_at_shoe_psi']:.0f} psi. "
    "The shoe is not at risk in this scenario.", "0")
put("Strokes, gas fully out", C["strokes_gas_fully_out"], "stk", "", "0")
put("Strokes, kill complete", C["strokes_kill_complete"], "stk",
    "Kill mud back at surface, choke pressure zero.", "0")

section("A DELIBERATE TRAP WORTH CHECKING")
put("Peak choke pressure vs MAASP",
    f"{C['peak_choke_psi']:.0f} psi vs {C['MAASP_psi']:.0f} psi MAASP",
    "", "Peak choke pressure EXCEEDS MAASP, yet the shoe stays "
    f"{C['shoe_margin_at_peak_psi']:.0f} psi inside its limit. MAASP is computed "
    "with a full mud column; when gas occupies the annulus the surface pressure "
    "can pass MAASP without the shoe being over-pressured. An app that alarms on "
    "choke > MAASP here is being conservative, not correct — but it should say so "
    "rather than declare the kill infeasible.", warn=True)

ws.column_dimensions["A"].width = 44
ws.column_dimensions["B"].width = 26
ws.column_dimensions["C"].width = 8
ws.column_dimensions["D"].width = 78
for r in range(5, row):
    ws.cell(row=r, column=4).alignment = Alignment(wrap_text=True, vertical="top")
ws.freeze_panes = "A5"

# ===================================================== Circulating_Profile
wp = wb.create_sheet("Circulating_Profile")
for c, col in enumerate(prof.columns, start=1):
    cell = wp.cell(row=1, column=c, value=col)
    cell.font = Font(name=ARIAL, size=10, bold=True, color="FFFFFF")
    cell.fill = HDR_FILL
    cell.alignment = Alignment(horizontal="center", wrap_text=True)
    cell.border = BOX
fmts = {"Pumped_bbl": "0.00", "DPP_Conventional_psi": "0.0",
        "DPP_Rigorous_psi": "0.0", "Choke_Pressure_psi": "0.0",
        "Shoe_Pressure_psi": "0.0", "Gas_Volume_bbl": "0.00",
        "Gas_Pressure_psi": "0.0", "Gas_Bottom_MD_ft": "0.0",
        "Gas_Top_MD_ft": "0.0", "Gas_Height_MD_ft": "0.0",
        "Kill_Mud_String_MD_ft": "0.0", "Kill_Mud_Annulus_MD_ft": "0.0",
        "Strokes": "0"}
for r in range(len(prof)):
    for c, col in enumerate(prof.columns, start=1):
        v = prof.iloc[r][col]
        if pd.isna(v):
            v = None
        cell = wp.cell(row=r + 2, column=c, value=v)
        cell.font = BLUE
        if col in fmts:
            cell.number_format = fmts[col]
for c, col in enumerate(prof.columns, start=1):
    wp.column_dimensions[get_column_letter(c)].width = 15
wp.freeze_panes = "A2"
wp.cell(row=len(prof) + 3, column=1,
        value="Model output, not in-cell formulas. Reproduce with circulating.py. "
              "Every row satisfies constant bottomhole pressure to 0.0000 psi and "
              "closes the annular volume book exactly.").font = NOTE

# ===================================================== External_Validation
wv = wb.create_sheet("External_Validation")
wv["A1"] = "EXTERNAL VALIDATION — drill pipe pressure schedule"
wv["A1"].font = TITLE
wv["A2"] = ("Second source: drillingformulas.com, 'Drill Pipe Pressure Schedule "
            "Calculation for Wait and Weight Well Control Method'. Its inputs and "
            "published table are reproduced verbatim in blue.")
wv["A2"].font = NOTE

inputs = [
    ("Original mud weight", 9.5, "ppg"), ("Pump output", 0.1, "bbl/stk"),
    ("Depth (vertical, MD = TVD)", 9000.0, "ft"),
    ("Drill string capacity", 0.0178, "bbl/ft"),
    ("Surface line volume", 15.0, "bbl"), ("SIDPP", 500.0, "psi"),
    ("ICP", 1600.0, "psi"), ("Published KWM", 10.6, "ppg"),
    ("Published FCP", 1227.0, "psi"),
]
r = 4
wv.cell(row=r, column=1, value="PUBLISHED INPUTS").font = BOLD
r += 1
ROW = {}
for lab, v, u in inputs:
    wv.cell(row=r, column=1, value=lab).font = BLACK
    c = wv.cell(row=r, column=2, value=v)
    c.font = BLUE
    wv.cell(row=r, column=3, value=u).font = BLACK
    ROW[lab] = r
    r += 1


def R(lab):
    return f"$B${ROW[lab]}"


derived = [
    ("SCR", f"={R('ICP')}-{R('SIDPP')}", "psi"),
    ("BHP", f"={R('SIDPP')}+0.052*{R('Original mud weight')}"
            f"*{R('Depth (vertical, MD = TVD)')}", "psi"),
    ("Recomputed KWM", f"={R('Original mud weight')}+{R('SIDPP')}"
                       f"/(0.052*{R('Depth (vertical, MD = TVD)')})", "ppg"),
    ("String volume", f"={R('Drill string capacity')}"
                      f"*{R('Depth (vertical, MD = TVD)')}", "bbl"),
    ("Strokes to bit", f"=$B${r+3}/{R('Pump output')}", "stk"),
    ("Surface line strokes", f"={R('Surface line volume')}/{R('Pump output')}", "stk"),
]
r += 1
wv.cell(row=r, column=1, value="DERIVED").font = BOLD
r += 1
for lab, f, u in derived:
    wv.cell(row=r, column=1, value=lab).font = BLACK
    c = wv.cell(row=r, column=2, value=f)
    c.font = BLACK
    c.number_format = "0.0000"
    wv.cell(row=r, column=3, value=u).font = BLACK
    ROW[lab] = r
    r += 1
# fix the self-reference for Strokes to bit
wv.cell(row=ROW["Strokes to bit"], column=2,
        value=f"={R('String volume')}/{R('Pump output')}")

tab_hdr = ["Strokes", "Published DPP (psi)", "Straight line (psi)",
           "Rigorous model (psi)", "Published - straight", "Straight - rigorous"]
r += 1
TAB0 = r
for c, h in enumerate(tab_hdr, start=1):
    cell = wv.cell(row=r, column=c, value=h)
    cell.font = Font(name=ARIAL, size=10, bold=True, color="FFFFFF")
    cell.fill = HDR_FILL
    cell.alignment = Alignment(wrap_text=True, horizontal="center")
    cell.border = BOX
r += 1
PUB = [(150, 1600), (350, 1554), (550, 1506), (750, 1459), (950, 1412),
       (1150, 1365), (1350, 1318), (1550, 1271), (1750, 1227)]
for s, pub in PUB:
    wv.cell(row=r, column=1, value=s).font = BLUE
    wv.cell(row=r, column=2, value=pub).font = BLUE
    frac = (f"MIN(MAX(A{r}-{R('Surface line strokes')},0),{R('Strokes to bit')})"
            f"/{R('Strokes to bit')}")
    wv.cell(row=r, column=3,
            value=f"={R('ICP')}-({R('ICP')}-{R('Published FCP')})*{frac}").font = BLACK
    depth = f"{frac}*{R('Depth (vertical, MD = TVD)')}"
    wv.cell(row=r, column=4, value=(
        f"={R('BHP')}+({R('SCR')}+({R('Published FCP')}-{R('SCR')})*{frac})"
        f"-(0.052*{R('Published KWM')}*({depth})"
        f"+0.052*{R('Original mud weight')}"
        f"*({R('Depth (vertical, MD = TVD)')}-({depth})))")).font = BLACK
    wv.cell(row=r, column=5, value=f"=B{r}-C{r}").font = BLACK
    wv.cell(row=r, column=6, value=f"=C{r}-D{r}").font = BLACK
    for c in range(3, 7):
        wv.cell(row=r, column=c).number_format = "0.00"
    r += 1
r += 1
wv.cell(row=r, column=1, value=(
    "Reading this sheet: column E is the article's own rounding — it steps its table "
    "by a rounded 47 psi per 200 strokes where the exact figure is 46.57, so the error "
    "accumulates downward. Column F is the gap between the straight line and the "
    "rigorous hydrostatic model when both are fed the article's ROUNDED kill mud "
    "weight of 10.6 ppg; 0.052 x 10.6 x 9000 = 4961 psi, which overshoots the true "
    "BHP of 4946 psi, and that 15 psi inconsistency is what column F exposes. Fed the "
    "unrounded 10.5684 ppg, the two models agree to 2e-12 psi. That is the real "
    "validation result: the rigorous model reduces exactly to the textbook straight "
    "line in a uniform vertical well.")).font = NOTE
wv.cell(row=r, column=1).alignment = Alignment(wrap_text=True, vertical="top")
wv.merge_cells(start_row=r, start_column=1, end_row=r + 6, end_column=6)
wv.column_dimensions["A"].width = 30
for col in "BCDEF":
    wv.column_dimensions[col].width = 17

# ===================================================== Notes_Circulating
wn = wb.create_sheet("Notes_Circulating")
wn["A1"] = "CIRCULATING MODEL — WHAT IS AND IS NOT VERIFIED"
wn["A1"].font = TITLE
lines = [
    "",
    "THE HONEST SUMMARY",
    "The geometry and the shut-in kill sheet on Well_Data are independently verified. "
    "The circulating results on this workbook's Circulating_Key and Circulating_Profile "
    "sheets are not, in the same sense. They come from a second independent "
    "implementation and they pass every internal and endpoint check available, but no "
    "published second-source circulating trace was found to check them against. Treat "
    "them as a strong cross-check, not as ground truth.",
    "",
    "WHAT WAS CHECKED, AND HOW",
    "Drill pipe pressure schedule: validated against a published worked example "
    "(see External_Validation). The general model reduces exactly to the textbook "
    "straight line in the uniform vertical case, to 2e-12 psi.",
    "Choke pressure at zero strokes: the model returns 775.4 psi, against 775.4 psi "
    "derived by a completely separate route in the data generator (influx height x "
    "mud-minus-gas gradient). Two code paths, same answer.",
    "Schedule endpoints: the rigorous curve lands on ICP at zero strokes and on FCP at "
    "strokes-to-bit exactly, which it only does if kill mud weight, BHP and hydrostatic "
    "are mutually consistent.",
    "Bottomhole pressure: recomputed from the full fluid column at every one of the "
    "profile rows. Constant to 0.0000 psi.",
    "Boyle's law: pressure x volume for the bubble is constant to within 2 parts in "
    "10,000 across the whole pre-venting phase, that residual being reporting rounding.",
    "Annular volume book: mud below the bubble, bubble, and mud above sum to the total "
    "annular volume exactly at every row.",
    "Final state: choke pressure returns to 0.0 psi when kill mud reaches surface.",
    "",
    "WHAT IS NOT INDEPENDENTLY CHECKED",
    "The shape of the choke and shoe pressure curves between the endpoints. Both rest "
    "on the modelling assumptions below, and any planner making the same assumptions "
    "will agree with them for the same reasons — which is not evidence that either is "
    "right.",
    "The influx expansion profile. Isothermal single-bubble Boyle's law is a teaching "
    "idealisation. A real bubble slips upward through the mud, disperses, partially "
    "dissolves in oil-based mud, and sits in a wellbore that is hotter at the bottom "
    "than at the top. Every one of those effects moves the answer.",
    "The friction treatment. Taking friction as linear in the kill-mud volume fraction "
    "is the standard kill-sheet convention, not a hydraulics calculation.",
    "",
    "ASSUMPTIONS, STATED PLAINLY",
    "Wait-and-weight (engineer's) method, one circulation.",
    "Bottomhole pressure held exactly constant. A real choke operator holds it "
    "approximately.",
    "One continuous gas bubble: no slip, no migration relative to the mud, no "
    "solubility, isothermal ideal gas referenced to the pressure at the bottom of the "
    "bubble.",
    "Gas gradient scales as 1/volume from 0.12 psi/ft at shut-in, so the bubble lightens "
    "as it expands. Many kill sheets ignore gas hydrostatic entirely; this does not.",
    "Annular geometry from the tally, split at the 9-5/8in shoe. No washout, no "
    "cuttings bed, no cement excess.",
    "",
    "WHAT WOULD ACTUALLY CLOSE THE GAP",
    "A second-source kill sheet for a well with a recorded circulating trace: choke "
    "pressure against strokes for a real or fully worked kick, with the well geometry "
    "published alongside it. Searching the open literature turned up plenty of "
    "qualitative descriptions of the choke pressure curve — rises while gas expands, "
    "peaks as gas reaches surface, falls as it vents — and the model reproduces that "
    "shape, but no numerical trace to difference against. Likely sources worth trying: "
    "IWCF or IADC instructor material with filled-in exercise answers, a well control "
    "simulator's validation dataset, or an SPE or IADC/SPE paper with a documented field "
    "case. If you can get one, point the model at its geometry and the comparison is "
    "immediate.",
]
r = 3
for line in lines:
    c = wn.cell(row=r, column=1, value=line)
    c.font = BOLD if (line and line.isupper()) else Font(name=ARIAL, size=10)
    c.alignment = Alignment(wrap_text=True, vertical="top")
    r += 1
wn.column_dimensions["A"].width = 118

wb.save("/home/claude/wc/well_control_test_data.xlsx")
print("appended sheets:", wb.sheetnames)
