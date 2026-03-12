"""
Experiment Runner for IRP-TW-DT.
Runs all 60 experiments (4 scenarios × 3 scales × 5 seeds).
Supports both synthetic and converted real Hanoi data.

Each run produces a subfolder containing:
- result.json: detailed numerical results
- map.html: interactive Folium map visualization
- convergence.csv: HGA convergence log (for scenarios B/C)
"""

import csv
import json
import logging
import os
import time
from datetime import datetime
from typing import Dict, List, Optional

import numpy as np

from src.core.instance import Instance
from src.core.solution import Solution
from src.core.constants import (
    EXPERIMENT_SEEDS, SCALE_CONFIGS, GA_POP_SIZE, GA_GENERATIONS, GA_TIME_LIMIT,
    C_D,
)
from src.data.generator import load_instance
from src.solver.hga import HGA
from src.baselines.periodic import solve_periodic
from src.baselines.rmi import solve_rmi

logger = logging.getLogger(__name__)


def _load_or_generate_instance(
    scale_name: str, n: int, m: int, seed: int,
    instance_dir: Optional[str] = None,
) -> Instance:
    """
    Load instance from converted data if available, otherwise generate synthetic.

    Parameters
    ----------
    scale_name : str
        Scale identifier (S/M/L).
    n, m, seed : int
        Instance parameters.
    instance_dir : str or None
        Directory containing converted instances (e.g., "src/data/irp-instances").
        Expected subdirectory: {scale}_n{n}_seed{seed}/

    Returns
    -------
    Instance
    """
    if instance_dir:
        inst_path = os.path.join(instance_dir, f"{scale_name}_n{n}_seed{seed}")
        if os.path.exists(inst_path):
            logger.info(f"  Loading real instance from {inst_path}")
            return load_instance(inst_path)
        else:
            raise FileNotFoundError(
                f"Instance not found at {inst_path}. "
                f"Run 'python -m src.main convert' first to generate instances from VRPTW data."
            )

    raise ValueError("instance_dir is required — only real OSRM-based instances are supported")


def run_all_experiments(
    output_dir: str = "results",
    instance_dir: Optional[str] = "src/data/irp-instances",
    pop_size: int = GA_POP_SIZE,
    generations: int = GA_GENERATIONS,
    time_limit: float = GA_TIME_LIMIT,
) -> List[Dict]:
    """
    Run the complete experiment matrix: 4 scenarios × 3 scales × 5 seeds = 60 runs.

    Each run creates a subfolder with map.html + result.json + convergence.csv.

    Parameters
    ----------
    output_dir : str
        Root directory for results.
    instance_dir : str or None
        Path to directory with pre-converted instances.
    pop_size, generations, time_limit : HGA parameters.

    Returns
    -------
    List[Dict]
        Results for each run.
    """
    batch_name = f"batch_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    batch_dir = os.path.join(output_dir, batch_name)
    os.makedirs(batch_dir, exist_ok=True)
    results = []

    for scale_name, (n, m) in SCALE_CONFIGS.items():
        for seed in EXPERIMENT_SEEDS:
            logger.info(f"\n{'='*60}")
            logger.info(f"Scale={scale_name} (n={n}, m={m}), Seed={seed}")
            logger.info(f"{'='*60}")

            # Load or generate instance
            inst = _load_or_generate_instance(
                scale_name, n, m, seed, instance_dir
            )

            # Scenario P: Periodic
            logger.info("  Running Scenario P (Periodic)...")
            t0 = time.time()
            sol_p = solve_periodic(inst)
            time_p = time.time() - t0
            res_p = _make_result("P", scale_name, n, m, seed, sol_p, time_p, inst=inst)
            _save_run_output(batch_dir, "P", scale_name, n, seed, inst, sol_p, res_p)
            results.append(res_p)

            # Scenario A: RMI
            logger.info("  Running Scenario A (RMI)...")
            t0 = time.time()
            sol_a = solve_rmi(inst)
            time_a = time.time() - t0
            res_a = _make_result("A", scale_name, n, m, seed, sol_a, time_a, inst=inst)
            _save_run_output(batch_dir, "A", scale_name, n, seed, inst, sol_a, res_a)
            results.append(res_a)

            # Scenario B: IRP-TW-Static (HGA with constant speed)
            logger.info("  Running Scenario B (IRP-TW-Static)...")
            hga_b = HGA(
                inst, pop_size=pop_size, generations=generations,
                time_limit=time_limit, use_dynamic=False, seed=seed,
            )
            t0 = time.time()
            sol_b = hga_b.run()
            time_b = time.time() - t0
            res_b = _make_result(
                "B", scale_name, n, m, seed, sol_b, time_b,
                inst=inst, convergence=hga_b.convergence_log,
            )
            _save_run_output(batch_dir, "B", scale_name, n, seed, inst, sol_b, res_b,
                             convergence=hga_b.convergence_log)
            results.append(res_b)

            # Scenario C: IRP-TW-DT (full model)
            logger.info("  Running Scenario C (IRP-TW-DT)...")
            hga_c = HGA(
                inst, pop_size=pop_size, generations=generations,
                time_limit=time_limit, use_dynamic=True, seed=seed,
            )
            t0 = time.time()
            sol_c = hga_c.run()
            time_c = time.time() - t0
            res_c = _make_result(
                "C", scale_name, n, m, seed, sol_c, time_c,
                inst=inst, convergence=hga_c.convergence_log,
            )
            _save_run_output(batch_dir, "C", scale_name, n, seed, inst, sol_c, res_c,
                             convergence=hga_c.convergence_log)
            results.append(res_c)

    # Save summary CSV
    csv_path = os.path.join(batch_dir, "results.csv")
    _save_csv(results, csv_path)
    logger.info(f"\nResults saved to {batch_dir}")

    return results


