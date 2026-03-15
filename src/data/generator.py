"""
Synthetic Hanoi dataset generator for IRP-TW-DT.
Generates clustered customer locations with inventory parameters.
"""

import json
import os
from typing import Optional, Tuple

import numpy as np

from src.core.constants import (
    DEFAULT_T, DEFAULT_Q, C_D, C_T, SERVICE_TIME,
    NUM_CLUSTERS, MAX_RADIUS_KM, TW_SHIFTS,
)
from src.core.instance import Instance
from src.core.traffic import igp_travel_time
from src.data.distances import compute_osrm_distance_matrix

# Hanoi city centre (Hoan Kiem Lake) — reference for synthetic instances.
# 1km ≈ 0.00899° lat, 0.00949° lon at this latitude.
_HANOI_LON = 105.8542
_HANOI_LAT = 21.0285
_DEG_PER_KM_LAT = 1.0 / 111.32
_DEG_PER_KM_LON = 1.0 / (111.32 * np.cos(np.radians(_HANOI_LAT)))

# Exclusion zones in degrees (lon_min, lon_max, lat_min, lat_max) — water / undeliverable.
# West Lake (Ho Tay): ~5.26 km², center ~21.055, 105.82; generous box to avoid shoreline.
# Red River: strip through Hanoi; extended box to cover main channel.
# Hoan Kiem Lake: small; depot is nearby so we use a small exclusion (no customer on the lake).
_EXCLUSION_BOXES = [
    (105.785, 105.865, 21.032, 21.078),   # West Lake (Ho Tay) — enlarged
    (105.805, 105.935, 20.985, 21.072),   # Red River stretch — wider/longer
    (105.848, 105.862, 21.024, 21.034),   # Hoan Kiem Lake (no customers on water)
]


def _is_deliverable_location(lon: float, lat: float) -> bool:
    """Return False if (lon, lat) lies in an exclusion zone (water / undeliverable)."""
    for (lon_lo, lon_hi, lat_lo, lat_hi) in _EXCLUSION_BOXES:
        if lon_lo <= lon <= lon_hi and lat_lo <= lat <= lat_hi:
            return False
    return True


def _nudge_to_deliverable(lon: float, lat: float, max_steps: int = 20) -> Tuple[float, float]:
    """Move (lon, lat) toward depot until deliverable or max_steps. Returns (lon, lat)."""
    for _ in range(max_steps):
        if _is_deliverable_location(lon, lat):
            return (float(lon), float(lat))
        lon = 0.5 * (lon + _HANOI_LON)
        lat = 0.5 * (lat + _HANOI_LAT)
    return (float(lon), float(lat))


