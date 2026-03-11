"""
TD-Split Algorithm — DP-based route splitting for IRP-TW-DT.
Decodes a Two-part Chromosome into a complete Solution.
"""

from typing import List, Tuple

import numpy as np

from src.core.instance import Instance
from src.core.solution import Route, Solution
from src.core.traffic import igp_travel_time, static_travel_time
from src.core.inventory import simulate_inventory, compute_inventory_cost
from src.core.constants import (
    DEPARTURE_SLOTS_MORNING, DEPARTURE_SLOTS_AFTERNOON,
    LAMBDA_STOCKOUT, LAMBDA_CAPACITY, LAMBDA_TW,
)
from .chromosome import Chromosome


def td_split(
    customers: List[int],
    inst: Instance,
    depart_h: float,
    day: int,
    q_day: np.ndarray,
    use_dynamic: bool = True,
) -> Tuple[List[Route], float]:
    """
    Split a sequence of customers into capacity-feasible routes using DP.

    Uses time-dependent travel time to compute accurate costs.

    Parameters
    ----------
    customers : List[int]
        Ordered list of customer indices (0-based into customer arrays).
        These are the customers to visit on this day, ordered by giant tour pi.
    inst : Instance
        Problem instance.
    depart_h : float
        Vehicle departure time from depot (hours).
    day : int
        Day index (0-based).
    q_day : np.ndarray
        (n,) delivery quantities for this day.
    use_dynamic : bool
        If True, use IGP travel time; if False, use static 18 km/h.

    Returns
    -------
    routes : List[Route]
        List of routes, each with stops and timing.
    total_cost : float
        Total routing cost (distance + time) for this day.
    """
    if len(customers) == 0:
        return [], 0.0

    num_cust = len(customers)
    INF = float('inf')

    # DP: V[j] = min cost to serve customers[0..j-1]
    # V[0] = 0 (no customers served)
    V = np.full(num_cust + 1, INF)
    V[0] = 0.0
    pred = np.full(num_cust + 1, -1, dtype=int)  # predecessor for backtracking

    # Store route info for reconstruction
    route_info = {}  # (i, j) -> (cost, stops_list)

    for j in range(1, num_cust + 1):
        for i in range(j, 0, -1):
            # Try route serving customers[i-1 .. j-1]
            route_customers = customers[i - 1:j]

            # Check capacity
            load = sum(q_day[c] for c in route_customers)
            if load > inst.Q + 1e-6:
                break  # Adding more customers will only increase load

            # Compute route cost with time propagation
            cost, stops = _compute_route_cost(
                route_customers, inst, depart_h, day, q_day, use_dynamic
            )

            if cost >= INF:
                continue

            total = V[i - 1] + cost
            if total < V[j]:
                V[j] = total
                pred[j] = i - 1
                route_info[(i - 1, j)] = (cost, stops)

    # Backtrack to recover routes
    routes = []
    j = num_cust
    vehicle_id = 0
    while j > 0:
        i = pred[j]
        if i < 0:
            # Fallback: single-customer routes for remaining
            for k in range(j):
                c = customers[k]
                _, stops = _compute_route_cost(
                    [c], inst, depart_h, day, q_day, use_dynamic
                )
                route = Route(
                    vehicle_id=vehicle_id, day=day,
                    depart_h=depart_h, stops=stops,
                )
                routes.append(route)
                vehicle_id += 1
            break

        _, stops = route_info[(i, j)]
        route = Route(
            vehicle_id=vehicle_id, day=day,
            depart_h=depart_h, stops=stops,
        )
        routes.append(route)
        vehicle_id += 1
        j = i

    routes.reverse()

    # Reassign vehicle IDs
    for idx, r in enumerate(routes):
        r.vehicle_id = idx

    total_cost = V[num_cust] if V[num_cust] < INF else 0.0
    return routes, total_cost


