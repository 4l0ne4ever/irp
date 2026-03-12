"""
Evolutionary operators for IRP-TW-DT HGA.
Crossover, Mutation, and Repair operators for Two-part Chromosome.
"""

import numpy as np

from src.core.instance import Instance
from src.core.inventory import simulate_inventory, check_feasibility
from .chromosome import Chromosome, copy_chromosome


def crossover(
    p1: Chromosome,
    p2: Chromosome,
    inst: Instance,
    rng: np.random.Generator,
) -> tuple:
    """
    Two-part crossover:
    - Tầng 1 (Y): Uniform Crossover
    - Tầng 2 (π): Order Crossover (OX)

    Returns two offspring.
    """
    c1 = copy_chromosome(p1)
    c2 = copy_chromosome(p2)

    # --- Tầng 1: Uniform Crossover on Y ---
    mask = rng.random(c1.Y.shape) < 0.5
    c1.Y = np.where(mask, p1.Y, p2.Y)
    c2.Y = np.where(mask, p2.Y, p1.Y)

    # --- Tầng 2: Order Crossover (OX) on pi ---
    c1.pi = _ox_crossover(p1.pi, p2.pi, rng)
    c2.pi = _ox_crossover(p2.pi, p1.pi, rng)

    c1._fitness = None
    c2._fitness = None

    return c1, c2


def _ox_crossover(
    parent1: np.ndarray,
    parent2: np.ndarray,
    rng: np.random.Generator,
) -> np.ndarray:
    """Order Crossover (OX) for permutation encoding."""
    n = len(parent1)
    child = np.full(n, -1, dtype=np.int32)

    # Select random segment
    start = rng.integers(0, n)
    end = rng.integers(start + 1, n + 1)

    # Copy segment from parent1
    child[start:end] = parent1[start:end]

    # Fill remaining positions with parent2 order
    segment_set = set(child[start:end])
    remaining = [g for g in parent2 if g not in segment_set]

    pos = 0
    for i in range(n):
        if child[i] == -1:
            child[i] = remaining[pos]
            pos += 1

    return child


def mutate(
    chrom: Chromosome,
    inst: Instance,
    rng: np.random.Generator,
    rate_y: float = 0.05,
    rate_pi: float = 0.10,
) -> None:
    """
    In-place mutation:
    - Tầng 1 (Y): Random bit-flip with probability rate_y per cell.
    - Tầng 2 (π): Swap mutation or Inversion mutation.
    """
    n, T = inst.n, inst.T

    # --- Tầng 1: Bit-flip on Y ---
    flip_mask = rng.random((n, T)) < rate_y
    chrom.Y = np.where(flip_mask, 1 - chrom.Y, chrom.Y)

    # --- Tầng 2: Swap or Inversion on pi ---
    if rng.random() < rate_pi:
        if rng.random() < 0.5:
            # Swap mutation
            i, j = rng.choice(n, 2, replace=False)
            chrom.pi[i], chrom.pi[j] = chrom.pi[j], chrom.pi[i]
        else:
            # Inversion mutation
            i, j = sorted(rng.choice(n, 2, replace=False))
            chrom.pi[i:j + 1] = chrom.pi[i:j + 1][::-1]

    chrom._fitness = None


def repair(
    chrom: Chromosome,
    inst: Instance,
) -> None:
    """
    Repair chromosome to ensure inventory AND routing feasibility.

    Phase 1: Forward-simulate inventory; whenever I[i,t] < L_min[i],
             force Y[i,t] = 1 (deliver on that day).
    Phase 2: Shift-aware load balancing — limit customers per TW shift
             so TD-Split produces ≤ m routes per shift.
    """
    n, T = inst.n, inst.T
    m = inst.m

    # --- Phase 1: Fix stockouts (iterate until convergence) ---
    max_iter_stockout = T * 2
    for iteration in range(max_iter_stockout):
        I_matrix, q_matrix = simulate_inventory(chrom.Y, inst)
        violations = check_feasibility(I_matrix, inst)

        if not violations:
            break

        for cust_0based, day in violations:
            chrom.Y[cust_0based, day] = 1

    # Ensure every customer has at least one delivery
    for i in range(n):
        if np.sum(chrom.Y[i, :]) == 0:
            day = int(np.argmax(inst.demand[i, :]))
            chrom.Y[i, day] = 1

    # --- Phase 2: Shift-aware load balancing (multi-pass) ---
    # Estimate max customers per route from TW width and travel times
    avg_inter_dist = np.mean(inst.dist[1:, 1:][
        inst.dist[1:, 1:] > 0
    ]) if n > 1 else 5.0
    avg_depot_dist = np.mean(inst.dist[0, 1:]) if n > 0 else 5.0
    avg_travel = avg_inter_dist / 18.0  # conservative speed estimate
    depot_travel = avg_depot_dist / 18.0
    tw_width = 4.0  # typical [8-12] or [14-18]
    usable_time = max(tw_width - 2 * depot_travel, 1.0)  # depot→first + last→depot
    per_stop_time = np.mean(inst.s) + avg_travel
    max_per_route = max(2, int(usable_time / per_stop_time) - 1)
    max_per_shift = m * max_per_route

    I_matrix, _ = simulate_inventory(chrom.Y, inst)

    # Multiple passes — shifting customers can overload adjacent days
    for _pass in range(3):
        any_moved = False
        for t in range(T):
            for is_morning in [True, False]:
                shift_custs = [
                    c for c in range(n)
                    if chrom.Y[c, t] == 1
                    and (inst.e[c] < 13.0) == is_morning
                ]

                if len(shift_custs) <= max_per_shift:
                    continue

                # Sort by inventory surplus (descending) — defer those with most buffer
                surplus = np.array([
                    (I_matrix[c, t - 1] if t > 0 else inst.I0[c])
                    - inst.demand[c, t] - inst.L_min[c]
                    for c in shift_custs
                ])
                order = np.argsort(-surplus)

                for idx in order:
                    # Recount current shift load
                    current_load = sum(
                        1 for c in range(n)
                        if chrom.Y[c, t] == 1
                        and (inst.e[c] < 13.0) == is_morning
                    )
                    if current_load <= max_per_shift:
                        break

                    c = shift_custs[idx]

                    # Try shifting to adjacent day
                    for dt in [1, -1, 2, -2]:
                        t_new = t + dt
                        if t_new < 0 or t_new >= T:
                            continue
                        if chrom.Y[c, t_new] == 1:
                            continue

                        # Test move
                        chrom.Y[c, t] = 0
                        chrom.Y[c, t_new] = 1
                        I_test, _ = simulate_inventory(chrom.Y, inst)
                        test_violations = check_feasibility(I_test, inst)

                        if not test_violations:
                            I_matrix = I_test  # accept
                            any_moved = True
                            break
                        else:
                            # Revert
                            chrom.Y[c, t] = 1
                            chrom.Y[c, t_new] = 0

        if not any_moved:
            break

    chrom._fitness = None
