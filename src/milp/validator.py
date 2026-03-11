"""
MILP Lower Bound Validator for IRP-TW-DT.
Uses HiGHS solver via highspy for small instances (n≤10, T=3).
Precomputes travel times for 3 fixed departure slots.
"""

import logging
from typing import Tuple, Optional

import numpy as np

logger = logging.getLogger(__name__)

try:
    import highspy
    HAS_HIGHS = True
except ImportError:
    HAS_HIGHS = False
    logger.warning("highspy not installed. MILP validation disabled.")

from src.core.instance import Instance
from src.core.solution import Solution
from src.core.traffic import precompute_static_travel_time_matrix
from src.core.constants import DEPARTURE_SLOTS, STATIC_SPEED


def build_and_solve_milp(
    inst: Instance,
    time_limit: float = 600.0,
) -> Tuple[Optional[float], Optional[str]]:
    """
    Build and solve MILP lower bound for small instances.

    Uses static travel times (constant speed) for linearization.
    Only suitable for n ≤ 10, T ≤ 3.

    Parameters
    ----------
    inst : Instance
    time_limit : float
        Solver time limit in seconds.

    Returns
    -------
    (lower_bound, status) : Tuple[Optional[float], Optional[str]]
        Lower bound value and solver status.
    """
    if not HAS_HIGHS:
        logger.error("highspy not available. Install with: pip install highspy")
        return None, "highspy not installed"

    n, T, m = inst.n, inst.T, inst.m
    N = n + 1  # Including depot

    # Precompute travel times with static speed
    tt_matrix = precompute_static_travel_time_matrix(inst.dist, STATIC_SPEED)

    h = highspy.Highs()
    h.setOptionValue("time_limit", time_limit)
    h.setOptionValue("output_flag", False)

    # Decision variables
    # x[i,j,k,t] - binary routing
    # z[i,k,t] - binary visit
    # q[i,k,t] - continuous delivery quantity
    # I[i,t] - continuous inventory
    # w[i,k,t] - continuous arrival time

    # Variable indices
    var_count = 0
    x_idx = {}  # (i, j, k, t) -> var_index
    z_idx = {}  # (i, k, t) -> var_index
    q_idx = {}  # (i, k, t) -> var_index
    I_idx = {}  # (i, t) -> var_index
    w_idx = {}  # (i, k, t) -> var_index

    # Create x variables (binary)
    for i in range(N):
        for j in range(N):
            if i == j:
                continue
            for k in range(m):
                for t in range(T):
                    x_idx[(i, j, k, t)] = var_count
                    h.addVar(0, 1)
                    h.changeColIntegrality(var_count, highspy.HighsIntegrality.kInteger)
                    var_count += 1

    # Create z variables (binary)
    for i in range(1, N):
        for k in range(m):
            for t in range(T):
                z_idx[(i, k, t)] = var_count
                h.addVar(0, 1)
                h.changeColIntegrality(var_count, highspy.HighsIntegrality.kInteger)
                var_count += 1

    # Create q variables (continuous)
    for i in range(1, N):
        for k in range(m):
            for t in range(T):
                q_idx[(i, k, t)] = var_count
                h.addVar(0, inst.Q)
                var_count += 1

    # Create I variables (continuous)
    for i in range(1, N):
        for t in range(T):
            I_idx[(i, t)] = var_count
            ci = i - 1  # customer 0-based
            h.addVar(inst.L_min[ci], inst.U[ci])
            var_count += 1

    # Create w variables (continuous, arrival time)
    for i in range(N):
        for k in range(m):
            for t in range(T):
                w_idx[(i, k, t)] = var_count
                h.addVar(0, 24.0)
                var_count += 1

    # Objective: minimize inventory + distance + time cost
    obj = np.zeros(var_count)

    # Inventory holding cost
    for i in range(1, N):
        ci = i - 1
        for t in range(T):
            obj[I_idx[(i, t)]] = inst.h[ci]

    # Distance cost
    for (i, j, k, t), idx in x_idx.items():
        obj[idx] += inst.c_d * inst.dist[i, j]

    # Time cost (static)
    for (i, j, k, t), idx in x_idx.items():
        obj[idx] += inst.c_t * tt_matrix[i, j]

    h.changeObjectiveSense(highspy.ObjSense.kMinimize)
    for v in range(var_count):
        h.changeColCost(v, obj[v])

    BIG_M = 24.0

    # Constraints
    # C1: Inventory balance
    for i in range(1, N):
        ci = i - 1
        for t in range(T):
            indices = [I_idx[(i, t)]]
            values = [1.0]

            if t > 0:
                indices.append(I_idx[(i, t - 1)])
                values.append(-1.0)

            for k in range(m):
                indices.append(q_idx[(i, k, t)])
                values.append(-1.0)

            rhs = -inst.demand[ci, t]
            if t == 0:
                rhs += inst.I0[ci]

            h.addRow(rhs, rhs, len(indices), indices, values)

    # C3: Order-up-to linking q with z
    for i in range(1, N):
        ci = i - 1
        for k in range(m):
            for t in range(T):
                indices = [q_idx[(i, k, t)], z_idx[(i, k, t)]]
                values = [1.0, -inst.U[ci]]
                h.addRow(-highspy.kHighsInf, 0, 2, indices, values)

    # C4: Capacity
    for k in range(m):
        for t in range(T):
            indices = [q_idx[(i, k, t)] for i in range(1, N)]
            values = [1.0] * n
            h.addRow(-highspy.kHighsInf, inst.Q, len(indices), indices, values)

    # C5-C6: Flow conservation for customers
    for i in range(1, N):
        for k in range(m):
            for t in range(T):
                # Out-flow = z
                out_idx = [x_idx[(i, j, k, t)] for j in range(N) if j != i]
                out_val = [1.0] * len(out_idx)
                out_idx.append(z_idx[(i, k, t)])
                out_val.append(-1.0)
                h.addRow(0, 0, len(out_idx), out_idx, out_val)

                # In-flow = z
                in_idx = [x_idx[(j, i, k, t)] for j in range(N) if j != i]
                in_val = [1.0] * len(in_idx)
                in_idx.append(z_idx[(i, k, t)])
                in_val.append(-1.0)
                h.addRow(0, 0, len(in_idx), in_idx, in_val)

    # C7: Depot departure ≤ 1
    for k in range(m):
        for t in range(T):
            indices = [x_idx[(0, j, k, t)] for j in range(1, N)]
            values = [1.0] * len(indices)
            h.addRow(-highspy.kHighsInf, 1, len(indices), indices, values)

    # C8: Time propagation (MTZ-like)
    for i in range(N):
        for j in range(1, N):
            if i == j:
                continue
            ci = i - 1 if i > 0 else -1
            service = inst.s[ci] if i > 0 else 0.0
            for k in range(m):
                for t in range(T):
                    # w[j,k,t] >= w[i,k,t] + s_i + tt[i,j] - M(1-x[i,j,k,t])
                    indices = [
                        w_idx[(j, k, t)],
                        w_idx[(i, k, t)],
                        x_idx[(i, j, k, t)],
                    ]
                    values = [1.0, -1.0, -BIG_M]
                    rhs = service + tt_matrix[i, j] - BIG_M
                    h.addRow(rhs, highspy.kHighsInf, 3, indices, values)

    # C9-C10: Time windows
    for i in range(1, N):
        ci = i - 1
        for k in range(m):
            for t in range(T):
                # w[i,k,t] >= e_i * z[i,k,t]
                indices = [w_idx[(i, k, t)], z_idx[(i, k, t)]]
                values = [1.0, -inst.e[ci]]
                h.addRow(0, highspy.kHighsInf, 2, indices, values)

                # w[i,k,t] <= l_i * z[i,k,t] + M(1-z[i,k,t])
                indices = [w_idx[(i, k, t)], z_idx[(i, k, t)]]
                values = [1.0, -(inst.l[ci] + BIG_M)]
                h.addRow(-highspy.kHighsInf, BIG_M, 2, indices, values)

    # Solve
    logger.info(f"MILP: {var_count} variables, solving...")
    status = h.run()
    info = h.getInfoValue("mip_gap")

    model_status = h.getModelStatus()
    if model_status == highspy.HighsModelStatus.kOptimal:
        obj_val = h.getInfoValue("objective_function_value")
        logger.info(f"MILP optimal: {obj_val:.0f}")
        return obj_val, "optimal"
    elif model_status == highspy.HighsModelStatus.kObjectiveBound:
        obj_val = h.getInfoValue("objective_function_value")
        logger.info(f"MILP bound: {obj_val:.0f}")
        return obj_val, "bound"
    else:
        logger.warning(f"MILP status: {model_status}")
        try:
            obj_val = h.getInfoValue("objective_function_value")
            return obj_val, str(model_status)
        except Exception:
            return None, str(model_status)


def compute_gap(hga_cost: float, milp_lb: float) -> float:
    """
    Compute optimality gap percentage.

    gap = (hga - milp) / milp * 100
    """
    if milp_lb is None or milp_lb <= 0:
        return float('inf')
    return (hga_cost - milp_lb) / milp_lb * 100.0
