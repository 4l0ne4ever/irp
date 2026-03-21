"""
Load IRP-TW-DT instances from uploaded JSON or CSV.
OSRM distance matrix is required — raises RuntimeError on failure (no fallback).
"""

import csv as csv_module
import io
import json
from typing import Tuple

import numpy as np

from src.core.instance import Instance, validate_instance
from src.core.constants import (
    DEFAULT_T,
    DEFAULT_Q,
    SERVICE_TIME,
    C_D,
    C_T,
)
from src.data.distances import compute_osrm_distance_matrix


def load_from_json(file_bytes: bytes) -> Tuple[Instance, np.ndarray]:
    """
    Parse IRP JSON, call OSRM, build and validate Instance.

    Raises RuntimeError on parse, OSRM, or validation errors.
    """
    try:
        data = json.loads(file_bytes.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise RuntimeError(f"Invalid JSON: {e}") from e

    meta = data.get("metadata")
    depot = data.get("depot")
    customers = data.get("customers")
    if not meta or depot is None or not customers:
        raise RuntimeError("JSON must contain metadata, depot, and customers")

    n = int(meta.get("n", 0))
    T = int(meta.get("T", DEFAULT_T))
    m = int(meta.get("m", 0))
    if n != len(customers):
        raise RuntimeError(f"metadata.n={n} but customers has {len(customers)} entries")

    coords = np.zeros((n + 1, 2))
    coords[0] = [float(depot["lon"]), float(depot["lat"])]
    for i, c in enumerate(customers):
        coords[i + 1] = [float(c["lon"]), float(c["lat"])]

    dist_matrix, _ = compute_osrm_distance_matrix(coords)

    U = np.array([float(c["tank_capacity"]) for c in customers])
    L_min = np.array([float(c["min_inventory"]) for c in customers])
    I0 = np.array([float(c["initial_inventory"]) for c in customers])
    demand = np.array([c["daily_demand"] for c in customers], dtype=float)
    if demand.shape != (n, T):
        raise RuntimeError(f"daily_demand must be length {T} per customer, got shape {demand.shape}")
    h = np.array([float(c["holding_cost_vnd"]) for c in customers])
    e = np.array([float(c["time_window_start_h"]) for c in customers])
    l = np.array([float(c["time_window_end_h"]) for c in customers])
    s = np.array([float(c.get("service_time_h", SERVICE_TIME)) for c in customers])

    name = meta.get("name", "upload_json")
    c_d = float(meta.get("c_d", C_D))
    c_t = float(meta.get("c_t", C_T))
    Q = float(meta.get("Q", DEFAULT_Q))

    inst = Instance(
        name=name,
        n=n,
        T=T,
        m=m,
        coords=coords,
        dist=dist_matrix,
        U=U,
        L_min=L_min,
        I0=I0,
        demand=demand,
        h=h,
        e=e,
        l=l,
        s=s,
        c_d=c_d,
        c_t=c_t,
        Q=Q,
    )

    errors = validate_instance(inst)
    if errors:
        raise RuntimeError("Instance validation failed: " + "; ".join(errors))

    return inst, dist_matrix


def load_from_csv(
    file_bytes: bytes,
    depot_lon: float,
    depot_lat: float,
    n: int,
    m: int,
) -> Tuple[Instance, np.ndarray]:
    """
    Parse customer CSV rows, validate row count == n, build Instance with m vehicles.

    Optional first line starting with '#' (metadata) is skipped before DictReader.
    """
    text = file_bytes.decode("utf-8")
    lines = text.splitlines()
    if not lines:
        raise RuntimeError("CSV file is empty")

    data_start = 1 if lines[0].strip().startswith("#") else 0
    stream = io.StringIO("\n".join(lines[data_start:]))
    try:
        reader = csv_module.DictReader(stream)
        rows = list(reader)
    except Exception as e:
        raise RuntimeError(f"Invalid CSV: {e}") from e

    if len(rows) != n:
        raise RuntimeError(f"CSV has {len(rows)} data rows but n={n}")

    T = DEFAULT_T
    coords = np.zeros((n + 1, 2))
    coords[0] = [depot_lon, depot_lat]

    U = np.zeros(n)
    L_min = np.zeros(n)
    I0 = np.zeros(n)
    demand = np.zeros((n, T))
    h = np.zeros(n)
    e = np.zeros(n)
    l = np.zeros(n)
    s = np.zeros(n)

    for i, row in enumerate(rows):
        coords[i + 1] = [float(row["lon"]), float(row["lat"])]
        U[i] = float(row["tank_capacity"])
        L_min[i] = float(row["min_inventory"])
        I0[i] = float(row["initial_inventory"])
        h[i] = float(row["holding_cost_vnd"])
        e[i] = float(row["time_window_start_h"])
        l[i] = float(row["time_window_end_h"])
        s[i] = float(row.get("service_time_h", SERVICE_TIME))
        for t in range(T):
            key = f"demand_day{t}"
            if key not in row:
                raise RuntimeError(f"CSV missing column {key}")
            demand[i, t] = float(row[key])

    dist_matrix, _ = compute_osrm_distance_matrix(coords)

    inst = Instance(
        name="upload_csv",
        n=n,
        T=T,
        m=m,
        coords=coords,
        dist=dist_matrix,
        U=U,
        L_min=L_min,
        I0=I0,
        demand=demand,
        h=h,
        e=e,
        l=l,
        s=s,
        c_d=C_D,
        c_t=C_T,
        Q=DEFAULT_Q,
    )

    errors = validate_instance(inst)
    if errors:
        raise RuntimeError("Instance validation failed: " + "; ".join(errors))

    return inst, dist_matrix
