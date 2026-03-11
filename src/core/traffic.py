"""
IGP Travel Time Model — Piecewise Constant Speed Function
Implements Ichoua, Gendreau & Potvin (2003) with Hanoi 5-zone profile.

FIFO guarantee: For all τ₁ < τ₂ and all d ≥ 0:
    τ₁ + τ(d, τ₁) ≤ τ₂ + τ(d, τ₂)
This is guaranteed by construction for piecewise-constant speed functions
(Ghiani & Guerriero, 2014).
"""

import numpy as np
from .constants import TRAFFIC_ZONES, ZONE_BOUNDARIES, ZONE_SPEEDS, NUM_ZONES, H


def igp_travel_time(distance_km: float, depart_h: float) -> float:
    """
    Compute travel time from departure time using IGP piecewise constant speed.

    Parameters
    ----------
    distance_km : float
        Distance to travel (km), typically road distance from OSRM. Must be ≥ 0.
    depart_h : float
        Departure time in decimal hours (e.g., 8.5 = 08:30). Must be ≥ 0.

    Returns
    -------
    float
        Travel time in hours.
    """
    if distance_km <= 0.0:
        return 0.0
    if distance_km < 0.0:
        raise ValueError(f"distance_km must be >= 0, got {distance_km}")

    # Normalize departure to [0, 24)
    depart_h = depart_h % H

    remaining_km = distance_km
    current_h = depart_h
    elapsed_h = 0.0

    # Iterate through zones starting from the one containing current_h
    max_iterations = NUM_ZONES * 3  # Safety: at most wrap around a few times
    iteration = 0

    while remaining_km > 1e-12 and iteration < max_iterations:
        iteration += 1

        # Find which zone we're in
        zone_idx = _find_zone(current_h)
        z_start, z_end, speed = TRAFFIC_ZONES[zone_idx]

        # Time available in this zone from current position
        time_available = z_end - current_h
        if time_available <= 1e-12:
            # At boundary, move to next zone
            current_h = z_end % H
            if current_h < 1e-12 and z_end >= H:
                current_h = 0.0
            continue

        # Distance we can cover in this zone
        dist_possible = time_available * speed

        if remaining_km <= dist_possible + 1e-12:
            # Can finish within this zone
            elapsed_h += remaining_km / speed
            remaining_km = 0.0
        else:
            # Consume entire zone and move to next
            elapsed_h += time_available
            remaining_km -= dist_possible
            current_h = z_end % H
            if current_h < 1e-12 and z_end >= H:
                current_h = 0.0

    return elapsed_h


def _find_zone(hour: float) -> int:
    """Find the zone index for a given hour in [0, 24)."""
    hour = hour % H
    for i, (z_start, z_end, _) in enumerate(TRAFFIC_ZONES):
        if z_start <= hour < z_end:
            return i
    # Edge case: exactly 24.0 wraps to zone 0
    return 0


def igp_arrival_time(distance_km: float, depart_h: float) -> float:
    """
    Compute arrival time = departure + travel time.

    Parameters
    ----------
    distance_km : float
        Distance to travel (km).
    depart_h : float
        Departure time in decimal hours.

    Returns
    -------
    float
        Arrival time in decimal hours (may exceed 24 for overnight travel).
    """
    return depart_h + igp_travel_time(distance_km, depart_h)


def static_travel_time(distance_km: float, speed_kmh: float = 18.0) -> float:
    """
    Compute travel time with constant speed (for static scenarios).

    Parameters
    ----------
    distance_km : float
        Distance in km.
    speed_kmh : float
        Constant speed in km/h (default: 18 km/h).

    Returns
    -------
    float
        Travel time in hours.
    """
    if distance_km <= 0.0:
        return 0.0
    return distance_km / speed_kmh


def precompute_travel_time_matrix(
    dist_matrix: np.ndarray,
    depart_h: float
) -> np.ndarray:
    """
    Compute travel time matrix for all (i,j) pairs at a fixed departure time.

    Parameters
    ----------
    dist_matrix : np.ndarray
        Shape (N, N) distance matrix in km.
    depart_h : float
        Fixed departure time in decimal hours.

    Returns
    -------
    np.ndarray
        Shape (N, N) travel time matrix in hours.
    """
    N = dist_matrix.shape[0]
    tt_matrix = np.zeros((N, N))
    for i in range(N):
        for j in range(N):
            if i != j:
                tt_matrix[i, j] = igp_travel_time(dist_matrix[i, j], depart_h)
    return tt_matrix


def precompute_static_travel_time_matrix(
    dist_matrix: np.ndarray,
    speed_kmh: float = 18.0
) -> np.ndarray:
    """
    Compute static travel time matrix (constant speed).

    Parameters
    ----------
    dist_matrix : np.ndarray
        Shape (N, N) distance matrix in km.
    speed_kmh : float
        Constant speed in km/h.

    Returns
    -------
    np.ndarray
        Shape (N, N) travel time matrix in hours.
    """
    tt_matrix = np.zeros_like(dist_matrix)
    mask = dist_matrix > 0
    tt_matrix[mask] = dist_matrix[mask] / speed_kmh
    return tt_matrix
