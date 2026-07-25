"""Unit constants and conversions for oilfield well control calculations.

Everything in this package uses **API oilfield units** unless a function name
says otherwise:

===================  ==========================
Quantity             Unit
===================  ==========================
Depth / length       ft
Diameter             in
Pressure             psi
Mud weight / density ppg (lb/gal)
Gradient             psi/ft
Volume               bbl (42 US gal)
Flow rate            gpm
Temperature          degF
===================  ==========================

The one constant that shows up everywhere in well control is the conversion
from mud weight to pressure gradient::

    gradient (psi/ft) = 0.052 x mud weight (ppg)

0.052 is a rounded value. The exact figure is 1/19.25 = 0.0519480...  Every
IWCF/IADC exam, kill sheet and rig-floor calculation uses 0.052, so that is the
default here. Pass ``exact=True`` to the gradient helpers if you need the
unrounded constant (the difference is ~0.1%, which is meaningless next to the
uncertainty in the mud weight itself).
"""

from __future__ import annotations

# --------------------------------------------------------------------------
# Core constants
# --------------------------------------------------------------------------

#: Rounded field constant: psi/ft per ppg. Used on every kill sheet.
PSI_PER_PPG_FT: float = 0.052

#: Unrounded constant: 1 / 19.25.
PSI_PER_PPG_FT_EXACT: float = 1.0 / 19.25

#: Capacity constant. capacity (bbl/ft) = ID(in)^2 / 1029.4
CAPACITY_CONSTANT: float = 1029.4

#: Cubic inches in one 42-gallon barrel.
CUIN_PER_BBL: float = 9702.0

#: US gallons per barrel.
GAL_PER_BBL: float = 42.0

#: Typical seawater density, ppg. Varies ~8.5-8.6 with salinity/temperature.
SEAWATER_PPG: float = 8.55

#: Density of fresh water, ppg.
FRESHWATER_PPG: float = 8.33

#: Standard atmospheric pressure, psia.
ATMOSPHERIC_PSI: float = 14.7

#: Absolute zero in degF, for gas-law work.
ABSOLUTE_ZERO_F: float = -459.67


# --------------------------------------------------------------------------
# Density
# --------------------------------------------------------------------------

def ppg_to_gradient(ppg: float, exact: bool = False) -> float:
    """Convert mud weight (ppg) to pressure gradient (psi/ft)."""
    k = PSI_PER_PPG_FT_EXACT if exact else PSI_PER_PPG_FT
    return ppg * k


def gradient_to_ppg(gradient: float, exact: bool = False) -> float:
    """Convert pressure gradient (psi/ft) to equivalent mud weight (ppg)."""
    k = PSI_PER_PPG_FT_EXACT if exact else PSI_PER_PPG_FT
    return gradient / k


def ppg_to_sg(ppg: float) -> float:
    """Convert ppg to specific gravity (water = 1.0)."""
    return ppg / FRESHWATER_PPG


def sg_to_ppg(sg: float) -> float:
    """Convert specific gravity to ppg."""
    return sg * FRESHWATER_PPG


def ppg_to_pcf(ppg: float) -> float:
    """Convert ppg to lb/ft^3."""
    return ppg * 7.4805


def pcf_to_ppg(pcf: float) -> float:
    """Convert lb/ft^3 to ppg."""
    return pcf / 7.4805


# --------------------------------------------------------------------------
# Pressure
# --------------------------------------------------------------------------

def psi_to_bar(psi: float) -> float:
    return psi * 0.0689476


def bar_to_psi(bar: float) -> float:
    return bar / 0.0689476


def psi_to_kpa(psi: float) -> float:
    return psi * 6.894757


def kpa_to_psi(kpa: float) -> float:
    return kpa / 6.894757


def psi_to_psia(psig: float) -> float:
    """Gauge pressure to absolute pressure. Gas laws need absolute."""
    return psig + ATMOSPHERIC_PSI


def psia_to_psig(psia: float) -> float:
    return psia - ATMOSPHERIC_PSI


# --------------------------------------------------------------------------
# Length, volume, flow
# --------------------------------------------------------------------------

def ft_to_m(ft: float) -> float:
    return ft * 0.3048


def m_to_ft(m: float) -> float:
    return m / 0.3048


def in_to_mm(inches: float) -> float:
    return inches * 25.4


def mm_to_in(mm: float) -> float:
    return mm / 25.4


def bbl_to_m3(bbl: float) -> float:
    return bbl * 0.158987


def m3_to_bbl(m3: float) -> float:
    return m3 / 0.158987


def bbl_to_gal(bbl: float) -> float:
    return bbl * GAL_PER_BBL


def gal_to_bbl(gal: float) -> float:
    return gal / GAL_PER_BBL


def gpm_to_lpm(gpm: float) -> float:
    return gpm * 3.78541


def lpm_to_gpm(lpm: float) -> float:
    return lpm / 3.78541


def gpm_to_bpm(gpm: float) -> float:
    """Gallons per minute to barrels per minute."""
    return gpm / GAL_PER_BBL


def bpm_to_gpm(bpm: float) -> float:
    return bpm * GAL_PER_BBL


# --------------------------------------------------------------------------
# Temperature
# --------------------------------------------------------------------------

def f_to_c(f: float) -> float:
    return (f - 32.0) * 5.0 / 9.0


def c_to_f(c: float) -> float:
    return c * 9.0 / 5.0 + 32.0


def f_to_rankine(f: float) -> float:
    """degF to degR. Gas laws need absolute temperature."""
    return f - ABSOLUTE_ZERO_F


def rankine_to_f(r: float) -> float:
    return r + ABSOLUTE_ZERO_F