def generate_hanoi_instance(
    n: int,
    m: int,
    T: int = DEFAULT_T,
    seed: int = 42,
    Q: float = DEFAULT_Q,
) -> Instance:
    """
    Generate a synthetic Hanoi IRP-TW-DT instance.

    Customers are distributed in K=5 Gaussian clusters within 15km
    of the depot (Hoan Kiem center at origin).

    Parameters
    ----------
    n : int
        Number of customers.
    m : int
        Number of vehicles.
    T : int
        Planning horizon in days (default 7).
    seed : int
        Random seed for reproducibility.
    Q : float
        Vehicle capacity.

    Returns
    -------
    Instance
        Complete problem instance.
    """
    rng = np.random.default_rng(seed)

    # ---- Coordinates: depot at origin, customers in clusters ----
    # Cluster radii from lognormal so most clusters at moderate distance, few far (realistic spread)
    mean_radius_km = 0.5 * MAX_RADIUS_KM * 0.7
    mu_r = np.log(mean_radius_km)
    sigma_r = 0.6
    cluster_radii = rng.lognormal(mu_r, sigma_r, NUM_CLUSTERS)
    cluster_radii = np.clip(cluster_radii, 2.0, MAX_RADIUS_KM * 0.85)
    cluster_angles = rng.uniform(0, 2 * np.pi, NUM_CLUSTERS)
    cluster_centers = np.column_stack([
        cluster_radii * np.cos(cluster_angles),
        cluster_radii * np.sin(cluster_angles),
    ])

    # Assign customers to clusters; spread within cluster also lognormal (distance from centre)
    assignments = rng.integers(0, NUM_CLUSTERS, size=n)
    cluster_std_km = 1.2

    customer_coords = np.zeros((n, 2))
    max_resample = 50
    for i in range(n):
        center = cluster_centers[assignments[i]]
        for _ in range(max_resample):
            # Lognormal radial offset then random angle
            r = rng.lognormal(0, 0.5) * cluster_std_km
            theta = rng.uniform(0, 2 * np.pi)
            pt = center + r * np.array([np.cos(theta), np.sin(theta)])
            dist = np.sqrt(np.sum(pt ** 2))
            if dist > MAX_RADIUS_KM:
                scale = MAX_RADIUS_KM / dist * 0.95
                pt = pt * scale
            lon = _HANOI_LON + pt[0] * _DEG_PER_KM_LON
            lat = _HANOI_LAT + pt[1] * _DEG_PER_KM_LAT
            if _is_deliverable_location(lon, lat):
                customer_coords[i] = pt
                break
        else:
            # Fallback: place near centre then nudge to deliverable
            pt = center + rng.normal(0, 0.5, 2)
            lon, lat = _HANOI_LON + pt[0] * _DEG_PER_KM_LON, _HANOI_LAT + pt[1] * _DEG_PER_KM_LAT
            lon, lat = _nudge_to_deliverable(lon, lat)
            customer_coords[i] = np.array([(lon - _HANOI_LON) / _DEG_PER_KM_LON, (lat - _HANOI_LAT) / _DEG_PER_KM_LAT])

    # Clip to max radius
    dists_from_depot = np.sqrt(np.sum(customer_coords ** 2, axis=1))
    too_far = dists_from_depot > MAX_RADIUS_KM
    if np.any(too_far):
        scale = MAX_RADIUS_KM / dists_from_depot[too_far]
        customer_coords[too_far] *= scale[:, np.newaxis] * 0.95

    # Combine depot (0,0) with customers — local km coords
    local_coords = np.vstack([np.array([[0.0, 0.0]]), customer_coords])

    # Convert local (x_km, y_km) to GPS [lon, lat] relative to Hanoi centre
    coords = np.zeros_like(local_coords)
    coords[:, 0] = _HANOI_LON + local_coords[:, 0] * _DEG_PER_KM_LON  # lon
    coords[:, 1] = _HANOI_LAT + local_coords[:, 1] * _DEG_PER_KM_LAT  # lat

    # Final check: nudge any customer still in water until deliverable
    for i in range(n):
        coords[i + 1, 0], coords[i + 1, 1] = _nudge_to_deliverable(
            float(coords[i + 1, 0]), float(coords[i + 1, 1])
        )

    dist_matrix, _ = compute_osrm_distance_matrix(coords)

    # ---- Inventory parameters ----
    U = rng.uniform(80, 200, n).astype(float)
    L_min = U * rng.uniform(0.10, 0.20, n)
    I0 = rng.uniform(L_min, 0.6 * U)

    # Demand: Lognormal with mean ≈ U/7
    mu_d = np.log(U / 7.0)
    demand = np.zeros((n, T))
    for i in range(n):
        demand[i, :] = rng.lognormal(mu_d[i], 0.3, T)

    # Round demand to integers for cleanliness
    demand = np.round(demand).astype(float)
    demand = np.maximum(demand, 1.0)  # At least 1 unit/day

    # Holding cost
    h = rng.uniform(100, 500, n).astype(float)

    # ---- Time windows: 2 shifts ----
    e = np.zeros(n)
    l = np.zeros(n)
    for i in range(n):
        shift_idx = rng.integers(0, len(TW_SHIFTS))
        e[i] = TW_SHIFTS[shift_idx][0]
        l[i] = TW_SHIFTS[shift_idx][1]

    # Service time
    s = np.full(n, SERVICE_TIME)

    # ---- Create instance ----
    inst = Instance(
        name=f"hanoi_n{n}_seed{seed}",
        n=n, T=T, m=m,
        coords=coords, dist=dist_matrix,
        U=U, L_min=L_min, I0=I0,
        demand=demand, h=h,
        e=e, l=l, s=s,
        c_d=C_D, c_t=C_T, Q=Q,
    )

    # ---- Verify single-visit feasibility ----
    if not verify_single_visit_feasibility(inst):
        # Retry with different seed (rare edge case)
        return generate_hanoi_instance(n, m, T, seed + 10000, Q)

    return inst