def run_single(
    scenario: str,
    n: int,
    m: int,
    seed: int,
    instance_dir: Optional[str] = "src/data/irp-instances",
    pop_size: int = GA_POP_SIZE,
    generations: int = GA_GENERATIONS,
    time_limit: float = GA_TIME_LIMIT,
    output_dir: str = "results",
) -> Dict:
    """Run a single experiment configuration and save outputs."""
    # Determine scale name
    scale = "custom"
    for k, (nn, mm) in SCALE_CONFIGS.items():
        if nn == n and mm == m:
            scale = k
            break

    inst = _load_or_generate_instance(scale, n, m, seed, instance_dir)

    convergence = None
    t0 = time.time()
    if scenario == "P":
        sol = solve_periodic(inst)
    elif scenario == "A":
        sol = solve_rmi(inst)
    elif scenario == "B":
        hga = HGA(inst, pop_size, generations, time_limit,
                  use_dynamic=False, seed=seed)
        sol = hga.run()
        convergence = hga.convergence_log
    elif scenario == "C":
        hga = HGA(inst, pop_size, generations, time_limit,
                  use_dynamic=True, seed=seed)
        sol = hga.run()
        convergence = hga.convergence_log
    else:
        raise ValueError(f"Unknown scenario: {scenario}")

    elapsed = time.time() - t0
    result = _make_result(scenario, scale, n, m, seed, sol, elapsed,
                          inst=inst, convergence=convergence)

    # Save outputs (map + json + convergence)
    _save_run_output(output_dir, scenario, scale, n, seed, inst, sol, result,
                     convergence=convergence)

    return result


