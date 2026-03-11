"""
Comprehensive feasibility test across multiple scenarios, scales, and seeds.
Verifies that the HGA always produces feasible solutions.
"""

import sys
import time
import logging

from src.data.generator import generate_hanoi_instance, load_instance
from src.solver.hga import HGA

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)

# Test matrix: (n, m, seed, scenario, use_dynamic)
TEST_CASES = [
    # --- Small (n=20) ---
    (20, 2, 42,   "B", False),
    (20, 2, 42,   "C", True),
    (20, 2, 123,  "C", True),
    (20, 2, 456,  "C", True),
    (20, 2, 789,  "C", True),
    (20, 2, 1000, "C", True),
    # --- Medium (n=50) — the failing case ---
    (50, 3, 42,   "B", False),
    (50, 3, 42,   "C", True),
    (50, 3, 123,  "C", True),   # <-- was infeasible before fix
    (50, 3, 456,  "C", True),
    (50, 3, 789,  "C", True),
    (50, 3, 1000, "C", True),
    # --- Large (n=100) ---
    (100, 5, 42,  "B", False),
    (100, 5, 42,  "C", True),
    (100, 5, 123, "C", True),
]

def run_test(n, m, seed, scenario, use_dynamic):
    """Run one test case and return result dict."""
    # Try to load pre-generated instance
    scale = {20: "S", 50: "M", 100: "L"}.get(n, "X")
    inst_path = f"src/data/irp-instances/{scale}_n{n}_seed{seed}"
    try:
        inst = load_instance(inst_path)
    except Exception:
        inst = generate_hanoi_instance(n=n, m=m, seed=seed)

    hga = HGA(
        inst,
        time_limit=120.0,  # 2 min max per test
        use_dynamic=use_dynamic,
        seed=seed,
    )
    t0 = time.time()
    sol = hga.run()
    elapsed = time.time() - t0

    return {
        "n": n, "m": m, "seed": seed, "scenario": scenario,
        "feasible": sol.feasible,
        "tw_violations": sol.tw_violations,
        "stockout_violations": sol.stockout_violations,
        "capacity_violations": sol.capacity_violations,
        "total_cost": sol.total_cost,
        "pop_size": hga.pop_size,
        "generations": hga.generations,
        "elapsed": elapsed,
    }

if __name__ == "__main__":
    print(f"{'='*90}")
    print(f"{'Scenario':>4} {'n':>4} {'m':>2} {'seed':>5}  {'Feasible':>8}  "
          f"{'TW':>3}  {'SO':>3}  {'Cap':>3}  {'Cost':>14}  "
          f"{'Pop':>4}  {'Gen':>4}  {'Time':>6}")
    print(f"{'='*90}")

    all_pass = True
    results = []

    for n, m, seed, scenario, use_dynamic in TEST_CASES:
        res = run_test(n, m, seed, scenario, use_dynamic)
        results.append(res)

        status = "✓" if res["feasible"] else "✗ FAIL"
        if not res["feasible"]:
            all_pass = False

        print(f"{res['scenario']:>4} {res['n']:>4} {res['m']:>2} {res['seed']:>5}  "
              f"{status:>8}  "
              f"{res['tw_violations']:>3}  {res['stockout_violations']:>3}  "
              f"{res['capacity_violations']:>3}  {res['total_cost']:>14,.0f}  "
              f"{res['pop_size']:>4}  {res['generations']:>4}  "
              f"{res['elapsed']:>5.1f}s")

    print(f"{'='*90}")
    n_pass = sum(1 for r in results if r["feasible"])
    n_total = len(results)
    print(f"\nResult: {n_pass}/{n_total} feasible")

    if all_pass:
        print("ALL TESTS PASSED ✓")
    else:
        print("SOME TESTS FAILED ✗")
        for r in results:
            if not r["feasible"]:
                print(f"  FAIL: Scenario {r['scenario']} n={r['n']} seed={r['seed']} "
                      f"— TW={r['tw_violations']} SO={r['stockout_violations']} "
                      f"Cap={r['capacity_violations']}")
        sys.exit(1)
