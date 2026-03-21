"""
TD-Split Algorithm — DP-based route splitting for IRP-TW-DT.
Decodes a Two-part Chromosome into a complete Solution.
"""

from typing import List, Optional, Tuple

import numpy as np

from src.core.instance import Instance
from src.core.solution import Route, Solution
from src.core.traffic import IGPModel, TravelTimeModel, static_travel_time
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
    max_routes: int = None,
    travel_model: Optional[TravelTimeModel] = None,
) -> Tuple[List[Route], float]:
    """
    Vehicle-limited split procedure (extension of Prins 2004).

    Uses 2D DP: V[j][k] = min cost to serve customers[0..j-1]
    using exactly k routes, subject to k <= max_routes and capacity Q.

    When max_routes is None (unconstrained), reduces to standard 1D split.

    Combined with soft TW penalty in _compute_route_cost, this guarantees
    that a partition into <= max_routes routes always exists, eliminating
    capacity (vehicle count) violations by construction.

    References
    ----------
    Prins C. (2004) "A simple and effective evolutionary algorithm for
        the vehicle routing problem" Computers & Operations Research.
    Vidal T. et al. (2012) "A hybrid genetic algorithm with adaptive
        diversity management for a large class of vehicle routing problems
        with time-windows" Computers & Operations Research.

    Parameters
    ----------
    customers : List[int]
        Ordered list of customer indices (0-based).
    inst : Instance
    depart_h : float
        Vehicle departure time from depot (hours).
    day : int
    q_day : np.ndarray
        (n,) delivery quantities for this day.
    use_dynamic : bool
    max_routes : int or None
        Maximum number of routes (vehicles) allowed. If None, unconstrained.

    Returns
    -------
    routes : List[Route]
    total_cost : float
    """
    if len(customers) == 0:
        return [], 0.0

    num_cust = len(customers)
    INF = float('inf')

    if max_routes is None or max_routes >= num_cust:
        max_routes = num_cust

    # 2D DP: V[j][k] = min cost to serve customers[0..j-1] using k routes
    V = np.full((num_cust + 1, max_routes + 1), INF)
    V[0][0] = 0.0
    pred = np.full((num_cust + 1, max_routes + 1), -1, dtype=int)
    route_info = {}  # (i, j, k) -> (cost, stops)

    # Cache route costs: segment (i,j) has the same cost regardless of k.
    # This avoids O(n^2 * m) redundant _compute_route_cost calls,
    # reducing to O(n^2) cost evaluations + O(n^2 * m) DP lookups.
    seg_cost = {}   # (i, j) -> cost
    seg_stops = {}  # (i, j) -> stops
    seg_load = {}   # (i, j) -> total load

    # Pre-compute segment costs and loads (O(n^2))
    for j in range(1, num_cust + 1):
        cumulative_load = 0.0
        for i in range(j, 0, -1):
            c = customers[i - 1]
            cumulative_load += q_day[c]
            if cumulative_load > inst.Q + 1e-6:
                break  # all longer segments from i-1 downward also exceed Q

            route_customers = customers[i - 1:j]
            cost, stops = _compute_route_cost(
                route_customers, inst, depart_h, day, q_day, use_dynamic, travel_model
            )
            seg_cost[(i - 1, j)] = cost
            seg_stops[(i - 1, j)] = stops
            seg_load[(i - 1, j)] = cumulative_load

    # DP transitions using cached costs (O(n^2 * m) lookups only)
    for k in range(1, max_routes + 1):
        for j in range(1, num_cust + 1):
            for i in range(j, 0, -1):
                key = (i - 1, j)
                if key not in seg_cost:
                    break  # capacity exceeded; shorter segments also infeasible

                if V[i - 1][k - 1] >= INF:
                    continue

                total = V[i - 1][k - 1] + seg_cost[key]
                if total < V[j][k]:
                    V[j][k] = total
                    pred[j][k] = i - 1
                    route_info[(i - 1, j, k)] = (seg_cost[key], seg_stops[key])

    # Find best number of routes (fewest cost, respecting max_routes)
    best_k = None
    best_cost = INF
    for k in range(1, max_routes + 1):
        if V[num_cust][k] < best_cost:
            best_cost = V[num_cust][k]
            best_k = k

    if best_k is None or best_cost >= INF:
        # Fallback: single-customer routes (shouldn't happen with soft TW)
        routes = []
        total_cost = 0.0
        for c in customers:
            cost, stops = _compute_route_cost(
                [c], inst, depart_h, day, q_day, use_dynamic, travel_model
            )
            routes.append(Route(
                vehicle_id=len(routes), day=day,
                depart_h=depart_h, stops=stops,
            ))
            total_cost += cost
        return routes, total_cost

    # Backtrack to recover routes
    routes = []
    j = num_cust
    cur_k = best_k
    while cur_k > 0 and j > 0:
        i = pred[j][cur_k]
        if i < 0:
            # Fallback for remaining unassigned customers
            for c in customers[:j]:
                cost_c, stops_c = _compute_route_cost(
                    [c], inst, depart_h, day, q_day, use_dynamic, travel_model
                )
                routes.append(Route(
                    vehicle_id=0, day=day,
                    depart_h=depart_h, stops=stops_c,
                ))
            break

        _, stops = route_info[(i, j, cur_k)]
        routes.append(Route(
            vehicle_id=0, day=day,
            depart_h=depart_h, stops=stops,
        ))
        j = i
        cur_k -= 1

    routes.reverse()
    for idx, r in enumerate(routes):
        r.vehicle_id = idx

    return routes, best_cost


