"""
External validation of the drill pipe pressure schedule.

Second source: drillingformulas.com worked example, "Drill Pipe Pressure
Schedule Calculation for Wait and Weight Well Control Method". Its inputs and
its published strokes-vs-pressure table are reproduced below verbatim, then
recomputed two ways:

  1. the conventional straight line, using the article's own rounded KWM/FCP
  2. the rigorous tapered-string hydrostatic model used for Test-1H, applied to
     this uniform vertical well

In a uniform vertical well the rigorous model must collapse exactly onto the
straight line. That is the point of the exercise: it tests the general model
against a published answer in the one case where the answer is known.
"""

# ---- inputs exactly as published -----------------------------------------
OMW = 9.5          # ppg
PUMP = 0.1         # bbl/stk
DEPTH = 9000.0     # ft MD, vertical so TVD = MD
CAP = 0.0178       # bbl/ft, uniform string
SURF_LINE = 15.0   # bbl
SIDPP = 500.0      # psi
ICP = 1600.0       # psi at 30 spm
SCR = ICP - SIDPP  # 1100 psi, as the article defines it

# ---- published answers ---------------------------------------------------
PUB_KWM = 10.6
PUB_FCP = 1227.0
PUB_STROKES_TO_BIT = 1602
PUB_TABLE = [(150, 1600), (350, 1554), (550, 1506), (750, 1459), (950, 1412),
             (1150, 1365), (1350, 1318), (1550, 1271), (1750, 1227)]

# ---- recomputed ----------------------------------------------------------
kwm = OMW + SIDPP / (0.052 * DEPTH)
fcp = SCR * kwm / OMW
v_str = CAP * DEPTH
s_bit = v_str / PUMP
s_offset = SURF_LINE / PUMP
BHP = SIDPP + 0.052 * OMW * DEPTH

print("=== inputs (published) ===")
print(f"  depth {DEPTH:.0f} ft vertical, OMW {OMW} ppg, cap {CAP} bbl/ft, "
      f"pump {PUMP} bbl/stk")
print(f"  SIDPP {SIDPP:.0f} psi, ICP {ICP:.0f} psi, SCR {SCR:.0f} psi, "
      f"surface lines {SURF_LINE:.0f} bbl")

print("\n=== derived quantities: published vs recomputed ===")
print(f"  kill mud weight   published {PUB_KWM:8.2f}   recomputed {kwm:8.4f} ppg"
      f"   (article rounds to 1 dp)")
print(f"  FCP               published {PUB_FCP:8.0f}   recomputed {fcp:8.2f} psi"
      f"   (follows from the rounded KWM)")
print(f"  strokes to bit    published {PUB_STROKES_TO_BIT:8d}   recomputed "
      f"{s_bit:8.0f}")
print(f"  strokes for surface lines                      {s_offset:8.0f}")


def dpp_line(strokes, fcp_used):
    """Conventional straight line, offset by the surface line volume."""
    s = min(max(strokes - s_offset, 0.0), s_bit)
    return ICP - (ICP - fcp_used) * s / s_bit


def dpp_rigorous(strokes, kwm_used, fcp_used):
    """The Test-1H model: BHP + friction - actual string hydrostatic."""
    v = min(max((strokes - s_offset) * PUMP, 0.0), v_str)
    d = v / CAP                                  # depth of the kill mud front
    frac = v / v_str
    friction = SCR + (fcp_used - SCR) * frac
    hyd = 0.052 * kwm_used * d + 0.052 * OMW * (DEPTH - d)
    return BHP + friction - hyd


print("\n=== published table vs both models (article's rounded KWM/FCP) ===")
print(f"{'strokes':>8s} {'published':>10s} {'straight':>10s} {'rigorous':>10s} "
      f"{'pub-str':>8s} {'str-rig':>8s}")
worst_pub = worst_model = 0.0
for s, pub in PUB_TABLE:
    a = dpp_line(s, PUB_FCP)
    b = dpp_rigorous(s, PUB_KWM, PUB_FCP)
    worst_pub = max(worst_pub, abs(pub - a))
    worst_model = max(worst_model, abs(a - b))
    print(f"{s:8d} {pub:10.0f} {a:10.1f} {b:10.1f} {pub-a:8.1f} {a-b:8.2f}")

print(f"\n  max |published - straight line| : {worst_pub:.1f} psi")
print(f"  max |straight line - rigorous|  : {worst_model:.2f} psi   "
      f"<- must be ~0 in a uniform vertical well")

print("\n  Note on the residual against the published column: the article steps its"
      "\n  table by a rounded 47 psi per 200 strokes (the exact value is "
      f"{(ICP-PUB_FCP)/s_bit*200:.2f}),"
      "\n  so its error accumulates down the table. That is rounding in the source,"
      "\n  not a disagreement in method.")

# same check with unrounded constants
w = max(abs(dpp_line(s, fcp) - dpp_rigorous(s, kwm, fcp)) for s, _ in PUB_TABLE)
print(f"\n  repeated with unrounded KWM {kwm:.4f} / FCP {fcp:.2f}: "
      f"max |straight - rigorous| = {w:.2e} psi")
