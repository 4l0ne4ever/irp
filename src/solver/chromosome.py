"""
Two-part Chromosome for IRP-TW-DT.
Encodes both allocation (inventory) and routing decisions.
"""

from dataclasses import dataclass
from typing import Optional

import numpy as np

from src.core.instance import Instance


@dataclass
class Chromosome:
    """
    Two-part chromosome encoding:
    - Y (n x T): binary allocation matrix. Y[i,t]=1 → customer i+1 gets delivery on day t.
    - pi (n,): permutation of customers (0-based indices into customer array).
              Determines relative order for routing.
    """
    Y: np.ndarray   # (n, T) binary
    pi: np.ndarray   # (n,) permutation of 0..n-1

    # Cached fitness (invalidated on modification)
    _fitness: Optional[float] = None


def random_chromosome(inst: Instance, rng: np.random.Generator) -> Chromosome:
    """
    Create a random but inventory-feasible chromosome.

    Strategy:
    1. Initialize Y with a greedy approach: simulate inventory forward,
       schedule delivery whenever stock would drop below L_min.
    2. Add some random extra deliveries for diversity.
    3. Random permutation for pi.

    Parameters
    ----------
    inst : Instance
    rng : np.random.Generator

    Returns
    -------
    Chromosome
    """
    n, T = inst.n, inst.T
    m = inst.m
    Y = np.zeros((n, T), dtype=np.int32)

    # Estimate max customers per shift for load balancing
    avg_inter_dist = np.mean(inst.dist[1:, 1:][
        inst.dist[1:, 1:] > 0
    ]) if n > 1 else 5.0
    avg_depot_dist = np.mean(inst.dist[0, 1:]) if n > 0 else 5.0
    avg_travel = avg_inter_dist / 18.0
    depot_travel = avg_depot_dist / 18.0
    tw_width = 4.0
    usable_time = max(tw_width - depot_travel, 1.0)
    per_stop_time = np.mean(inst.s) + avg_travel
    max_per_route = max(2, int(usable_time / per_stop_time) - 1)
    max_per_shift = m * max_per_route

    # Greedy: simulate inventory, deliver when needed
    I = inst.I0.copy()
    for t in range(T):
        for i in range(n):
            # Will stock drop below safety after consuming demand?
            projected = I[i] - inst.demand[i, t]
            if projected < inst.L_min[i]:
                Y[i, t] = 1
                I[i] = inst.U[i]  # Order-up-to
            else:
                I[i] = projected

        # Random extra deliveries for diversity (with probability 0.15)
        extras = rng.random(n) < 0.15
        for i in range(n):
            if extras[i] and Y[i, t] == 0:
                if I[i] < inst.U[i] * 0.8:
                    Y[i, t] = 1
                    I[i] = inst.U[i]

    # Ensure every customer gets at least one delivery
    for i in range(n):
        if np.sum(Y[i, :]) == 0:
            Y[i, 0] = 1

    # --- Shift-aware load balancing ---
    I = inst.I0.copy()
    for t in range(T):
        for is_morning in [True, False]:
            shift_custs = [
                c for c in range(n)
                if Y[c, t] == 1 and (inst.e[c] < 13.0) == is_morning
            ]

            if len(shift_custs) > max_per_shift:
                # Sort by inventory surplus descending — defer easiest first
                surplus = np.array([
                    I[c] - inst.demand[c, t] - inst.L_min[c]
                    for c in shift_custs
                ])
                defer_order = np.argsort(-surplus)

                for idx in defer_order:
                    cur_count = sum(
                        1 for c in range(n)
                        if Y[c, t] == 1 and (inst.e[c] < 13.0) == is_morning
                    )
                    if cur_count <= max_per_shift:
                        break
                    c = shift_custs[idx]

                    # Try shifting to adjacent day
                    for dt in [1, -1, 2, -2]:
                        t_new = t + dt
                        if t_new < 0 or t_new >= T:
                            continue
                        if Y[c, t_new] == 1:
                            continue
                        # Check that deferring doesn't cause stockout
                        I_after = I[c] - inst.demand[c, t]
                        if I_after >= inst.L_min[c]:
                            Y[c, t] = 0
                            Y[c, t_new] = 1
                            break

        # Update inventory for current day
        for i in range(n):
            if Y[i, t] == 1:
                I[i] = inst.U[i]
            else:
                I[i] = I[i] - inst.demand[i, t]

    # Random permutation
    pi = rng.permutation(n).astype(np.int32)

    return Chromosome(Y=Y, pi=pi)


def copy_chromosome(c: Chromosome) -> Chromosome:
    """Create a deep copy of a chromosome."""
    return Chromosome(
        Y=c.Y.copy(),
        pi=c.pi.copy(),
        _fitness=c._fitness,
    )
