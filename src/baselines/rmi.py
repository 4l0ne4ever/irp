"""
Scenario A — Retailer Managed Inventory (RMI) Baseline.
Reactive delivery: deliver next day when stock drops below safety level.
Uses CVRPTW nearest-neighbor routing, constant speed.
"""

from typing import List

import numpy as np

from src.core.instance import Instance
from src.core.solution import Route, Solution
from src.core.traffic import static_travel_time
from src.core.inventory import simulate_inventory, compute_inventory_cost, check_feasibility
from src.core.constants import STATIC_SPEED, LAMBDA_STOCKOUT
from src.baselines.periodic import _nn_routing


def solve_rmi(inst: Instance) -> Solution:
    """
    Solve Scenario A: Retailer Managed Inventory.

    Strategy: At end of each day, if customer i's projected inventory for
    tomorrow (after consuming demand) would drop below L_min, deliver
    on the next day.

    Parameters
    ----------
    inst : Instance

    Returns
    -------
    Solution
    """
    n, T = inst.n, inst.T

    # Build allocation matrix reactively
    Y = np.zeros((n, T), dtype=np.int32)

    I = inst.I0.copy()
    for t in range(T):
        # Consume demand
        I_after = I - inst.demand[:, t]

        # Check who needs delivery TODAY (determined yesterday or at start)
        # We deliver today if projected stock is below safety
        for i in range(n):
            if I_after[i] < inst.L_min[i]:
                Y[i, t] = 1

        # Update inventory
        for i in range(n):
            if Y[i, t] == 1:
                # Order-up-to
                I[i] = inst.U[i]
            else:
                I[i] = I_after[i]

    # Now simulate properly to get exact quantities
    I_matrix, q_matrix = simulate_inventory(Y, inst)

    # Build routes for each day using nearest-neighbor
    schedule = []
    total_dist_cost = 0.0
    total_time_cost = 0.0
    total_tw_violations = 0

    for t in range(T):
        day_customers = list(np.where(Y[:, t] == 1)[0])
        if not day_customers:
            schedule.append([])
            continue

        # Split customers by time window for feasible routing
        morning_custs = [c for c in day_customers if inst.e[c] < 13.0]
        afternoon_custs = [c for c in day_customers if inst.e[c] >= 13.0]

        all_routes = []
        if morning_custs:
            all_routes.extend(_nn_routing(morning_custs, inst, t, q_matrix[:, t],
                                          depart_h=7.0))
        if afternoon_custs:
            all_routes.extend(_nn_routing(afternoon_custs, inst, t, q_matrix[:, t],
                                          depart_h=13.0))

        schedule.append(all_routes)

        for route in all_routes:
            for stop in route.stops:
                cust_0based = stop[0] - 1
                if stop[2] > inst.l[cust_0based] + 1e-6:
                    total_tw_violations += 1

            prev_node = 0
            for cust_1based, _, _ in route.stops:
                dist = inst.dist[prev_node, cust_1based]
                tt = static_travel_time(dist, STATIC_SPEED)
                total_dist_cost += inst.c_d * dist
                total_time_cost += inst.c_t * tt
                prev_node = cust_1based
            dist = inst.dist[prev_node, 0]
            tt = static_travel_time(dist, STATIC_SPEED)
            total_dist_cost += inst.c_d * dist
            total_time_cost += inst.c_t * tt

    cost_inventory = compute_inventory_cost(I_matrix, inst)
    violations = check_feasibility(I_matrix, inst)

    return Solution(
        schedule=schedule,
        cost_inventory=cost_inventory,
        cost_distance=total_dist_cost,
        cost_time=total_time_cost,
        feasible=(len(violations) == 0 and total_tw_violations == 0),
        tw_violations=total_tw_violations,
        stockout_violations=len(violations),
        capacity_violations=0,
        penalty_stockout=LAMBDA_STOCKOUT * len(violations),
        inventory_trace=I_matrix,
        delivery_matrix=q_matrix,
    )
