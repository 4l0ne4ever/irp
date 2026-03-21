"""
Local Search operators for IRP-TW-DT.
- 2-opt: spatial improvement of routes
- Time-Shift: temporal improvement (shift delivery days)
"""

from typing import List, Optional

import numpy as np

from src.core.instance import Instance
from src.core.solution import Route, Solution
from src.core.traffic import TravelTimeModel
from src.core.inventory import simulate_inventory, check_feasibility, compute_inventory_cost
from src.core.constants import DEPARTURE_SLOTS_MORNING, DEPARTURE_SLOTS_AFTERNOON
from .chromosome import Chromosome, copy_chromosome
from .decode import decode_chromosome, _compute_route_cost, _decompose_route_cost, _decode_day


def _solution_to_pi(sol: Solution, n: int) -> np.ndarray:
    """
    Re-encode solution schedule into a giant-tour permutation π.
    Order = first occurrence of each customer across days (day, route, stop).
    Ensures 2-opt/Or-opt improvements are persisted to the genotype.
    """
    order: List[int] = []
    seen = set()
    for t in range(len(sol.schedule)):
        for route in sol.schedule[t]:
            for (cust_1based, _, _) in route.stops:
                c = cust_1based - 1
                if c not in seen:
                    seen.add(c)
                    order.append(c)
    order += [c for c in range(n) if c not in seen]
    return np.array(order, dtype=np.int32)


def two_opt_route(
    route: Route,
    inst: Instance,
    use_dynamic: bool = True,
    travel_model: Optional[TravelTimeModel] = None,
) -> Route:
    """
    Apply 2-opt improvement to a single route.

    Tries all pairs of edges, reverses segment if improvement found.
    Uses first-improvement strategy.
    Recomputes ALL travel times after each reversal (DevGuide §3.6).

    Parameters
    ----------
    route : Route
    inst : Instance
    use_dynamic : bool

    Returns
    -------
    Route
        Improved route (or original if no improvement).
    """
    if len(route.stops) <= 2:
        return route

    customers = [s[0] - 1 for s in route.stops]  # 0-based
    qty_dict = {s[0] - 1: s[1] for s in route.stops}
    n_stops = len(customers)

    # Pre-build q_day once for route evaluation
    q_day = np.zeros(inst.n)
    for c, q in qty_dict.items():
        q_day[c] = q

    best_order = customers[:]
    best_cost = _compute_route_cost(
        best_order, inst, route.depart_h, route.day, q_day, use_dynamic, travel_model
    )[0]
    improved = True

    while improved:
        improved = False
        for i in range(n_stops - 1):
            for j in range(i + 1, n_stops):
                new_order = best_order[:i] + best_order[i:j + 1][::-1] + best_order[j + 1:]
                new_cost = _compute_route_cost(
                    new_order, inst, route.depart_h, route.day, q_day, use_dynamic, travel_model
                )[0]

                if new_cost < best_cost - 1e-6:
                    best_order = new_order
                    best_cost = new_cost
                    improved = True
                    break
            if improved:
                break

    # Rebuild route with new order
    _, stops = _compute_route_cost(best_order, inst, route.depart_h, route.day, q_day, use_dynamic, travel_model)

    return Route(
        vehicle_id=route.vehicle_id,
        day=route.day,
        depart_h=route.depart_h,
        stops=stops,
    )


