"""
VRPTW-to-IRP Dataset Converter.
Converts existing VRPTW Hanoi JSON datasets to IRP-TW-DT Instance format.

Key transformations:
1. GPS coordinates → kept as-is, real road distance matrix via OSRM (km)
2. Single-day demand → multi-day demand[n,T] via lognormal with original as mean
3. TW in minutes → 2-shift mapping: [8h,12h] or [14h,18h]
4. Add inventory parameters: U, L_min, I0, h
"""

import json
import logging
import os
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

from src.core.instance import Instance
from src.core.constants import (
    DEFAULT_T, DEFAULT_Q, C_D, C_T, SERVICE_TIME, TW_SHIFTS,
)
from src.data.distances import compute_osrm_distance_matrix


def convert_vrptw_to_irp(
    vrptw_json_path: str,
    T: int = DEFAULT_T,
    m: Optional[int] = None,
    seed: int = 42,
    Q: float = DEFAULT_Q,
) -> Instance:
    """
    Convert a VRPTW Hanoi JSON file to an IRP-TW-DT Instance.

    Transformations:
    - Coordinates: GPS (lon, lat) preserved, OSRM real road distance in km
    - Demand: original single-day as mean → lognormal multi-day demand[n,T]
    - Time windows: minutes → 2-shift hours [8,12] or [14,18] based on original TW
    - Inventory params: generated from demand characteristics
    - Service time: 0.25h (15 min) per DevGuide spec

    Parameters
    ----------
    vrptw_json_path : str
        Path to the VRPTW JSON file.
    T : int
        Planning horizon in days (default 7).
    m : int or None
        Number of vehicles (if None, uses original file's value).
    seed : int
        Random seed for reproducibility.
    Q : float
        Vehicle capacity in units.

    Returns
    -------
    Instance
        Complete IRP-TW-DT instance with real Hanoi coordinates.
    """
    with open(vrptw_json_path, "r") as f:
        data = json.load(f)

    rng = np.random.default_rng(seed)

    # ---- Extract coordinates (GPS) ----
    depot = data["depot"]
    customers = data["customers"]
    n = len(customers)

    if m is None:
        m = data["metadata"].get("num_vehicles", max(2, n // 10))

    # Build coordinate array: [longitude, latitude]
    coords_gps = np.zeros((n + 1, 2))
    coords_gps[0] = [depot["x"], depot["y"]]
    for c in customers:
        coords_gps[c["id"]] = [c["x"], c["y"]]

    # ---- Distance matrix (OSRM real road distance) ----
    dist_matrix, used_osrm = compute_osrm_distance_matrix(coords_gps)
    logger.info(f"  OSRM real road distances computed for {n} customers")

    # ---- Time windows → 2-shift mapping ----
    # Original TW in minutes from midnight. Map to standard IRP shifts:
    #   ready_time < 720 (noon) → morning shift [8h, 12h]
    #   ready_time >= 720       → afternoon shift [14h, 18h]
    e = np.zeros(n)
    l = np.zeros(n)
    for c in customers:
        idx = c["id"] - 1  # 0-based for customer arrays
        midpoint_minutes = (c["ready_time"] + c["due_date"]) / 2.0
        if midpoint_minutes < 780.0:  # Before 13:00
            e[idx] = TW_SHIFTS[0][0]  # 8h
            l[idx] = TW_SHIFTS[0][1]  # 12h
        else:
            e[idx] = TW_SHIFTS[1][0]  # 14h
            l[idx] = TW_SHIFTS[1][1]  # 18h

    # ---- Service time: 0.25h for all ----
    s = np.full(n, SERVICE_TIME)

    # ---- Inventory parameters (generated from demand) ----
    # Use original VRPTW demand as base daily consumption rate
    original_demands = np.array([c["demand"] for c in customers])

    # U (max capacity): ~7 days of demand + buffer
    U = np.round(original_demands * 7.0 * rng.uniform(1.0, 1.5, n)).astype(float)
    U = np.maximum(U, 80.0)  # Minimum 80 units
    U = np.minimum(U, 300.0)  # Maximum 300 units

    # L_min (safety stock): 10-20% of U
    L_min = np.round(U * rng.uniform(0.10, 0.20, n)).astype(float)

    # I0 (initial inventory): between 30-60% of U
    I0 = np.round(rng.uniform(0.30, 0.60, n) * U).astype(float)
    I0 = np.maximum(I0, L_min)  # Ensure I0 >= L_min

    # Demand[n, T]: lognormal with mean ≈ original_demand, σ = 0.3
    # μ_d = log(mean) - σ²/2  (so that E[X] = mean)
    sigma = 0.3
    mu_d = np.log(original_demands) - sigma**2 / 2.0
    demand = np.zeros((n, T))
    for i in range(n):
        demand[i, :] = rng.lognormal(mu_d[i], sigma, T)
    demand = np.round(demand).astype(float)
    demand = np.maximum(demand, 1.0)  # At least 1 unit/day

    # Holding cost: 100-500 VND/unit/day
    h = np.round(rng.uniform(100, 500, n)).astype(float)

    # ---- Build instance ----
    basename = os.path.splitext(os.path.basename(vrptw_json_path))[0]
    name = f"irp_{basename}_seed{seed}"

    inst = Instance(
        name=name,
        n=n, T=T, m=m,
        coords=coords_gps,
        dist=dist_matrix,
        U=U, L_min=L_min, I0=I0,
        demand=demand, h=h,
        e=e, l=l, s=s,
        c_d=C_D, c_t=C_T, Q=Q,
    )

    return inst


def convert_all_lognormal(
    dataset_dir: str = "src/data/test-dataset",
    output_dir: str = "src/data/irp-instances",
    seeds: list = None,
) -> dict:
    """
    Convert all 3 lognormal VRPTW datasets to IRP-TW-DT instances.

    Creates one instance per (file, seed) combination.

    Parameters
    ----------
    dataset_dir : str
        Path to directory with VRPTW JSON files.
    output_dir : str
        Path to save converted instances.
    seeds : list
        Seeds for randomized parameters (default: [42, 123, 456, 789, 1000]).

    Returns
    -------
    dict
        Mapping {instance_name: Instance}.
    """
    from src.core.constants import EXPERIMENT_SEEDS, SCALE_CONFIGS
    from src.data.generator import save_instance

    if seeds is None:
        seeds = EXPERIMENT_SEEDS

    # The 3 lognormal files
    source_files = {
        "S": ("hanoi_lognormal_20_customers.json", 20, 2),
        "M": ("hanoi_lognormal_50_customers.json", 50, 3),
        "L": ("hanoi_lognormal_100_customers.json", 100, 5),
    }

    os.makedirs(output_dir, exist_ok=True)
    instances = {}

    for scale, (filename, n_expected, m) in source_files.items():
        json_path = os.path.join(dataset_dir, filename)
        if not os.path.exists(json_path):
            print(f"  WARNING: {json_path} not found, skipping")
            continue

        for seed in seeds:
            inst = convert_vrptw_to_irp(json_path, m=m, seed=seed)
            assert inst.n == n_expected, f"Expected n={n_expected}, got {inst.n}"

            # Save
            inst_dir = os.path.join(output_dir, f"{scale}_n{inst.n}_seed{seed}")
            save_instance(inst, inst_dir)
            instances[inst.name] = inst
            print(f"  Converted: {scale} n={inst.n} seed={seed} → {inst_dir}")

    return instances
