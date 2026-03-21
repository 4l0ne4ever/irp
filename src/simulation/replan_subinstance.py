"""
Rolling-horizon re-plan: sub-instance for remaining stops on a day + merge back into full solution.
"""

from __future__ import annotations

import copy
import logging
from dataclasses import dataclass
from typing import List, Optional, Tuple

import numpy as np

from src.core.instance import Instance, validate_instance
from src.core.solution import Route, Solution
from src.core.traffic import TravelTimeModel, build_travel_model
from src.solver.chromosome import Chromosome
from src.solver.hga import HGA
from src.messaging.kafka_convergence import clear_convergence_run_id, set_convergence_run_id
from src.simulation.schedule_metrics import solution_from_schedule

logger = logging.getLogger(__name__)


@dataclass
class SubProblem:
    inst: Instance
    """0-based global customer indices included in sub-instance, shape (n_sub,)."""
    old_indices: np.ndarray
    """sub-local customer index j -> global 0-based customer index."""
    sub_to_old: np.ndarray


def _day_time_fraction(inst: Instance, sim_time_h: float) -> float:
    t_lo = float(np.min(inst.e))
    t_hi = float(np.max(inst.l))
    span = max(1e-6, t_hi - t_lo)
    frac = (float(sim_time_h) - t_lo) / span
    return float(min(1.0, max(0.0, frac)))


def _inventory_after_prefix(
    inst: Instance,
    sol: Solution,
    day: int,
    sim_time_h: float,
) -> np.ndarray:
    """Inventory vector (n,) after applying OU deliveries for stops with arrival <= sim_time_h."""
    if sol.inventory_trace is not None and day > 0:
        I = sol.inventory_trace[:, day - 1].copy()
    else:
        I = inst.I0.copy()
    frac = _day_time_fraction(inst, sim_time_h)
    I = I - inst.demand[:, day] * frac
    stops: List[Tuple[float, int, float]] = []
    for route in sol.schedule[day]:
        for c1, q, arr in route.stops:
            stops.append((float(arr), int(c1), float(q)))
    for arr, c1, _q in sorted(stops, key=lambda x: x[0]):
        if arr > sim_time_h + 1e-6:
            break
        ci = c1 - 1
        I[ci] = inst.U[ci]
    return I


def _collect_remaining(
    sol: Solution,
    day: int,
    sim_time_h: float,
) -> np.ndarray:
    """Unique global 0-based customer indices with a stop planned after sim_time_h."""
    seen = set()
    out: List[int] = []
    for route in sol.schedule[day]:
        for c1, q, arr in route.stops:
            if float(arr) > float(sim_time_h):
                g = int(c1) - 1
                if g not in seen:
                    seen.add(g)
                    out.append(g)
    if not out:
        return np.array([], dtype=np.int32)
    out.sort()
    return np.array(out, dtype=np.int32)


def build_subinstance(
    inst: Instance,
    sol: Solution,
    day: int,
    sim_time_h: float,
) -> Tuple[SubProblem, np.ndarray]:
    """
    Build a single-day (T=1) sub-instance over customers still to be served after sim_time_h.
    Returns SubProblem and I0_sub (length n_sub).
    """
    old_indices = _collect_remaining(sol, day, sim_time_h)
    if old_indices.size == 0:
        raise RuntimeError("no remaining stops for this day at the given sim_time_h")

    n_sub = int(old_indices.size)
    sub_to_old = old_indices.astype(np.int32)
    I_full = _inventory_after_prefix(inst, sol, day, sim_time_h)
    I0_sub = np.array([I_full[int(sub_to_old[j])] for j in range(n_sub)], dtype=float)
    U_sub = np.array([inst.U[int(sub_to_old[j])] for j in range(n_sub)], dtype=float)
    L_sub = np.array([inst.L_min[int(sub_to_old[j])] for j in range(n_sub)], dtype=float)
    h_sub = np.array([inst.h[int(sub_to_old[j])] for j in range(n_sub)], dtype=float)
    e_sub = np.array([inst.e[int(sub_to_old[j])] for j in range(n_sub)], dtype=float)
    l_sub = np.array([inst.l[int(sub_to_old[j])] for j in range(n_sub)], dtype=float)
    s_sub = np.array([inst.s[int(sub_to_old[j])] for j in range(n_sub)], dtype=float)
    frac_rem = 1.0 - _day_time_fraction(inst, sim_time_h)
    d_sub = np.zeros((n_sub, 1), dtype=float)
    for j in range(n_sub):
        oi = int(sub_to_old[j])
        d_sub[j, 0] = float(inst.demand[oi, day]) * max(0.0, frac_rem)

    idx = np.concatenate([[0], 1 + np.arange(n_sub, dtype=np.int32)])
    coords_sub = inst.coords[idx, :].copy()
    dist_sub = inst.dist[np.ix_(idx, idx)].copy()
    dist_sub = (dist_sub + dist_sub.T) * 0.5

    name = f"{inst.name}_replan_d{day}"
    sub_inst = Instance(
        name=name,
        n=n_sub,
        T=1,
        m=inst.m,
        coords=coords_sub,
        dist=dist_sub,
        U=U_sub,
        L_min=L_sub,
        I0=I0_sub,
        demand=d_sub,
        h=h_sub,
        e=e_sub,
        l=l_sub,
        s=s_sub,
        c_d=inst.c_d,
        c_t=inst.c_t,
        Q=inst.Q,
    )
    err = validate_instance(sub_inst)
    if err:
        raise RuntimeError("sub-instance invalid: " + "; ".join(err))
    meta = SubProblem(inst=sub_inst, old_indices=old_indices, sub_to_old=sub_to_old)
    return meta, I0_sub


