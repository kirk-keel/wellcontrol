"""Hydrostatic pressure, tripping and slug tests."""

import pytest

from wellcontrol.hydrostatics import (
    FluidSegment,
    balance_mud_weight,
    column_pressure,
    dry_pipe_length_from_slug,
    equivalent_circulating_density,
    equivalent_mud_weight,
    equivalent_static_density,
    fill_volume_for_pipe_pulled,
    hydrostatic_drop_from_not_filling,
    hydrostatic_pressure,
    mud_weight_for_pressure,
    overbalance,
    pressure_at_depth,
    slug_volume_for_dry_pipe,
    trip_margin_mud_weight,
)


class TestHydrostatic:
    def test_basic(self):
        """0.052 x 9.6 x 10000 = 4992 psi"""
        assert hydrostatic_pressure(9.6, 10000.0) == pytest.approx(4992.0)

    def test_exact_constant_differs_slightly(self):
        rounded = hydrostatic_pressure(9.6, 10000.0)
        exact = hydrostatic_pressure(9.6, 10000.0, exact=True)
        assert exact == pytest.approx(4987.01, abs=0.1)
        assert abs(exact - rounded) / rounded < 0.002

    def test_round_trip(self):
        assert mud_weight_for_pressure(4992.0, 10000.0) == pytest.approx(9.6)

    def test_emw_compares_pressures_at_different_depths(self):
        """4500 psi at 9000 ft and 6000 psi at 12000 ft are the same 9.615 ppg."""
        assert equivalent_mud_weight(4500.0, 9000.0) == pytest.approx(9.615, abs=0.001)
        assert equivalent_mud_weight(6000.0, 12000.0) == pytest.approx(9.615, abs=0.001)

    def test_negative_tvd_is_rejected(self):
        with pytest.raises(ValueError, match="TVD cannot be negative"):
            hydrostatic_pressure(9.6, -100.0)

    def test_zero_tvd_for_mud_weight_is_rejected(self):
        with pytest.raises(ValueError, match="TVD must be positive"):
            mud_weight_for_pressure(1000.0, 0.0)


class TestBalance:
    def test_overbalance(self):
        """4992 psi of mud against 4600 psi of formation = 392 psi over."""
        assert overbalance(9.6, 4600.0, 10000.0) == pytest.approx(392.0)

    def test_underbalance_is_negative(self):
        assert overbalance(9.0, 4992.0, 10000.0) < 0

    def test_balance_mud_weight(self):
        assert balance_mud_weight(4992.0, 10000.0) == pytest.approx(9.6)

    def test_trip_margin_as_pressure(self):
        """4992 psi balance plus 260 psi margin = 0.5 ppg more."""
        assert trip_margin_mud_weight(4992.0, 10000.0, margin_psi=260.0) == (
            pytest.approx(10.1)
        )

    def test_trip_margin_as_mud_weight(self):
        assert trip_margin_mud_weight(4992.0, 10000.0, margin_ppg=0.3) == (
            pytest.approx(9.9)
        )


class TestFluidColumns:
    def test_mud_over_gas(self):
        """9000 ft of 9.6 ppg mud over 1000 ft of 2 ppg gas:
        0.052 x 9.6 x 9000 = 4492.8
        0.052 x 2.0 x 1000 = 104.0
        Total 4596.8 psi
        """
        segments = [
            FluidSegment(9.6, 9000.0, "mud"),
            FluidSegment(2.0, 1000.0, "gas"),
        ]
        assert column_pressure(segments) == pytest.approx(4596.8)

    def test_surface_pressure_adds(self):
        segments = [FluidSegment(9.6, 10000.0)]
        assert column_pressure(segments, surface_pressure_psi=500.0) == (
            pytest.approx(5492.0)
        )

    def test_pressure_partway_down(self):
        segments = [
            FluidSegment(9.6, 9000.0),
            FluidSegment(2.0, 1000.0),
        ]
        assert pressure_at_depth(segments, 9000.0) == pytest.approx(4492.8)
        assert pressure_at_depth(segments, 9500.0) == pytest.approx(4544.8)

    def test_below_the_column_is_rejected(self):
        with pytest.raises(ValueError, match="below the bottom"):
            pressure_at_depth([FluidSegment(9.6, 1000.0)], 2000.0)

    def test_equivalent_static_density_of_a_layered_column(self):
        """A gas-cut column reads lighter than the mud it is made of."""
        segments = [
            FluidSegment(9.6, 9000.0),
            FluidSegment(2.0, 1000.0),
        ]
        esd = equivalent_static_density(segments, 10000.0)
        assert esd == pytest.approx(8.84, abs=0.01)
        assert esd < 9.6


class TestCirculating:
    def test_ecd(self):
        """9.6 ppg with 200 psi of annular friction at 10000 ft:
        9.6 + 200 / (0.052 x 10000) = 9.6 + 0.3846 = 9.985 ppg
        """
        assert equivalent_circulating_density(9.6, 200.0, 10000.0) == (
            pytest.approx(9.9846, abs=0.0001)
        )

    def test_backpressure_adds_to_ecd(self):
        with_bp = equivalent_circulating_density(9.6, 200.0, 10000.0, 150.0)
        without = equivalent_circulating_density(9.6, 200.0, 10000.0)
        assert with_bp > without
        assert with_bp - without == pytest.approx(150.0 / 520.0, abs=1e-6)


class TestTripping:
    def test_fill_volume(self):
        """0.0065242 bbl/ft x 90 ft = 0.587 bbl for three stands of 5in DP."""
        assert fill_volume_for_pipe_pulled(0.0065242, 90.0) == (
            pytest.approx(0.5872, abs=0.001)
        )

    def test_not_filling_drops_the_level_and_the_pressure(self):
        """0.587 bbl removed from a 0.0489215 bbl/ft annulus drops the level
        12.0 ft, worth 0.052 x 9.6 x 12.0 = 5.99 psi.
        """
        drop_ft, drop_psi = hydrostatic_drop_from_not_filling(
            displacement_bbl_per_ft=0.0065242,
            length_pulled_ft=90.0,
            annular_capacity_bbl_per_ft=0.0489215,
            mud_weight_ppg=9.6,
        )
        assert drop_ft == pytest.approx(12.003, abs=0.01)
        assert drop_psi == pytest.approx(5.99, abs=0.01)

    def test_pulling_many_stands_dry_is_serious(self):
        """Thirty stands (2700 ft) without filling loses about 180 psi."""
        _, drop_psi = hydrostatic_drop_from_not_filling(
            0.0065242, 2700.0, 0.0489215, 9.6
        )
        assert drop_psi == pytest.approx(179.8, abs=1.0)


class TestSlug:
    def test_slug_volume(self):
        """300 ft of dry pipe, 0.0177620 bbl/ft, 9.6 ppg mud, 12.5 ppg slug:
        V = 300 x 0.0177620 x 9.6 / (12.5 - 9.6) = 17.64 bbl
        """
        volume = slug_volume_for_dry_pipe(300.0, 0.0177620, 9.6, 12.5)
        assert volume == pytest.approx(17.64, abs=0.01)

    def test_round_trip(self):
        volume = slug_volume_for_dry_pipe(300.0, 0.0177620, 9.6, 12.5)
        length = dry_pipe_length_from_slug(volume, 0.0177620, 9.6, 12.5)
        assert length == pytest.approx(300.0, abs=0.01)

    def test_light_slug_is_rejected(self):
        with pytest.raises(ValueError, match="heavier than the mud"):
            slug_volume_for_dry_pipe(300.0, 0.0177620, 9.6, 9.0)