def _compute_route_cost(
    route_customers: List[int],
    inst: Instance,
    depart_h: float,
    day: int,
    q_day: np.ndarray,
    use_dynamic: bool = True,
) -> Tuple[float, List[Tuple[int, float, float]]]:
    """
    Compute the cost and stops for a single route with time propagation.

    Returns
    -------
    cost : float
        Distance cost + time cost for this route.
    stops : List[Tuple[int, float, float]]
        (customer_1based, delivery_qty, arrival_time) for each stop.
    """
    cost_distance = 0.0
    cost_time = 0.0
    stops = []
    current_time = depart_h
    prev_node = 0  # depot

    for cust_0based in route_customers:
        cust_1based = cust_0based + 1
        dist = inst.dist[prev_node, cust_1based]

        # Travel time
        if use_dynamic:
            tt = igp_travel_time(dist, current_time)
        else:
            tt = static_travel_time(dist)

        arrival = current_time + tt

        # Wait if arriving before time window opens
        if arrival < inst.e[cust_0based]:
            arrival = inst.e[cust_0based]

        # Record stop
        qty = q_day[cust_0based]
        stops.append((cust_1based, qty, arrival))

        # Accumulate costs
        cost_distance += inst.c_d * dist
        cost_time += inst.c_t * tt

        # Update time: arrival + service time
        current_time = arrival + inst.s[cust_0based]
        prev_node = cust_1based

    # Return to depot
    dist_return = inst.dist[prev_node, 0]
    if use_dynamic:
        tt_return = igp_travel_time(dist_return, current_time)
    else:
        tt_return = static_travel_time(dist_return)

    cost_distance += inst.c_d * dist_return
    cost_time += inst.c_t * tt_return

    return cost_distance + cost_time, stops


def _decode_day(
    pi: np.ndarray,
    Y_day: np.ndarray,
    inst: Instance,
    day: int,
    q_day: np.ndarray,
    morning_slots: List[float],
    afternoon_slots: List[float],
    use_dynamic: bool,
    m: int,
) -> Tuple[List[Route], int, int]:
    """
    Decode routing for a single day.

    Splits customers by TW into morning/afternoon groups, runs TD-Split
    with best departure slot per group.

    Parameters
    ----------
    pi : ndarray
        Giant tour permutation (0-based).
    Y_day : ndarray
        (n,) binary — who gets delivery today.
    inst, day, q_day, use_dynamic : as in td_split.
    morning_slots, afternoon_slots : departure slot candidates.
    m : int
        Number of vehicles.

    Returns
    -------
    routes : List[Route]
    tw_violations : int
    capacity_violations : int
    """
    visit_mask = Y_day == 1
    if not np.any(visit_mask):
        return [], 0, 0

    day_customers_set = set(np.where(visit_mask)[0])
    day_customers = [c for c in pi if c in day_customers_set]

    morning_custs = [c for c in day_customers if inst.e[c] < 13.0]
    afternoon_custs = [c for c in day_customers if inst.e[c] >= 13.0]

    all_routes: List[Route] = []
    n_morning_routes = 0
    n_afternoon_routes = 0

    for group, slots in [(morning_custs, morning_slots),
                         (afternoon_custs, afternoon_slots)]:
        if not group:
            continue

        best_grp_routes = None
        best_grp_cost = float('inf')

        for depart_h in slots:
            routes, cost = td_split(
                group, inst, depart_h, day, q_day, use_dynamic
            )
            if cost < best_grp_cost:
                best_grp_cost = cost
                best_grp_routes = routes

        if best_grp_routes:
            all_routes.extend(best_grp_routes)
            if group is morning_custs:
                n_morning_routes = len(best_grp_routes)
            else:
                n_afternoon_routes = len(best_grp_routes)

    # Count violations
    tw_violations = 0
    capacity_violations = 0

    max_concurrent = max(n_morning_routes, n_afternoon_routes) if all_routes else 0
    if max_concurrent > m:
        capacity_violations += max_concurrent - m

    for route in all_routes:
        if route.total_delivery > inst.Q + 1e-6:
            capacity_violations += 1
        for cust_1based, qty, arrival in route.stops:
            cust_0based = cust_1based - 1
            if arrival > inst.l[cust_0based] + 1e-6:
                tw_violations += 1

    return all_routes, tw_violations, capacity_violations


