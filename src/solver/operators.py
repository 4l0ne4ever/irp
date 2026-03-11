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
    Repair chromosome to ensure inventory feasibility.

    Forward-simulate inventory; whenever I[i,t] < L_min[i],
    force Y[i,t] = 1 (deliver on that day).

    Also ensures every customer gets at least one delivery.
    """
    n, T = inst.n, inst.T
    max_iterations = 3  # Bounded to prevent infinite loops

    for iteration in range(max_iterations):
        I_matrix, q_matrix = simulate_inventory(chrom.Y, inst)
        violations = check_feasibility(I_matrix, inst)

        if not violations:
            break

        for cust_0based, day in violations:
            chrom.Y[cust_0based, day] = 1

    # Ensure every customer has at least one delivery
    for i in range(n):
        if np.sum(chrom.Y[i, :]) == 0:
            # Find the day with highest demand
            day = int(np.argmax(inst.demand[i, :]))
            chrom.Y[i, day] = 1

    chrom._fitness = None
