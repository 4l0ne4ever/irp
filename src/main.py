"""
IRP-TW-DT: CLI Entry Point
Inventory Routing Problem with Time Windows & Dynamic Traffic
"""

import argparse
import logging
import sys

from src.core.constants import (
    GA_POP_SIZE, GA_GENERATIONS, GA_TIME_LIMIT,
    SCALE_CONFIGS, EXPERIMENT_SEEDS,
)


def setup_logging(verbose: bool = False):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def cmd_convert(args):
    """Convert VRPTW datasets to IRP-TW-DT format."""
    from src.data.converter import convert_all_lognormal

    print("Converting VRPTW lognormal datasets to IRP-TW-DT format...")
    instances = convert_all_lognormal(
        dataset_dir=args.source,
        output_dir=args.output,
    )
    print(f"\nDone: {len(instances)} instances converted.")


def cmd_single(args):
    """Run a single experiment."""
    from src.experiments.runner import run_single

    result = run_single(
        scenario=args.scenario,
        n=args.n, m=args.m, seed=args.seed,
        instance_dir=args.instance_dir,
        pop_size=args.pop_size,
        generations=args.generations,
        time_limit=args.time_limit,
        output_dir=args.output,
    )

    print(f"\n{'='*50}")
    print(f"Scenario {result['scenario']} | n={result['n']} m={result['m']} seed={result['seed']}")
    print(f"{'='*50}")
    print(f"Total Cost:     {result['total_cost']:>14,.0f} VND")
    print(f"  Inventory:    {result['cost_inventory']:>14,.0f}")
    print(f"  Distance:     {result['cost_distance']:>14,.0f}")
    print(f"  Time:         {result['cost_time']:>14,.0f}")
    print(f"Feasible:       {result['feasible']}")
    print(f"TW Violations:  {result['tw_violations']}")
    print(f"Stockouts:      {result['stockout_violations']}")
    print(f"CPU Time:       {result['cpu_time_sec']:.1f}s")
    print(f"Output:         {args.output}/{result['scenario']}_{result['scale']}_n{result['n']}_seed{result['seed']}/")


def cmd_batch(args):
    """Run all 60 experiments."""
    from src.experiments.runner import run_all_experiments

    results = run_all_experiments(
        output_dir=args.output,
        instance_dir=args.instance_dir,
        pop_size=args.pop_size,
        generations=args.generations,
        time_limit=args.time_limit,
    )
    print(f"\nCompleted {len(results)} experiments.")


def cmd_analyze(args):
    """Analyze results from CSV."""
    from src.experiments.analysis import load_results, print_summary

    df = load_results(args.csv)
    if df is not None:
        print_summary(df)


def cmd_visualize(args):
    """Visualize a solution on Hanoi map."""
    from src.data.generator import load_instance
    from src.experiments.visualize import visualize_solution
    from src.solver.hga import HGA
    from src.baselines.periodic import solve_periodic
    from src.baselines.rmi import solve_rmi

    # Load instance
    inst = load_instance(args.instance_dir)
    print(f"Loaded instance: {inst.name} (n={inst.n}, m={inst.m})")

    # Solve
    scenario = args.scenario
    if scenario == "P":
        sol = solve_periodic(inst)
    elif scenario == "A":
        sol = solve_rmi(inst)
    elif scenario == "B":
        hga = HGA(inst, pop_size=args.pop_size, generations=args.generations,
                  time_limit=args.time_limit, use_dynamic=False, seed=args.seed)
        sol = hga.run()
    elif scenario == "C":
        hga = HGA(inst, pop_size=args.pop_size, generations=args.generations,
                  time_limit=args.time_limit, use_dynamic=True, seed=args.seed)
        sol = hga.run()
    else:
        raise ValueError(f"Unknown scenario: {scenario}")

    print(f"Total Cost: {sol.total_cost:,.0f} VND (feasible={sol.feasible})")

    # Visualize
    output = args.output or f"results/map_{inst.name}_{scenario}.html"
    path = visualize_solution(
        inst, sol, output_path=output,
        title=f"Scenario {scenario}: {inst.name}",
        use_osrm_geometry=True,
    )
    print(f"Map saved to: {path}")


def main():
    parser = argparse.ArgumentParser(
        description="IRP-TW-DT: Inventory Routing with Time Windows & Dynamic Traffic"
    )
    parser.add_argument("--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command")

    # Convert VRPTW → IRP
    p_convert = sub.add_parser("convert", help="Convert VRPTW datasets to IRP-TW-DT")
    p_convert.add_argument("--source", default="src/data/test-dataset",
                           help="Input VRPTW JSON directory")
    p_convert.add_argument("--output", default="src/data/irp-instances",
                           help="Output IRP instance directory")

    # Single run
    p_single = sub.add_parser("run", help="Run a single experiment")
    p_single.add_argument("--scenario", choices=["P", "A", "B", "C"], required=True)
    p_single.add_argument("--n", type=int, required=True, help="Number of customers")
    p_single.add_argument("--m", type=int, required=True, help="Number of vehicles")
    p_single.add_argument("--seed", type=int, default=42)
    p_single.add_argument("--instance-dir", default="src/data/irp-instances",
                           help="Directory with converted instances")
    p_single.add_argument("--output", default="results",
                           help="Output directory for run folder")
    p_single.add_argument("--pop-size", type=int, default=GA_POP_SIZE)
    p_single.add_argument("--generations", type=int, default=GA_GENERATIONS)
    p_single.add_argument("--time-limit", type=float, default=GA_TIME_LIMIT)

    # Batch run
    p_batch = sub.add_parser("batch", help="Run all 60 experiments")
    p_batch.add_argument("--output", default="results")
    p_batch.add_argument("--instance-dir", default="src/data/irp-instances",
                          help="Directory with converted instances")
    p_batch.add_argument("--pop-size", type=int, default=GA_POP_SIZE)
    p_batch.add_argument("--generations", type=int, default=GA_GENERATIONS)
    p_batch.add_argument("--time-limit", type=float, default=GA_TIME_LIMIT)

    # Analysis
    p_analyze = sub.add_parser("analyze", help="Analyze results")
    p_analyze.add_argument("--csv", default="results/results.csv")

    # Visualize
    p_viz = sub.add_parser("visualize", help="Visualize solution on Hanoi map")
    p_viz.add_argument("--instance-dir", required=True,
                       help="Path to instance directory (e.g. src/data/irp-instances/S_n20_seed42)")
    p_viz.add_argument("--scenario", choices=["P", "A", "B", "C"], default="C")
    p_viz.add_argument("--seed", type=int, default=42)
    p_viz.add_argument("--output", default=None, help="Output HTML path")
    p_viz.add_argument("--pop-size", type=int, default=GA_POP_SIZE)
    p_viz.add_argument("--generations", type=int, default=GA_GENERATIONS)
    p_viz.add_argument("--time-limit", type=float, default=GA_TIME_LIMIT)

    args = parser.parse_args()
    setup_logging(args.verbose)

    if args.command == "convert":
        cmd_convert(args)
    elif args.command == "run":
        cmd_single(args)
    elif args.command == "batch":
        cmd_batch(args)
    elif args.command == "analyze":
        cmd_analyze(args)
    elif args.command == "visualize":
        cmd_visualize(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
