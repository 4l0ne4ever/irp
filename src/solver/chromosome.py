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
    Y = np.zeros((n, T), dtype=np.int32)

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
                # Only add if there's room in warehouse
                if I[i] < inst.U[i] * 0.8:
                    Y[i, t] = 1
                    I[i] = inst.U[i]

    # Ensure every customer gets at least one delivery
    for i in range(n):
        if np.sum(Y[i, :]) == 0:
            # Deliver on day 0
            Y[i, 0] = 1

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
