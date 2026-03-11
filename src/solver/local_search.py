"""
Local Search operators for IRP-TW-DT.
- 2-opt: spatial improvement of routes
- Time-Shift: temporal improvement (shift delivery days)
"""

from typing import List, Optional

import numpy as np

from src.core.instance import Instance
from src.core.solution import Route, Solution
from src.core.traffic import igp_travel_time, static_travel_time
from src.core.inventory import simulate_inventory, check_feasibility, compute_inventory_cost
from src.core.constants import DEPARTURE_SLOTS_MORNING, DEPARTURE_SLOTS_AFTERNOON
from .chromosome import Chromosome, copy_chromosome
from .decode import decode_chromosome, _compute_route_cost, _decompose_route_cost, _decode_day


def two_opt_route(
    route: Route,
    inst: Instance,
    use_dynamic: bool = True,
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
        best_order, inst, route.depart_h, route.day, q_day, use_dynamic
    )[0]
    improved = True

    while improved:
        improved = False
        for i in range(n_stops - 1):
            for j in range(i + 1, n_stops):
                new_order = best_order[:i] + best_order[i:j + 1][::-1] + best_order[j + 1:]
                new_cost = _compute_route_cost(
                    new_order, inst, route.depart_h, route.day, q_day, use_dynamic
                )[0]

                if new_cost < best_cost - 1e-6:
                    best_order = new_order
                    best_cost = new_cost
                    improved = True
                    break
            if improved:
                break

    # Rebuild route with new order
    _, stops = _compute_route_cost(best_order, inst, route.depart_h, route.day, q_day, use_dynamic)

    return Route(
        vehicle_id=route.vehicle_id,
        day=route.day,
        depart_h=route.depart_h,
        stops=stops,
    )


def time_shift(
    chrom: Chromosome,
    inst: Instance,
    use_dynamic: bool = True,
    rng: Optional[np.random.Generator] = None,
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
        )
        dc, tc = 0.0, 0.0
        for r in routes:
            d, tt = _decompose_route_cost(r, inst, use_dynamic)
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
                )
                routes_tn, tw_tn, cap_tn = _decode_day(
                    candidate.pi, candidate.Y[:, t_new], inst, t_new, cand_q[:, t_new],
                    morning_slots, afternoon_slots, use_dynamic, m,
                )

                if tw_t + tw_tn + cap_t + cap_tn > 0:
                    continue

                # Compute new costs for affected days
                new_dist_t, new_time_t = 0.0, 0.0
                for r in routes_t:
                    d, tt = _decompose_route_cost(r, inst, use_dynamic)
                    new_dist_t += d
                    new_time_t += tt

                new_dist_tn, new_time_tn = 0.0, 0.0
                for r in routes_tn:
                    d, tt = _decompose_route_cost(r, inst, use_dynamic)
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
        improved = time_shift(chrom, inst, use_dynamic=use_dynamic, rng=rng)
    else:
        improved = copy_chromosome(chrom)

    # Step 2: 2-opt on each route
    sol = decode_chromosome(improved, inst, use_dynamic=use_dynamic)

    any_improved = False
    for t in range(inst.T):
        for r_idx, route in enumerate(sol.schedule[t]):
            if len(route.stops) > 2:
                new_route = two_opt_route(route, inst, use_dynamic=use_dynamic)
                old_d, old_t = _decompose_route_cost(route, inst, use_dynamic)
                new_d, new_t = _decompose_route_cost(new_route, inst, use_dynamic)
                if (new_d + new_t) < (old_d + old_t) - 1e-6:
                    sol.schedule[t][r_idx] = new_route
                    any_improved = True

    if any_improved:
        sol.cost_distance = 0.0
        sol.cost_time = 0.0
        for t in range(inst.T):
            for route in sol.schedule[t]:
                d_cost, t_cost = _decompose_route_cost(route, inst, use_dynamic)
                sol.cost_distance += d_cost
                sol.cost_time += t_cost

    improved._fitness = sol.fitness

    return improved