def verify_single_visit_feasibility(inst: Instance) -> bool:
    """
    Verify each customer can be reached and start service within [e_i, l_i]
    using conservative worst-case departure (6h) so instances are not admitted
    that would later violate TW when service time and waiting are applied.

    Uses service_start = max(arrival, e_i) and requires service_start <= l_i.
    """
    for i in range(inst.n):
        cust_node = i + 1  # 1-based index in distance matrix
        distance = inst.dist[0, cust_node]

        # Conservative: worst-case departure 6h (slowest zone 6–9h) for all customers
        depart_time = 6.0
        travel_time = igp_travel_time(distance, depart_time)
        arrival = depart_time + travel_time
        service_start = max(arrival, inst.e[i])

        # Must be able to start service within [e_i, l_i]
        if service_start > inst.l[i] - 1e-6:
            return False

    return True


def save_instance(inst: Instance, path: str) -> None:
    """Save instance to a directory as numpy arrays + metadata JSON."""
    os.makedirs(path, exist_ok=True)

    # Save arrays
    np.save(os.path.join(path, "coords.npy"), inst.coords)
    np.save(os.path.join(path, "dist.npy"), inst.dist)
    np.save(os.path.join(path, "U.npy"), inst.U)
    np.save(os.path.join(path, "L_min.npy"), inst.L_min)
    np.save(os.path.join(path, "I0.npy"), inst.I0)
    np.save(os.path.join(path, "demand.npy"), inst.demand)
    np.save(os.path.join(path, "h.npy"), inst.h)
    np.save(os.path.join(path, "e.npy"), inst.e)
    np.save(os.path.join(path, "l.npy"), inst.l)
    np.save(os.path.join(path, "s.npy"), inst.s)

    # Save metadata
    meta = {
        "name": inst.name,
        "n": inst.n, "T": inst.T, "m": inst.m,
        "c_d": inst.c_d, "c_t": inst.c_t, "Q": inst.Q,
    }
    with open(os.path.join(path, "meta.json"), "w") as f:
        json.dump(meta, f, indent=2)


def load_instance(path: str) -> Instance:
    """Load instance from directory."""
    with open(os.path.join(path, "meta.json")) as f:
        meta = json.load(f)

    return Instance(
        name=meta["name"],
        n=meta["n"], T=meta["T"], m=meta["m"],
        coords=np.load(os.path.join(path, "coords.npy")),
        dist=np.load(os.path.join(path, "dist.npy")),
        U=np.load(os.path.join(path, "U.npy")),
        L_min=np.load(os.path.join(path, "L_min.npy")),
        I0=np.load(os.path.join(path, "I0.npy")),
        demand=np.load(os.path.join(path, "demand.npy")),
        h=np.load(os.path.join(path, "h.npy")),
        e=np.load(os.path.join(path, "e.npy")),
        l=np.load(os.path.join(path, "l.npy")),
        s=np.load(os.path.join(path, "s.npy")),
        c_d=meta["c_d"], c_t=meta["c_t"], Q=meta["Q"],
    )
