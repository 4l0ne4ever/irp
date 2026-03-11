"""
Instance data model for IRP-TW-DT.
Defines the Instance dataclass and validation utilities.
"""

from dataclasses import dataclass
from typing import List, Optional

import numpy as np

from .constants import DEFAULT_T, DEFAULT_Q, C_D, C_T, SERVICE_TIME


@dataclass
class Instance:
    """
    Complete problem instance for IRP-TW-DT.

    All distance units: km
    All time units: decimal hours (8.5 = 08:30)
    Index 0 is always the depot.
    """
    name: str           # e.g. "hanoi_n20_seed42"
    n: int              # Number of customers (excluding depot)
    T: int              # Planning horizon in days (default 7)
    m: int              # Number of vehicles

    # Spatial — index 0 = depot, indices 1..n = customers
    coords: np.ndarray  # (n+1, 2) GPS [lon, lat] or local [x, y] in km
    dist: np.ndarray    # (n+1, n+1) distance matrix in km (OSRM road / Haversine / Euclidean)

    # Inventory per customer — indices 0..n-1 map to customers 1..n
    U: np.ndarray       # (n,) max warehouse capacity
    L_min: np.ndarray   # (n,) safety stock floor
    I0: np.ndarray      # (n,) initial inventory at t=0
    demand: np.ndarray  # (n, T) deterministic daily demand
    h: np.ndarray       # (n,) holding cost VND/unit/day

    # Time windows — same every day, indices 0..n-1 for customers 1..n
    e: np.ndarray       # (n,) earliest service start (hours)
    l: np.ndarray       # (n,) latest service start (hours)
    s: np.ndarray       # (n,) service time in hours (default 0.25)

    # Cost parameters
    c_d: float = C_D    # VND/km
    c_t: float = C_T    # VND/hour
    Q: float = DEFAULT_Q  # Vehicle capacity (units)


def compute_distance_matrix(coords: np.ndarray) -> np.ndarray:
    """
    Compute Euclidean distance matrix from coordinates.

    Parameters
    ----------
    coords : np.ndarray
        Shape (N, 2) array of (x, y) coordinates.

    Returns
    -------
    np.ndarray
        Shape (N, N) symmetric distance matrix.
    """
    diff = coords[:, np.newaxis, :] - coords[np.newaxis, :, :]
    return np.sqrt(np.sum(diff ** 2, axis=2))


def validate_instance(inst: Instance) -> List[str]:
    """
    Validate instance data integrity. Returns list of error messages (empty = valid).

    Parameters
    ----------
    inst : Instance
        The instance to validate.

    Returns
    -------
    List[str]
        List of validation error messages. Empty if instance is valid.
    """
    errors = []
    n, T = inst.n, inst.T

    # Shape checks
    if inst.coords.shape != (n + 1, 2):
        errors.append(f"coords shape {inst.coords.shape} != ({n+1}, 2)")
    if inst.dist.shape != (n + 1, n + 1):
        errors.append(f"dist shape {inst.dist.shape} != ({n+1}, {n+1})")
    if inst.U.shape != (n,):
        errors.append(f"U shape {inst.U.shape} != ({n},)")
    if inst.L_min.shape != (n,):
        errors.append(f"L_min shape {inst.L_min.shape} != ({n},)")
    if inst.I0.shape != (n,):
        errors.append(f"I0 shape {inst.I0.shape} != ({n},)")
    if inst.demand.shape != (n, T):
        errors.append(f"demand shape {inst.demand.shape} != ({n}, {T})")
    if inst.h.shape != (n,):
        errors.append(f"h shape {inst.h.shape} != ({n},)")
    if inst.e.shape != (n,):
        errors.append(f"e shape {inst.e.shape} != ({n},)")
    if inst.l.shape != (n,):
        errors.append(f"l shape {inst.l.shape} != ({n},)")
    if inst.s.shape != (n,):
        errors.append(f"s shape {inst.s.shape} != ({n},)")

    # Value checks
    if np.any(inst.U <= 0):
        errors.append("U must be positive")
    if np.any(inst.L_min < 0):
        errors.append("L_min must be non-negative")
    if np.any(inst.L_min > inst.U):
        errors.append("L_min must be <= U")
    if np.any(inst.I0 < inst.L_min):
        errors.append("I0 must be >= L_min")
    if np.any(inst.I0 > inst.U):
        errors.append("I0 must be <= U")
    if np.any(inst.demand < 0):
        errors.append("demand must be non-negative")
    if np.any(inst.h < 0):
        errors.append("h must be non-negative")
    if np.any(inst.e < 0):
        errors.append("e must be non-negative")
    if np.any(inst.l <= inst.e):
        errors.append("l must be > e (time window must have positive width)")
    if np.any(inst.s < 0):
        errors.append("s must be non-negative")
    if inst.Q <= 0:
        errors.append("Q must be positive")
    if inst.m <= 0:
        errors.append("m must be positive")
    if inst.T <= 0:
        errors.append("T must be positive")

    # Distance matrix diagonal check (symmetry relaxed for OSRM road distances)
    if inst.dist.shape == (n + 1, n + 1):
        if np.any(np.diag(inst.dist) != 0):
            errors.append("dist diagonal must be zero")
        # OSRM road distances may not be perfectly symmetric (A→B ≠ B→A due
        # to one-way streets etc.), so we use a relaxed tolerance
        if not np.allclose(inst.dist, inst.dist.T, atol=0.5):
            errors.append("dist matrix asymmetry exceeds 0.5 km tolerance")

    return errors