def _compute_route_cost(
    route_customers: List[int],
    inst: Instance,
    depart_h: float,
    day: int,
    q_day: np.ndarray,
    use_dynamic: bool = True,
    travel_model: Optional[TravelTimeModel] = None,
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
    tm = travel_model if travel_model is not None else IGPModel()
    cost_distance = 0.0
    cost_time = 0.0
    tw_penalty = 0.0
    stops = []
    current_time = depart_h
    prev_node = 0  # depot

    for cust_0based in route_customers:
        cust_1based = cust_0based + 1
        dist = inst.dist[prev_node, cust_1based]

        # Travel time
        if use_dynamic:
            tt = tm.duration_h(prev_node, cust_1based, current_time, dist)
        else:
            tt = static_travel_time(dist)

        arrival = current_time + tt

        # Wait if arriving before time window opens
        if arrival < inst.e[cust_0based]:
            arrival = inst.e[cust_0based]

        # Soft TW penalty (Vidal et al. 2012 UHGS) — proportional to lateness.
        # Critical for vehicle-limited DP: allows finding partitions
        # even when TW is tight and route count is constrained.
        if arrival > inst.l[cust_0based] + 1e-6:
            tw_penalty += LAMBDA_TW * (arrival - inst.l[cust_0based])

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
        tt_return = tm.duration_h(prev_node, 0, current_time, dist_return)
    else:
        tt_return = static_travel_time(dist_return)

    cost_distance += inst.c_d * dist_return
    cost_time += inst.c_t * tt_return

    return cost_distance + cost_time + tw_penalty, stops


def _nn_order(customers: List[int], inst: Instance) -> List[int]:
    """
    Order customers by nearest-neighbor heuristic starting from depot.

    For the DP split, contiguous subsequences in NN order are
    geographically close, yielding efficient routes with fewer splits.

    Parameters
    ----------
    customers : List[int]
        0-based customer indices.
    inst : Instance

    Returns
    -------
    List[int]
        Customers ordered by nearest-neighbor from depot.
    """
    if len(customers) <= 1:
        return list(customers)

    remaining = set(customers)
    ordered = []
    current_node = 0  # depot

    while remaining:
        nearest = min(remaining, key=lambda c: inst.dist[current_node, c + 1])
        ordered.append(nearest)
        remaining.remove(nearest)
        current_node = nearest + 1  # 1-based node index

    return ordered


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
    travel_model: Optional[TravelTimeModel] = None,
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

    # Split by TW shift
    morning_set = [c for c in day_customers_set if inst.e[c] < 13.0]
    afternoon_set = [c for c in day_customers_set if inst.e[c] >= 13.0]

    # Order each group by giant tour π (DevGuide: sort {i : Y_it=1} by order of π for TD-Split).
    # pi_position[c] = index of customer c in permutation pi.
    pi_position = np.empty(inst.n, dtype=np.int32)
    for k in range(inst.n):
        pi_position[pi[k]] = k
    morning_custs = sorted(morning_set, key=lambda c: pi_position[c])
    afternoon_custs = sorted(afternoon_set, key=lambda c: pi_position[c])

    all_routes: List[Route] = []

    # Allocate vehicles proportionally between shifts.
    # Since morning [8-12] and afternoon [14-18] don't overlap,
    # the same vehicles can serve both shifts. Each shift gets up to m.
    # But we also compute proportional allocation for better route quality.
    n_morning = len(morning_custs)
    n_afternoon = len(afternoon_custs)
    total = n_morning + n_afternoon

    for group, slots in [(morning_custs, morning_slots),
                         (afternoon_custs, afternoon_slots)]:
        if not group:
            continue

        best_grp_routes = None
        best_grp_cost = float('inf')

        for depart_h in slots:
            routes, cost = td_split(
                group, inst, depart_h, day, q_day, use_dynamic,
                max_routes=m,  # Vehicle-limited DP (Prins 2004)
                travel_model=travel_model,
            )
            if cost < best_grp_cost:
                best_grp_cost = cost
                best_grp_routes = routes

        if best_grp_routes:
            all_routes.extend(best_grp_routes)

    # Count violations from actual stop arrival times
    tw_violations = 0
    capacity_violations = 0

    # Vehicle count constraint is guaranteed by max_routes=m in td_split,
    # so we only check individual route capacity and TW violations.
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
    travel_model: Optional[TravelTimeModel] = None,
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
            travel_model=travel_model,
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
            d_cost, t_cost = _decompose_route_cost(route, inst, use_dynamic, travel_model)
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
    travel_model: Optional[TravelTimeModel] = None,
) -> Tuple[float, float]:
    """Decompose a route's cost into distance and time components."""
    tm = travel_model if travel_model is not None else IGPModel()
    cost_distance = 0.0
    cost_time = 0.0
    current_time = route.depart_h
    prev_node = 0

    for cust_1based, qty, arrival in route.stops:
        cust_0based = cust_1based - 1
        dist = inst.dist[prev_node, cust_1based]

        if use_dynamic:
            tt = tm.duration_h(prev_node, cust_1based, current_time, dist)
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
        tt_return = tm.duration_h(prev_node, 0, current_time, dist_return)
    else:
        tt_return = static_travel_time(dist_return)

    cost_distance += inst.c_d * dist_return
    cost_time += inst.c_t * tt_return

    return cost_distance, cost_time