def _make_result(
    scenario: str, scale: str, n: int, m: int, seed: int,
    sol: Solution, elapsed: float,
    inst: Instance = None,
    convergence: list = None,
) -> Dict:
    """Create a result dictionary from a solution with all DevGuide §6.2 KPIs."""
    n_deliveries = 0
    for day_routes in sol.schedule:
        for route in day_routes:
            n_deliveries += len(route.stops)

    total_distance = sol.cost_distance / C_D if sol.cost_distance > 0 else 0.0
    tw_compliance = 100.0 if (sol.tw_violations == 0 or n_deliveries == 0) else \
        (1.0 - sol.tw_violations / n_deliveries) * 100.0

    # Avg inventory level as % of U
    avg_inv_pct = 0.0
    if inst is not None and sol.inventory_trace is not None:
        avg_inv = np.mean(sol.inventory_trace)
        avg_U = np.mean(inst.U)
        avg_inv_pct = (avg_inv / avg_U) * 100.0 if avg_U > 0 else 0.0

    # Cost breakdown percentages
    tc = sol.total_cost if sol.total_cost > 0 else 1.0
    pct_inv = (sol.cost_inventory / tc) * 100.0
    pct_dist = (sol.cost_distance / tc) * 100.0
    pct_time = (sol.cost_time / tc) * 100.0

    # Per-day statistics
    per_day = []
    for t in range(len(sol.schedule)):
        day_routes = sol.schedule[t]
        day_deliveries = sum(len(r.stops) for r in day_routes)
        day_dist = sum(
            r.stops[-1][2] - r.depart_h if r.stops else 0
            for r in day_routes
        )
        # Compute actual distance for this day
        day_km = 0.0
        for route in day_routes:
            prev = 0
            for cust_1b, _, _ in route.stops:
                if inst is not None:
                    day_km += inst.dist[prev, cust_1b]
                prev = cust_1b
            if inst is not None and route.stops:
                day_km += inst.dist[prev, 0]

        per_day.append({
            "day": t,
            "n_deliveries": day_deliveries,
            "n_routes": len(day_routes),
            "distance_km": round(day_km, 2),
        })

    return {
        "scenario": scenario,
        "scale": scale,
        "n": n,
        "m": m,
        "seed": seed,
        # Primary KPIs (DevGuide §6.2)
        "total_cost": sol.total_cost,
        "cost_inventory": sol.cost_inventory,
        "cost_distance": sol.cost_distance,
        "cost_time": sol.cost_time,
        "cost_pct_inventory": round(pct_inv, 1),
        "cost_pct_distance": round(pct_dist, 1),
        "cost_pct_time": round(pct_time, 1),
        # Feasibility
        "feasible": sol.feasible,
        "tw_violations": sol.tw_violations,
        "stockout_violations": sol.stockout_violations,
        "capacity_violations": sol.capacity_violations,
        "tw_compliance_rate": round(tw_compliance, 1),
        # Delivery statistics
        "n_deliveries": n_deliveries,
        "avg_deliveries_per_customer": round(n_deliveries / n, 2) if n > 0 else 0,
        "total_distance_km": round(total_distance, 2),
        # Inventory statistics
        "avg_inventory_level_pct": round(avg_inv_pct, 1),
        # Performance
        "cpu_time_sec": round(elapsed, 2),
        "fitness": sol.fitness,
        # Per-day breakdown
        "per_day": per_day,
    }


def _save_run_output(
    parent_dir: str,
    scenario: str, scale: str, n: int, seed: int,
    inst: Instance, sol: Solution, result: Dict,
    convergence: list = None,
) -> str:
    """
    Save a single run's outputs to a subfolder.

    Creates: <parent_dir>/<scenario>_<scale>_n<n>_seed<seed>/
      - result.json: numerical results
      - map.html: interactive Folium map
      - convergence.csv: HGA convergence log (if applicable)

    Returns the run directory path.
    """
    run_name = f"{scenario}_{scale}_n{n}_seed{seed}"
    run_dir = os.path.join(parent_dir, run_name)
    os.makedirs(run_dir, exist_ok=True)

    # 1. Save result.json
    json_path = os.path.join(run_dir, "result.json")
    with open(json_path, "w") as f:
        json.dump(result, f, indent=2, default=str)

    # 2. Save detailed metrics report (human-readable)
    _save_detailed_metrics(run_dir, result, inst, sol)

    # 3. Save map visualization
    try:
        from src.experiments.visualize import visualize_solution
        visualize_solution(
            inst, sol,
            output_path=os.path.join(run_dir, "map.html"),
            title=f"Scenario {scenario}: {scale} n={n} seed={seed}",
            use_osrm_geometry=True,
        )
    except Exception as e:
        logger.warning(f"Map generation failed for {run_name}: {e}")

    # 4. Save convergence log (for HGA scenarios B/C)
    if convergence:
        conv_path = os.path.join(run_dir, "convergence.csv")
        with open(conv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=convergence[0].keys())
            writer.writeheader()
            writer.writerows(convergence)

    logger.info(f"  Run output saved to {run_dir}")
    return run_dir


