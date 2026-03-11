"""
Fitness evaluation for IRP-TW-DT.
Computes total cost + penalties for a chromosome.
"""

from typing import Tuple

import numpy as np

from src.core.instance import Instance
from src.core.solution import Solution
from src.core.constants import LAMBDA_STOCKOUT, LAMBDA_CAPACITY, LAMBDA_TW
from .chromosome import Chromosome
from .decode import decode_chromosome


def evaluate(
    chrom: Chromosome,
    inst: Instance,
    use_dynamic: bool = True,
) -> Tuple[float, Solution]:
    """
    Evaluate a chromosome: decode and compute fitness.

    Fitness = Total Cost + Penalties
    Feasible solutions always beat infeasible ones.

    Parameters
    ----------
    chrom : Chromosome
    inst : Instance
    use_dynamic : bool
        Use dynamic traffic model (True for scenario C).

    Returns
    -------
    fitness : float
    solution : Solution
    """
    sol = decode_chromosome(chrom, inst, use_dynamic=use_dynamic)

    fitness = sol.total_cost + sol.total_penalty
    chrom._fitness = fitness

    return fitness, sol


def compute_penalties(sol: Solution) -> Tuple[float, float, float]:
    """
    Extract penalty components from a solution.

    Returns
    -------
    (P_stockout, P_capacity, P_tw) : Tuple[float, float, float]
    """
    return sol.penalty_stockout, sol.penalty_capacity, sol.penalty_tw


def is_feasible(sol: Solution) -> bool:
    """Check if solution is fully feasible (no violations)."""
    return sol.feasible


def compare_fitness(
    fitness_a: float, feasible_a: bool,
    fitness_b: float, feasible_b: bool,
) -> int:
    """
    Compare two solutions by fitness.
    Feasible always beats infeasible.

    Returns
    -------
    -1 if a is better, 1 if b is better, 0 if tie.
    """
    if feasible_a and not feasible_b:
        return -1
    if not feasible_a and feasible_b:
        return 1
    if fitness_a < fitness_b:
        return -1
    if fitness_a > fitness_b:
        return 1
    return 0
