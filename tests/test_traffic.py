"""
Tests for IGP Traffic Model.
Verifies FIFO property, boundary conditions, and overnight travel.
"""

import pytest
import numpy as np
from src.core.constants import TRAFFIC_ZONES
from src.core.traffic import (
    igp_travel_time,
    igp_arrival_time,
    static_travel_time,
    precompute_travel_time_matrix,
    _find_zone,
)


class TestIGPTravelTime:
    """Core travel time computation tests."""

    def test_zero_distance(self):
        """Zero distance → zero travel time."""
        assert igp_travel_time(0.0, 8.0) == 0.0
        assert igp_travel_time(0.0, 0.0) == 0.0
        assert igp_travel_time(0.0, 23.99) == 0.0

    def test_within_single_zone(self):
        """Travel entirely within one zone."""
        # Zone 1: 0-6h, speed=27 km/h. 10km at 27 = 0.370 h
        tt = igp_travel_time(10.0, 1.0)
        assert abs(tt - 10.0 / 27.0) < 1e-6

        # Zone 2: 6-9h, speed=15 km/h. 5km at 15 = 0.333 h
        tt = igp_travel_time(5.0, 7.0)
        assert abs(tt - 5.0 / 15.0) < 1e-6

        # Zone 4: 17-19h, speed=14 km/h. 7km at 14 = 0.5 h
        tt = igp_travel_time(7.0, 17.5)
        assert abs(tt - 7.0 / 14.0) < 1e-6

    def test_crossing_zones(self):
        """Travel crossing zone boundary."""
        # Depart at 5.5h (Zone 1, speed=27), 0.5h available → 13.5km in zone 1
        # Then zone 2 (6-9h, speed=15)
        distance = 20.0  # Total 20km
        tt = igp_travel_time(distance, 5.5)
        # Zone 1: 0.5h × 27 = 13.5 km, remaining = 6.5km
        # Zone 2: 6.5/15 = 0.4333h
        expected = 0.5 + 6.5 / 15.0
        assert abs(tt - expected) < 1e-6

    def test_zone_boundary_departure(self):
        """Departing exactly at zone boundary."""
        # Depart at 6.0h → Zone 2 (speed=15)
        tt = igp_travel_time(15.0, 6.0)
        assert abs(tt - 15.0 / 15.0) < 1e-6

        # Depart at 17.0h → Zone 4 (speed=14)
        tt = igp_travel_time(14.0, 17.0)
        assert abs(tt - 14.0 / 14.0) < 1e-6


class TestFIFOProperty:
    """FIFO: earlier departure → earlier arrival, for all distances."""

    @pytest.mark.parametrize("distance", [1.0, 5.0, 10.0, 20.0, 50.0])
    def test_fifo_sweep(self, distance):
        """Sweep departure times and verify FIFO."""
        departures = np.arange(0.0, 24.0, 0.1)
        arrivals = [igp_arrival_time(distance, d) for d in departures]

        for i in range(len(arrivals) - 1):
            assert arrivals[i] <= arrivals[i + 1] + 1e-10, (
                f"FIFO violated: depart {departures[i]:.1f} arrives {arrivals[i]:.4f} "
                f"> depart {departures[i+1]:.1f} arrives {arrivals[i+1]:.4f} "
                f"for distance {distance}"
            )

    def test_fifo_adjacent_times(self):
        """FIFO for very close departure times."""
        for d in [5.0, 15.0]:
            for t in np.arange(0.0, 24.0, 0.01):
                a1 = igp_arrival_time(d, t)
                a2 = igp_arrival_time(d, t + 0.01)
                assert a1 <= a2 + 1e-10


class TestStaticTravelTime:
    """Static (constant speed) travel time."""

    def test_basic(self):
        assert abs(static_travel_time(18.0, 18.0) - 1.0) < 1e-10
        assert abs(static_travel_time(0.0, 18.0)) < 1e-10

    def test_custom_speed(self):
        assert abs(static_travel_time(30.0, 15.0) - 2.0) < 1e-10


class TestZoneFinding:
    """Test zone identification."""

    def test_boundaries(self):
        z = TRAFFIC_ZONES
        assert _find_zone(0.0, z) == 0
        assert _find_zone(5.99, z) == 0
        assert _find_zone(6.0, z) == 1
        assert _find_zone(8.99, z) == 1
        assert _find_zone(9.0, z) == 2
        assert _find_zone(16.99, z) == 2
        assert _find_zone(17.0, z) == 3
        assert _find_zone(18.99, z) == 3
        assert _find_zone(19.0, z) == 4
        assert _find_zone(23.99, z) == 4


class TestPrecompute:
    """Test matrix precomputation."""

    def test_shape(self):
        dist = np.array([[0, 5, 10], [5, 0, 7], [10, 7, 0]], dtype=float)
        tt = precompute_travel_time_matrix(dist, 8.0)
        assert tt.shape == (3, 3)
        assert tt[0, 0] == 0.0
        assert tt[1, 1] == 0.0
        assert tt[0, 1] > 0