def _save_detailed_metrics(
    run_dir: str, result: Dict, inst: Instance, sol: Solution
) -> None:
    """Save a human-readable metrics report for analysis."""
    lines = []
    lines.append("=" * 60)
    lines.append(f"IRP-TW-DT DETAILED METRICS REPORT")
    lines.append(f"Scenario {result['scenario']} | Scale {result['scale']} "
                 f"| n={result['n']} m={result['m']} seed={result['seed']}")
    lines.append("=" * 60)

    lines.append("")
    lines.append("1. OBJECTIVE FUNCTION BREAKDOWN")
    lines.append("-" * 40)
    lines.append(f"  Total Cost (Z):       {result['total_cost']:>14,.0f} VND")
    lines.append(f"  Inventory Holding:    {result['cost_inventory']:>14,.0f} VND  ({result['cost_pct_inventory']}%)")
    lines.append(f"  Distance Cost:        {result['cost_distance']:>14,.0f} VND  ({result['cost_pct_distance']}%)")
    lines.append(f"  Time-Dep Travel Cost: {result['cost_time']:>14,.0f} VND  ({result['cost_pct_time']}%)")

    lines.append("")
    lines.append("2. FEASIBILITY")
    lines.append("-" * 40)
    lines.append(f"  Feasible:             {result['feasible']}")
    lines.append(f"  TW Violations:        {result['tw_violations']}")
    lines.append(f"  Stockout Violations:  {result['stockout_violations']}")
    lines.append(f"  Capacity Violations:  {result['capacity_violations']}")
    lines.append(f"  TW Compliance Rate:   {result['tw_compliance_rate']}%")

    lines.append("")
    lines.append("3. DELIVERY STATISTICS")
    lines.append("-" * 40)
    lines.append(f"  Total Deliveries:     {result['n_deliveries']}")
    lines.append(f"  Avg per Customer:     {result['avg_deliveries_per_customer']}")
    lines.append(f"  Total Distance:       {result['total_distance_km']} km")

    lines.append("")
    lines.append("4. INVENTORY ANALYSIS")
    lines.append("-" * 40)
    lines.append(f"  Avg Inventory Level:  {result['avg_inventory_level_pct']}% of capacity")

    if inst is not None and sol.inventory_trace is not None:
        I = sol.inventory_trace
        for i in range(min(inst.n, 10)):  # Show top 10 customers
            inv_vals = [f"{I[i, t]:.0f}" for t in range(inst.T)]
            lines.append(f"  Customer {i+1:>3d}: [{' -> '.join(inv_vals)}]  "
                         f"(U={inst.U[i]:.0f}, Lmin={inst.L_min[i]:.0f})")
        if inst.n > 10:
            lines.append(f"  ... ({inst.n - 10} more customers)")

    lines.append("")
    lines.append("5. PER-DAY BREAKDOWN")
    lines.append("-" * 40)
    lines.append(f"  {'Day':>4s}  {'Deliveries':>10s}  {'Routes':>6s}  {'Distance (km)':>14s}")
    for day_info in result.get("per_day", []):
        lines.append(f"  {day_info['day']:>4d}  {day_info['n_deliveries']:>10d}  "
                     f"{day_info['n_routes']:>6d}  {day_info['distance_km']:>14.2f}")

    lines.append("")
    lines.append("6. ROUTE DETAILS")
    lines.append("-" * 40)
    for t in range(len(sol.schedule)):
        if not sol.schedule[t]:
            continue
        lines.append(f"  Day {t}:")
        for r_idx, route in enumerate(sol.schedule[t]):
            custs = [str(s[0]) for s in route.stops]
            arrivals = [f"{s[2]:.2f}h" for s in route.stops]
            total_qty = sum(s[1] for s in route.stops)
            lines.append(f"    Route {r_idx}: depart {route.depart_h:.1f}h | "
                         f"stops [{' -> '.join(custs)}] | "
                         f"arrivals [{', '.join(arrivals)}] | "
                         f"load {total_qty:.0f}/{inst.Q:.0f}")

    lines.append("")
    lines.append("7. PERFORMANCE")
    lines.append("-" * 40)
    lines.append(f"  CPU Time:             {result['cpu_time_sec']}s")
    lines.append(f"  Fitness:              {result['fitness']:,.0f}")

    lines.append("")
    lines.append("=" * 60)

    with open(os.path.join(run_dir, "metrics.txt"), "w") as f:
        f.write("\n".join(lines))


def _save_csv(results: List[Dict], path: str):
    """Save results to CSV (excludes nested per_day field)."""
    if not results:
        return
    # Exclude per_day (nested list of dicts) from CSV
    fieldnames = [k for k in results[0].keys() if k != "per_day"]
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(results)