def project_seed_chromosome(chrom: Chromosome, sub_meta: SubProblem) -> Chromosome:
    """Order remaining customers by global giant-tour order (chrom.pi); Y all ones for the single day."""
    rem_set = set(int(x) for x in sub_meta.old_indices.tolist())
    order_g = [int(chrom.pi[i]) for i in range(len(chrom.pi)) if int(chrom.pi[i]) in rem_set]
    g_to_sub = {int(sub_meta.sub_to_old[j]): j for j in range(sub_meta.inst.n)}
    pi_sub = np.array([g_to_sub[g] for g in order_g], dtype=np.int32)
    if pi_sub.size != sub_meta.inst.n or set(int(x) for x in pi_sub.tolist()) != set(range(sub_meta.inst.n)):
        pi_sub = np.arange(sub_meta.inst.n, dtype=np.int32)
    Y_sub = np.ones((sub_meta.inst.n, 1), dtype=np.int32)
    return Chromosome(Y=Y_sub, pi=pi_sub)


def _merge_day(
    inst: Instance,
    sol: Solution,
    day: int,
    sim_time_h: float,
    sub_sol: Solution,
    sub_meta: SubProblem,
    travel_model: TravelTimeModel,
    use_dynamic: bool,
) -> List[Route]:
    """Prefix (unchanged) + suffix from sub re-optimized routes with chained times."""
    m = inst.m
    sub_to_old = sub_meta.sub_to_old
    new_routes: List[Route] = []
    for k in range(m):
        r_old = sol.schedule[day][k]
        pref = [(c, q, a) for c, q, a in r_old.stops if float(a) <= float(sim_time_h) + 1e-6]
        sub_r = sub_sol.schedule[0][k]
        merged: List[Tuple[int, float, float]] = list(pref)
        if not sub_r.stops:
            depart_h = float(r_old.depart_h)
            new_routes.append(
                Route(vehicle_id=k, day=day, depart_h=depart_h, stops=merged)
            )
            continue
        if not pref:
            prev_loc = 0
            t = float(sim_time_h)
            depart_h = float(sim_time_h)
        else:
            last_c, _lq, last_a = pref[-1]
            prev_loc = int(last_c)
            lc = int(last_c) - 1
            t = float(last_a) + float(inst.s[lc])
            depart_h = float(r_old.depart_h)
        for cust_s, q_sub, _ in sub_r.stops:
            glo = int(sub_to_old[int(cust_s) - 1])
            g1 = glo + 1
            dist_km = float(inst.dist[prev_loc, g1])
            tt = travel_model.duration_h(prev_loc, g1, t, dist_km)
            arr = t + tt
            if arr < inst.e[glo]:
                arr = float(inst.e[glo])
            q_use = float(q_sub)
            merged.append((g1, q_use, float(arr)))
            t = float(arr) + float(inst.s[glo])
            prev_loc = g1
        new_routes.append(Route(vehicle_id=k, day=day, depart_h=depart_h, stops=merged))
    return new_routes


def merge_sub_solution(
    inst: Instance,
    sol: Solution,
    day: int,
    sim_time_h: float,
    sub_sol: Solution,
    sub_meta: SubProblem,
    travel_model: TravelTimeModel,
    use_dynamic: bool,
) -> Solution:
    sched = copy.deepcopy(sol.schedule)
    sched[day] = _merge_day(inst, sol, day, sim_time_h, sub_sol, sub_meta, travel_model, use_dynamic)
    return solution_from_schedule(inst, sched, use_dynamic=use_dynamic, travel_model=travel_model)


def run_sub_replan_hga(
    inst: Instance,
    sol: Solution,
    chrom: Chromosome,
    day: int,
    sim_time_h: float,
    *,
    scenario: str,
    traffic_model_key: str,
    seed: int,
    pop_size: int,
    generations: int,
    time_limit: float,
    run_id: Optional[str] = None,
) -> Tuple[Solution, Solution, SubProblem]:
    """
    Build sub-instance, run HGA, merge into full solution.
    Returns (merged_full_solution, sub_solution, sub_meta).
    """
    sub_meta, _I0s = build_subinstance(inst, sol, day, sim_time_h)
    tm = build_travel_model(traffic_model_key)
    seed_chrom = project_seed_chromosome(chrom, sub_meta)
    use_dynamic = scenario == "C"
    set_convergence_run_id(run_id)
    try:
        hga = HGA(
            sub_meta.inst,
            pop_size=pop_size,
            generations=generations,
            time_limit=time_limit,
            use_dynamic=use_dynamic,
            seed=seed,
            travel_model=tm,
            seed_chromosome=seed_chrom,
        )
        sub_sol = hga.run()
    finally:
        clear_convergence_run_id()
    merged = merge_sub_solution(inst, sol, day, sim_time_h, sub_sol, sub_meta, tm, use_dynamic)
    return merged, sub_sol, sub_meta
