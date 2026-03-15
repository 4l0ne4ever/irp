"""
Scenario P — Periodic Delivery Baseline.
Fixed delivery every 3 days to all customers, nearest-neighbor routing, constant speed.
"""

from typing import List

import numpy as np

from src.core.instance import Instance
from src.core.solution import Route, Solution
from src.core.traffic import static_travel_time
from src.core.inventory import simulate_inventory, compute_inventory_cost, check_feasibility
from src.core.constants import STATIC_SPEED, LAMBDA_STOCKOUT


def solve_periodic(inst: Instance, period: int = 3) -> Solution:
    """
    Solve Scenario P: deliver to ALL customers every `period` days.

    Uses nearest-neighbor heuristic for routing and constant speed.

    Parameters
    ----------
    inst : Instance
    period : int
        Delivery period in days (default 3).

    Returns
    -------
    Solution
    """
    n, T, m = inst.n, inst.T, inst.m

    # Build allocation matrix: deliver on days 0, 3, 6, ...
    Y = np.zeros((n, T), dtype=np.int32)
    for t in range(T):
        if t % period == 0:
            Y[:, t] = 1

    # Simulate inventory
    I_matrix, q_matrix = simulate_inventory(Y, inst)

    # Build routes using nearest-neighbor for each delivery day
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

            # Accumulate costs
            prev_node = 0
            for cust_1based, _, _ in route.stops:
                dist = inst.dist[prev_node, cust_1based]
                tt = static_travel_time(dist, STATIC_SPEED)
                total_dist_cost += inst.c_d * dist
                total_time_cost += inst.c_t * tt
                prev_node = cust_1based
            # Return
            dist = inst.dist[prev_node, 0]
            tt = static_travel_time(dist, STATIC_SPEED)
            total_dist_cost += inst.c_d * dist
            total_time_cost += inst.c_t * tt

    cost_inventory = compute_inventory_cost(I_matrix, inst)
    violations = check_feasibility(I_matrix, inst)

    # P1: Flag when baseline uses more than m vehicles on any day
    vehicle_violations = sum(max(0, len(day_routes) - m) for day_routes in schedule)

    return Solution(
        schedule=schedule,
        cost_inventory=cost_inventory,
        cost_distance=total_dist_cost,
        cost_time=total_time_cost,
        feasible=(len(violations) == 0 and total_tw_violations == 0 and vehicle_violations == 0),
        tw_violations=total_tw_violations,
        stockout_violations=len(violations),
        capacity_violations=0,
        vehicle_violations=vehicle_violations,
        penalty_stockout=LAMBDA_STOCKOUT * len(violations),
        inventory_trace=I_matrix,
        delivery_matrix=q_matrix,
    )


def _nn_routing(
    customers: List[int],
    inst: Instance,
    day: int,
    q_day: np.ndarray,
    depart_h: float = 9.0,
) -> List[Route]:
    """
    Nearest-neighbor routing with capacity splitting.

    Parameters
    ----------
    customers : List[int]
        0-based customer indices to visit.
    inst : Instance
    day : int
    q_day : np.ndarray
    depart_h : float

    Returns
    -------
    List[Route]
    """
    routes = []
    remaining = set(customers)
    vehicle_id = 0

    while remaining:
        route_stops = []
        route_load = 0.0
        current_node = 0  # depot
        current_time = depart_h

        unvisited = set(remaining)
        while unvisited:
            # Find nearest unvisited customer
            best_cust = None
            best_dist = float('inf')
            for c in unvisited:
                c_node = c + 1
                d = inst.dist[current_node, c_node]
                if d < best_dist:
                    best_dist = d
                    best_cust = c

            if best_cust is None:
                break

            # Check capacity
            if route_load + q_day[best_cust] > inst.Q + 1e-6:
                break

            # Travel
            c_node = best_cust + 1
            tt = static_travel_time(best_dist, STATIC_SPEED)
            arrival = current_time + tt

            # Wait if early
            if arrival < inst.e[best_cust]:
                arrival = inst.e[best_cust]

            route_stops.append((c_node, q_day[best_cust], arrival))
            route_load += q_day[best_cust]
            current_time = arrival + inst.s[best_cust]
            current_node = c_node
            unvisited.discard(best_cust)
            remaining.discard(best_cust)

        if route_stops:
            routes.append(Route(
                vehicle_id=vehicle_id,
                day=day,
                depart_h=depart_h,
                stops=route_stops,
            ))
            vehicle_id += 1

    return routes
