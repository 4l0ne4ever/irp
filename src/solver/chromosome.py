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
    n = inst.n
    Y = _greedy_Y(inst, rng)

    # Giant-tour permutation: random
    pi = rng.permutation(n).astype(np.int32)

    return Chromosome(Y=Y, pi=pi)


def savings_chromosome(inst: Instance, rng: np.random.Generator) -> Chromosome:
    """
    Create a chromosome with savings-based π ordering.

    Uses Clarke-Wright savings heuristic to construct a good initial
    giant tour. The savings s(i,j) = dist[0,i] + dist[0,j] - dist[i,j]
    orders customers so that neighbouring customers in π tend to save
    the most distance when grouped into the same route.

    Combined with the standard greedy Y initialisation and load-balancing.

    Reference: Clarke G., Wright J. (1964) "Scheduling of Vehicles from
    a Central Depot to a Number of Delivery Points." Operations Research.
    """
    n, T = inst.n, inst.T

    # Compute savings: s(i,j) = dist[0,i+1] + dist[0,j+1] - dist[i+1,j+1]
    savings = []
    for i in range(n):
        for j in range(i + 1, n):
            s = (inst.dist[0, i + 1] + inst.dist[0, j + 1]
                 - inst.dist[i + 1, j + 1])
            savings.append((s, i, j))
    savings.sort(reverse=True)

    # Build routes (chains) using savings heuristic
    # Each customer starts in its own route
    route_of = list(range(n))     # route_of[i] = which route customer i belongs to
    route_chains = {i: [i] for i in range(n)}  # route_id -> ordered customer list
    head = list(range(n))  # head[route_id] = first customer
    tail = list(range(n))  # tail[route_id] = last customer

    for s_val, i, j in savings:
        ri, rj = route_of[i], route_of[j]
        if ri == rj:
            continue  # same route

        # Merge only if i is at tail of ri and j is at head of rj (or vice versa)
        if tail[ri] == i and head[rj] == j:
            # Append rj after ri
            route_chains[ri].extend(route_chains[rj])
            tail[ri] = tail[rj]
            for c in route_chains[rj]:
                route_of[c] = ri
            del route_chains[rj]
        elif tail[rj] == j and head[ri] == i:
            # Append ri after rj
            route_chains[rj].extend(route_chains[ri])
            tail[rj] = tail[ri]
            for c in route_chains[ri]:
                route_of[c] = rj
            del route_chains[ri]
        # else: can't merge (interior nodes)

    # Build π by concatenating route chains
    pi = []
    for chain in route_chains.values():
        pi.extend(chain)
    pi = np.array(pi, dtype=np.int32)

    # Standard greedy Y initialisation (same as random_chromosome)
    Y = _greedy_Y(inst, rng)

    return Chromosome(Y=Y, pi=pi)


def _greedy_Y(inst: Instance, rng: np.random.Generator) -> np.ndarray:
    """Greedy inventory-feasible Y initialisation with load balancing."""
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
    usable_time = max(tw_width - 2 * depot_travel, 1.0)
    per_stop_time = np.mean(inst.s) + avg_travel
    max_per_route = max(2, int(usable_time / per_stop_time) - 1)
    max_per_shift = m * max_per_route

    # Greedy: simulate inventory, deliver when needed
    I = inst.I0.copy()
    for t in range(T):
        for i in range(n):
            projected = I[i] - inst.demand[i, t]
            if projected < inst.L_min[i]:
                Y[i, t] = 1
                I[i] = inst.U[i]
            else:
                I[i] = projected

        # Random extra deliveries for diversity (probability 0.15)
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

    # Shift-aware load balancing
    I = inst.I0.copy()
    for t in range(T):
        for is_morning in [True, False]:
            shift_custs = [
                c for c in range(n)
                if Y[c, t] == 1 and (inst.e[c] < 13.0) == is_morning
            ]

            if len(shift_custs) > max_per_shift:
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

                    for dt in [1, -1, 2, -2]:
                        t_new = t + dt
                        if t_new < 0 or t_new >= T:
                            continue
                        if Y[c, t_new] == 1:
                            continue
                        I_after = I[c] - inst.demand[c, t]
                        if I_after >= inst.L_min[c]:
                            Y[c, t] = 0
                            Y[c, t_new] = 1
                            break

        for i in range(n):
            if Y[i, t] == 1:
                I[i] = inst.U[i]
            else:
                I[i] = I[i] - inst.demand[i, t]

    return Y


def copy_chromosome(c: Chromosome) -> Chromosome:
    """Create a deep copy of a chromosome."""
    return Chromosome(
        Y=c.Y.copy(),
        pi=c.pi.copy(),
        _fitness=c._fitness,
    )
