"""
Inventory simulation for IRP-TW-DT.
Implements Order-Up-To (OU) policy and feasibility checking.
"""

from typing import List, Tuple

import numpy as np

from .instance import Instance


def simulate_inventory(
    Y: np.ndarray,
    inst: Instance
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Forward-simulate inventory levels given allocation matrix Y.

    Uses Order-Up-To (OU) policy: when Y[i,t]=1, deliver q[i,t] = U_i - I[i,t-1].

    Parameters
    ----------
    Y : np.ndarray
        Shape (n, T) binary allocation matrix. Y[i,t]=1 if customer i+1
        receives delivery on day t.
    inst : Instance
        Problem instance.

    Returns
    -------
    I_matrix : np.ndarray
        Shape (n, T) inventory levels at end of each day.
    q_matrix : np.ndarray
        Shape (n, T) delivery quantities.
    """
    n, T = inst.n, inst.T
    I_matrix = np.zeros((n, T))
    q_matrix = np.zeros((n, T))

    I_prev = inst.I0.copy()

    for t in range(T):
        # Compute delivery quantities (OU policy)
        q_matrix[:, t] = Y[:, t] * (inst.U - I_prev)

        # Ensure non-negative deliveries
        q_matrix[:, t] = np.maximum(q_matrix[:, t], 0.0)

        # Update inventory: I_t = I_{t-1} + q_t - d_t
        I_matrix[:, t] = I_prev + q_matrix[:, t] - inst.demand[:, t]

        I_prev = I_matrix[:, t].copy()

    return I_matrix, q_matrix


def check_feasibility(
    I_matrix: np.ndarray,
    inst: Instance
) -> List[Tuple[int, int]]:
    """
    Check inventory feasibility and return violations.

    Parameters
    ----------
    I_matrix : np.ndarray
        Shape (n, T) inventory levels at end of each day.
    inst : Instance
        Problem instance.

    Returns
    -------
    List[Tuple[int, int]]
        List of (customer_0based, day) pairs where stock-out occurs
        (I[i,t] < L_min[i]).
    """
    violations = []
    for i in range(inst.n):
        for t in range(inst.T):
            if I_matrix[i, t] < inst.L_min[i] - 1e-6:
                violations.append((i, t))
    return violations


def check_overstock(
    I_matrix: np.ndarray,
    inst: Instance
) -> List[Tuple[int, int]]:
    """Check where inventory exceeds capacity."""
    violations = []
    for i in range(inst.n):
        for t in range(inst.T):
            if I_matrix[i, t] > inst.U[i] + 1e-6:
                violations.append((i, t))
    return violations


def compute_inventory_cost(
    I_matrix: np.ndarray,
    inst: Instance
) -> float:
    """
    Compute total inventory holding cost.

    Parameters
    ----------
    I_matrix : np.ndarray
        Shape (n, T) inventory levels.
    inst : Instance
        Problem instance.

    Returns
    -------
    float
        Total inventory holding cost in VND.
    """
    # h[i] * I[i,t] summed over all customers and days
    return float(np.sum(inst.h[:, np.newaxis] * I_matrix))