def or_opt_day(
    routes: List[Route],
    inst: Instance,
    use_dynamic: bool = True,
    travel_model: Optional[TravelTimeModel] = None,
) -> List[Route]:
    """
    Or-opt: relocate 1 or 2 consecutive customers between routes on the same day.

    For each pair of routes (r1, r2), try removing a segment of 1-2 customers
    from r1 and inserting into the best position in r2. Accept if total cost
    improves and both routes remain within capacity Q.

    Parameters
    ----------
    routes : List[Route]
    inst : Instance
    use_dynamic : bool

    Returns
    -------
    List[Route]
        Improved routes.
    """
    if len(routes) < 2:
        return routes

    improved = True
    while improved:
        improved = False
        for r1_idx in range(len(routes)):
            if improved:
                break
            r1 = routes[r1_idx]
            if len(r1.stops) <= 1:
                continue

            custs_1 = [s[0] - 1 for s in r1.stops]
            qty_1 = {s[0] - 1: s[1] for s in r1.stops}

            for r2_idx in range(len(routes)):
                if r1_idx == r2_idx:
                    continue
                if improved:
                    break

                r2 = routes[r2_idx]
                custs_2 = [s[0] - 1 for s in r2.stops]
                qty_2 = {s[0] - 1: s[1] for s in r2.stops}

                # Compute current costs
                q_day_1 = np.zeros(inst.n)
                for c, q in qty_1.items():
                    q_day_1[c] = q
                q_day_2 = np.zeros(inst.n)
                for c, q in qty_2.items():
                    q_day_2[c] = q

                cost_1, _ = _compute_route_cost(
                    custs_1, inst, r1.depart_h, r1.day, q_day_1, use_dynamic, travel_model)
                cost_2, _ = _compute_route_cost(
                    custs_2, inst, r2.depart_h, r2.day, q_day_2, use_dynamic, travel_model)
                old_total = cost_1 + cost_2

                # Try segment sizes 1 and 2
                for seg_len in [1, 2]:
                    if improved:
                        break
                    for ci in range(len(custs_1) - seg_len + 1):
                        segment = custs_1[ci:ci + seg_len]
                        seg_load = sum(qty_1[c] for c in segment)

                        # Check capacity of r2 after insertion
                        new_r2_load = sum(qty_2.values()) + seg_load
                        if new_r2_load > inst.Q + 1e-6:
                            continue

                        new_custs_1 = custs_1[:ci] + custs_1[ci + seg_len:]
                        if not new_custs_1:
                            continue

                        # Cost of r1 without segment
                        q_combined = np.zeros(inst.n)
                        for cc in new_custs_1:
                            q_combined[cc] = qty_1[cc]
                        new_cost_1, _ = _compute_route_cost(
                            new_custs_1, inst, r1.depart_h, r1.day, q_combined, use_dynamic, travel_model)

                        # Try all insertion positions in r2
                        best_new_cost_2 = float('inf')
                        best_new_stops = None
                        for pos in range(len(custs_2) + 1):
                            trial = custs_2[:pos] + segment + custs_2[pos:]
                            q_trial = np.zeros(inst.n)
                            for cc in trial:
                                q_trial[cc] = qty_2.get(cc, qty_1.get(cc, 0))
                            trial_cost, trial_stops = _compute_route_cost(
                                trial, inst, r2.depart_h, r2.day, q_trial, use_dynamic, travel_model)
                            if trial_cost < best_new_cost_2:
                                best_new_cost_2 = trial_cost
                                best_new_stops = trial_stops

                        new_total = new_cost_1 + best_new_cost_2
                        if new_total < old_total - 1e-6:
                            # Accept move
                            q_new_1 = np.zeros(inst.n)
                            for cc in new_custs_1:
                                q_new_1[cc] = qty_1[cc]
                            _, new_stops_1 = _compute_route_cost(
                                new_custs_1, inst, r1.depart_h, r1.day, q_new_1, use_dynamic, travel_model)

                            routes[r1_idx] = Route(
                                vehicle_id=r1.vehicle_id, day=r1.day,
                                depart_h=r1.depart_h, stops=new_stops_1)
                            routes[r2_idx] = Route(
                                vehicle_id=r2.vehicle_id, day=r2.day,
                                depart_h=r2.depart_h, stops=best_new_stops)
                            improved = True
                            break

    return routes


