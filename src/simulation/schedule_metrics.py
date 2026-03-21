"""
Build Solution metrics from an explicit schedule (routes), without full chromosome decode.
Used after rolling-horizon merge to attach costs and inventory trace.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

import numpy as np

from src.core.constants import LAMBDA_CAPACITY, LAMBDA_STOCKOUT, LAMBDA_TW
from src.core.instance import Instance
from src.core.inventory import check_feasibility, compute_inventory_cost
from src.core.solution import Route, Solution
from src.core.traffic import IGPModel, TravelTimeModel
from src.solver.decode import _decompose_route_cost


def simulate_inventory_from_schedule(inst: Instance, schedule: List[List[Route]]) -> Tuple[np.ndarray, np.ndarray]:
    """Forward inventory using per-stop delivery quantities (sum per customer per day)."""
    n, T = inst.n, inst.T
    I_matrix = np.zeros((n, T))
    q_matrix = np.zeros((n, T))
    I = inst.I0.copy()
    for t in range(T):
        q_matrix[:, t] = 0.0
        for route in schedule[t]:
            for cust_1b, qty, _arr in route.stops:
                if qty > 0:
                    q_matrix[cust_1b - 1, t] += float(qty)
        I = I + q_matrix[:, t] - inst.demand[:, t]
        I_matrix[:, t] = I.copy()
    return I_matrix, q_matrix


def _count_tw_violations(inst: Instance, schedule: List[List[Route]]) -> int:
    n = 0
    for t in range(len(schedule)):
        for route in schedule[t]:
            for cust_1b, _q, arrival in route.stops:
                ci = cust_1b - 1
                if arrival < inst.e[ci] - 1e-5 or arrival > inst.l[ci] + 1e-5:
                    n += 1
    return n


def solution_from_schedule(
    inst: Instance,
    schedule: List[List[Route]],
    *,
    use_dynamic: bool,
    travel_model: Optional[TravelTimeModel] = None,
) -> Solution:
    """Aggregate costs and feasibility from explicit routes."""
    tm = travel_model if travel_model is not None else IGPModel()
    I_matrix, q_matrix = simulate_inventory_from_schedule(inst, schedule)
    cost_inventory = compute_inventory_cost(I_matrix, inst)
    cost_distance = 0.0
    cost_time = 0.0
    for t in range(len(schedule)):
        for route in schedule[t]:
            d_cost, t_cost = _decompose_route_cost(route, inst, use_dynamic, tm)
            cost_distance += d_cost
            cost_time += t_cost
    violations = check_feasibility(I_matrix, inst)
    stockout_violations = len(violations)
    tw_violations = _count_tw_violations(inst, schedule)
    cap_violations = 0
    for t in range(len(schedule)):
        for route in schedule[t]:
            if route.total_delivery > inst.Q + 1e-6:
                cap_violations += 1
    feasible = stockout_violations == 0 and tw_violations == 0 and cap_violations == 0
    return Solution(
        schedule=schedule,
        cost_inventory=cost_inventory,
        cost_distance=cost_distance,
        cost_time=cost_time,
        feasible=feasible,
        tw_violations=tw_violations,
        stockout_violations=stockout_violations,
        capacity_violations=cap_violations,
        penalty_stockout=LAMBDA_STOCKOUT * stockout_violations,
        penalty_capacity=LAMBDA_CAPACITY * cap_violations,
        penalty_tw=LAMBDA_TW * tw_violations,
        inventory_trace=I_matrix,
        delivery_matrix=q_matrix,
    )