def decode_chromosome(
    chrom: Chromosome,
    inst: Instance,
    use_dynamic: bool = True,
) -> Solution:
    """
    Decode a Two-part Chromosome into a complete Solution.

    Steps:
    1. Simulate inventory to get delivery quantities.
    2. For each day, split customers by TW, run TD-Split with best departure slot.
    3. Aggregate costs and violations.

    Parameters
    ----------
    chrom : Chromosome
        Two-part chromosome (Y, pi).
    inst : Instance
        Problem instance.
    use_dynamic : bool
        Whether to use dynamic traffic (True for scenario C, False for B).

    Returns
    -------
    Solution
        Complete decoded solution.
    """
    from src.core.inventory import check_feasibility

    n, T, m = inst.n, inst.T, inst.m

    # Step 1: Simulate inventory
    I_matrix, q_matrix = simulate_inventory(chrom.Y, inst)

    # TW-aware departure slots
    if use_dynamic:
        morning_slots = DEPARTURE_SLOTS_MORNING
        afternoon_slots = DEPARTURE_SLOTS_AFTERNOON
    else:
        morning_slots = [8.0]
        afternoon_slots = [13.0]

    # Step 2: Decode each day
    schedule = []
    total_tw_violations = 0
    total_capacity_violations = 0

    for t in range(T):
        routes, tw_v, cap_v = _decode_day(
            chrom.pi, chrom.Y[:, t], inst, t, q_matrix[:, t],
            morning_slots, afternoon_slots, use_dynamic, m,
        )
        schedule.append(routes)
        total_tw_violations += tw_v
        total_capacity_violations += cap_v

    # Step 3: Compute costs
    cost_inventory = compute_inventory_cost(I_matrix, inst)

    cost_distance = 0.0
    cost_time = 0.0
    for t in range(T):
        for route in schedule[t]:
            d_cost, t_cost = _decompose_route_cost(route, inst, use_dynamic)
            cost_distance += d_cost
            cost_time += t_cost

    # Count stockout violations
    violations = check_feasibility(I_matrix, inst)
    stockout_violations = len(violations)

    sol = Solution(
        schedule=schedule,
        cost_inventory=cost_inventory,
        cost_distance=cost_distance,
        cost_time=cost_time,
        feasible=(stockout_violations == 0 and total_tw_violations == 0
                  and total_capacity_violations == 0),
        tw_violations=total_tw_violations,
        stockout_violations=stockout_violations,
        capacity_violations=total_capacity_violations,
        penalty_stockout=LAMBDA_STOCKOUT * stockout_violations,
        penalty_capacity=LAMBDA_CAPACITY * total_capacity_violations,
        penalty_tw=LAMBDA_TW * total_tw_violations,
        inventory_trace=I_matrix,
        delivery_matrix=q_matrix,
    )

    return sol


def _decompose_route_cost(
    route: Route,
    inst: Instance,
    use_dynamic: bool = True,
) -> Tuple[float, float]:
    """Decompose a route's cost into distance and time components."""
    cost_distance = 0.0
    cost_time = 0.0
    current_time = route.depart_h
    prev_node = 0

    for cust_1based, qty, arrival in route.stops:
        cust_0based = cust_1based - 1
        dist = inst.dist[prev_node, cust_1based]

        if use_dynamic:
            tt = igp_travel_time(dist, current_time)
        else:
            tt = static_travel_time(dist)

        cost_distance += inst.c_d * dist
        cost_time += inst.c_t * tt

        # Update time
        actual_arrival = current_time + tt
        if actual_arrival < inst.e[cust_0based]:
            actual_arrival = inst.e[cust_0based]
        current_time = actual_arrival + inst.s[cust_0based]
        prev_node = cust_1based

    # Return to depot
    dist_return = inst.dist[prev_node, 0]
    if use_dynamic:
        tt_return = igp_travel_time(dist_return, current_time)
    else:
        tt_return = static_travel_time(dist_return)

    cost_distance += inst.c_d * dist_return
    cost_time += inst.c_t * tt_return

    return cost_distance, cost_time
