"""Unit conversion tests."""

import pytest

from wellcontrol import units


class TestDensity:
    def test_ppg_to_gradient(self):
        assert units.ppg_to_gradient(9.6) == pytest.approx(0.4992)

    def test_exact_constant(self):
        assert units.ppg_to_gradient(1.0, exact=True) == pytest.approx(
            0.0519481, abs=1e-7
        )

    def test_gradient_round_trip(self):
        assert units.gradient_to_ppg(units.ppg_to_gradient(12.5)) == pytest.approx(12.5)

    def test_specific_gravity(self):
        """Fresh water is 8.33 ppg and SG 1.0 by definition here."""
        assert units.ppg_to_sg(8.33) == pytest.approx(1.0)
        assert units.sg_to_ppg(1.5) == pytest.approx(12.495)

    def test_pounds_per_cubic_foot(self):
        assert units.ppg_to_pcf(10.0) == pytest.approx(74.805)
        assert units.pcf_to_ppg(74.805) == pytest.approx(10.0)


class TestPressure:
    def test_bar(self):
        assert units.psi_to_bar(1000.0) == pytest.approx(68.9476, abs=0.001)
        assert units.bar_to_psi(68.9476) == pytest.approx(1000.0, abs=0.01)

    def test_kpa(self):
        assert units.psi_to_kpa(1000.0) == pytest.approx(6894.757, abs=0.01)

    def test_absolute_pressure(self):
        assert units.psi_to_psia(0.0) == pytest.approx(14.7)
        assert units.psia_to_psig(14.7) == pytest.approx(0.0)


class TestLengthAndVolume:
    def test_feet_metres(self):
        assert units.ft_to_m(10000.0) == pytest.approx(3048.0)
        assert units.m_to_ft(3048.0) == pytest.approx(10000.0)

    def test_inches_millimetres(self):
        assert units.in_to_mm(8.5) == pytest.approx(215.9)

    def test_barrels(self):
        assert units.bbl_to_m3(100.0) == pytest.approx(15.8987, abs=0.001)
        assert units.bbl_to_gal(1.0) == pytest.approx(42.0)
        assert units.gal_to_bbl(42.0) == pytest.approx(1.0)

    def test_flow(self):
        assert units.gpm_to_lpm(100.0) == pytest.approx(378.541, abs=0.01)
        assert units.gpm_to_bpm(420.0) == pytest.approx(10.0)
        assert units.bpm_to_gpm(10.0) == pytest.approx(420.0)


class TestTemperature:
    def test_fahrenheit_celsius(self):
        assert units.f_to_c(212.0) == pytest.approx(100.0)
        assert units.c_to_f(100.0) == pytest.approx(212.0)
        assert units.f_to_c(32.0) == pytest.approx(0.0)

    def test_rankine(self):
        """Absolute temperature, needed for every gas law calculation."""
        assert units.f_to_rankine(70.0) == pytest.approx(529.67)
        assert units.rankine_to_f(529.67) == pytest.approx(70.0)
        assert units.f_to_rankine(units.ABSOLUTE_ZERO_F) == pytest.approx(0.0)


class TestConstants:
    def test_capacity_constant_is_consistent(self):
        """1029.4 comes from (pi/4 x 12) / 9702."""
        import math

        derived = units.CUIN_PER_BBL / (math.pi / 4.0 * 12.0)
        assert derived == pytest.approx(units.CAPACITY_CONSTANT, abs=0.5)

    def test_rounded_and_exact_gradient_constants_agree_closely(self):
        difference = abs(units.PSI_PER_PPG_FT - units.PSI_PER_PPG_FT_EXACT)
        assert difference / units.PSI_PER_PPG_FT_EXACT < 0.002