def time_shift(
    chrom: Chromosome,
    inst: Instance,
    use_dynamic: bool = True,
    rng: Optional[np.random.Generator] = None,
    travel_model: Optional[TravelTimeModel] = None,
) -> Chromosome:
    """
    Time-Shift Neighborhood Search — core contribution (DevGuide §3.6).

    Optimizes delivery schedule on the TIME AXIS by shifting customer i
    from day t to t±δ (δ ∈ {1,2}). Uses incremental evaluation:
    only recomputes routing for the two affected days (not full horizon).

    Parameters
    ----------
    chrom : Chromosome
    inst : Instance
    use_dynamic : bool
    rng : optional random generator

    Returns
    -------
    Chromosome
        Improved chromosome (copy of input).
    """
    best = copy_chromosome(chrom)
    n, T, m = inst.n, inst.T, inst.m

    # Departure slots for decoding
    if use_dynamic:
        morning_slots = DEPARTURE_SLOTS_MORNING
        afternoon_slots = DEPARTURE_SLOTS_AFTERNOON
    else:
        morning_slots = [8.0]
        afternoon_slots = [13.0]

    # Compute initial solution and cache per-day costs
    I_matrix, q_matrix = simulate_inventory(best.Y, inst)
    inv_cost = compute_inventory_cost(I_matrix, inst)

    day_dist = []
    day_time = []
    for t in range(T):
        routes, _, _ = _decode_day(
            best.pi, best.Y[:, t], inst, t, q_matrix[:, t],
            morning_slots, afternoon_slots, use_dynamic, m,
            travel_model=travel_model,
        )
        dc, tc = 0.0, 0.0
        for r in routes:
            d, tt = _decompose_route_cost(r, inst, use_dynamic, travel_model)
            dc += d
            tc += tt
        day_dist.append(dc)
        day_time.append(tc)

    total_dist = sum(day_dist)
    total_time = sum(day_time)
    best_fitness = inv_cost + total_dist + total_time

    # Iterate customers in random order
    order = np.arange(n)
    if rng is not None:
        rng.shuffle(order)

    for i in order:
        served_days = np.where(best.Y[i, :] == 1)[0]
        if len(served_days) == 0:
            continue

        improved_i = False
        for t in served_days:
            if improved_i:
                break
            for delta in [-2, -1, 1, 2]:
                t_new = t + delta
                if t_new < 0 or t_new >= T:
                    continue
                if best.Y[i, t_new] == 1:
                    continue

                # Create candidate
                candidate = copy_chromosome(best)
                candidate.Y[i, t] = 0
                candidate.Y[i, t_new] = 1

                # Check inventory feasibility
                cand_I, cand_q = simulate_inventory(candidate.Y, inst)
                violations = check_feasibility(cand_I, inst)
                if violations:
                    continue

                # Incremental eval: only re-decode 2 affected days
                routes_t, tw_t, cap_t = _decode_day(
                    candidate.pi, candidate.Y[:, t], inst, t, cand_q[:, t],
                    morning_slots, afternoon_slots, use_dynamic, m,
                    travel_model=travel_model,
                )
                routes_tn, tw_tn, cap_tn = _decode_day(
                    candidate.pi, candidate.Y[:, t_new], inst, t_new, cand_q[:, t_new],
                    morning_slots, afternoon_slots, use_dynamic, m,
                    travel_model=travel_model,
                )

                if tw_t + tw_tn + cap_t + cap_tn > 0:
                    continue

                # Compute new costs for affected days
                new_dist_t, new_time_t = 0.0, 0.0
                for r in routes_t:
                    d, tt = _decompose_route_cost(r, inst, use_dynamic, travel_model)
                    new_dist_t += d
                    new_time_t += tt

                new_dist_tn, new_time_tn = 0.0, 0.0
                for r in routes_tn:
                    d, tt = _decompose_route_cost(r, inst, use_dynamic, travel_model)
                    new_dist_tn += d
                    new_time_tn += tt

                new_inv = compute_inventory_cost(cand_I, inst)
                new_total_dist = total_dist - day_dist[t] - day_dist[t_new] + new_dist_t + new_dist_tn
                new_total_time = total_time - day_time[t] - day_time[t_new] + new_time_t + new_time_tn
                new_fitness = new_inv + new_total_dist + new_total_time

                if new_fitness < best_fitness - 1e-6:
                    best = candidate
                    day_dist[t] = new_dist_t
                    day_dist[t_new] = new_dist_tn
                    day_time[t] = new_time_t
                    day_time[t_new] = new_time_tn
                    total_dist = new_total_dist
                    total_time = new_total_time
                    inv_cost = new_inv
                    best_fitness = new_fitness
                    improved_i = True
                    break  # First improvement — move to next customer

    return best


def apply_local_search(
    chrom: Chromosome,
    inst: Instance,
    use_dynamic: bool = True,
    use_time_shift: bool = True,
    rng: Optional[np.random.Generator] = None,
    travel_model: Optional[TravelTimeModel] = None,
) -> Chromosome:
    """
    Apply local search pipeline.

    DevGuide §4.3: Scenario B uses 2-opt only; Scenario C uses Time-Shift + 2-opt.

    Parameters
    ----------
    chrom : Chromosome
    inst : Instance
    use_dynamic : bool
    use_time_shift : bool
        If True, apply Time-Shift NS before 2-opt (Scenario C).
        If False, only 2-opt (Scenario B).
    rng : optional

    Returns
    -------
    Chromosome
        Improved chromosome.
    """
    # Step 1: Time-Shift (only for Scenario C)
    if use_time_shift:
        improved = time_shift(chrom, inst, use_dynamic=use_dynamic, rng=rng, travel_model=travel_model)
    else:
        improved = copy_chromosome(chrom)

    # Step 2: 2-opt on each route, then Or-opt between routes per day
    sol = decode_chromosome(improved, inst, use_dynamic=use_dynamic, travel_model=travel_model)

    any_improved = False
    for t in range(inst.T):
        # Intra-route: 2-opt
        for r_idx, route in enumerate(sol.schedule[t]):
            if len(route.stops) > 2:
                new_route = two_opt_route(route, inst, use_dynamic=use_dynamic, travel_model=travel_model)
                old_d, old_t = _decompose_route_cost(route, inst, use_dynamic, travel_model)
                new_d, new_t = _decompose_route_cost(new_route, inst, use_dynamic, travel_model)
                if (new_d + new_t) < (old_d + old_t) - 1e-6:
                    sol.schedule[t][r_idx] = new_route
                    any_improved = True

        # Inter-route: Or-opt (relocate customers between routes)
        if len(sol.schedule[t]) >= 2:
            or_opt_day(sol.schedule[t], inst, use_dynamic=use_dynamic, travel_model=travel_model)
            any_improved = True

    if any_improved:
        sol.cost_distance = 0.0
        sol.cost_time = 0.0
        for t in range(inst.T):
            for route in sol.schedule[t]:
                d_cost, t_cost = _decompose_route_cost(route, inst, use_dynamic, travel_model)
                sol.cost_distance += d_cost
                sol.cost_time += t_cost

    # Persist current route order back to π so 2-opt/Or-opt improvements are kept (P1 fix).
    improved.pi = _solution_to_pi(sol, inst.n)

    improved._fitness = sol.fitness

    return improved
