"""
Statistical Analysis and Visualization for IRP-TW-DT experiments.
"""

import os
import logging
from typing import Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)

try:
    import pandas as pd
    HAS_PANDAS = True
except ImportError:
    HAS_PANDAS = False

try:
    from scipy import stats
    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False


def load_results(csv_path: str) -> Optional["pd.DataFrame"]:
    """Load results CSV into DataFrame."""
    if not HAS_PANDAS:
        logger.error("pandas required for analysis. Install: pip install pandas")
        return None
    return pd.read_csv(csv_path)


def compute_scenario_comparison(df: "pd.DataFrame") -> Dict:
    """
    Compute pairwise scenario comparisons.

    Returns dict with:
    - A_vs_P: savings from A over P
    - B_vs_A: savings from VMI scheduling (IRP-TW vs RMI)
    - C_vs_B: savings from dynamic traffic
    """
    results = {}

    for scale in df['scale'].unique():
        scale_df = df[df['scale'] == scale]
        results[scale] = {}

        for s1, s2, label in [('P', 'A', 'A_vs_P'), ('A', 'B', 'B_vs_A'), ('B', 'C', 'C_vs_B')]:
            df1 = scale_df[scale_df['scenario'] == s1].sort_values('seed')
            df2 = scale_df[scale_df['scenario'] == s2].sort_values('seed')

            if len(df1) == 0 or len(df2) == 0:
                continue

            costs1 = df1['total_cost'].values
            costs2 = df2['total_cost'].values

            # Savings %
            savings_pct = (costs1 - costs2) / costs1 * 100

            comparison = {
                'mean_savings_pct': float(np.mean(savings_pct)),
                'std_savings_pct': float(np.std(savings_pct)),
                'mean_cost_1': float(np.mean(costs1)),
                'mean_cost_2': float(np.mean(costs2)),
            }

            # Statistical test
            if HAS_SCIPY and len(costs1) >= 3:
                # t-test for A_vs_P, B_vs_A
                if label in ['A_vs_P', 'B_vs_A']:
                    t_stat, p_val = stats.ttest_rel(costs1, costs2)
                    comparison['t_stat'] = float(t_stat)
                    comparison['p_value'] = float(p_val)
                    comparison['test'] = 'paired t-test'
                else:
                    # Wilcoxon for B_vs_C (non-parametric)
                    try:
                        w_stat, p_val = stats.wilcoxon(costs1, costs2)
                        comparison['w_stat'] = float(w_stat)
                        comparison['p_value'] = float(p_val)
                        comparison['test'] = 'Wilcoxon signed-rank'
                    except ValueError:
                        comparison['test'] = 'insufficient data'

            results[scale][label] = comparison

    return results


def print_summary(df: "pd.DataFrame"):
    """Print formatted summary table."""
    print("\n" + "=" * 80)
    print("IRP-TW-DT Experiment Results Summary")
    print("=" * 80)

    for scale in sorted(df['scale'].unique()):
        scale_df = df[df['scale'] == scale]
        n = scale_df['n'].iloc[0]
        m = scale_df['m'].iloc[0]
        print(f"\n--- Scale {scale} (n={n}, m={m}) ---")

        for scenario in ['P', 'A', 'B', 'C']:
            s_df = scale_df[scale_df['scenario'] == scenario]
            if len(s_df) == 0:
                continue

            print(f"\n  Scenario {scenario}:")
            print(f"    Total Cost:     {s_df['total_cost'].mean():>14,.0f} ± {s_df['total_cost'].std():>10,.0f}")
            print(f"    Inventory Cost: {s_df['cost_inventory'].mean():>14,.0f}")
            print(f"    Distance Cost:  {s_df['cost_distance'].mean():>14,.0f}")
            print(f"    Time Cost:      {s_df['cost_time'].mean():>14,.0f}")
            print(f"    Feasible:       {s_df['feasible'].mean()*100:>6.0f}%")
            print(f"    CPU Time:       {s_df['cpu_time_sec'].mean():>8.1f}s")

    # Pairwise comparisons
    comparisons = compute_scenario_comparison(df)
    print("\n" + "=" * 80)
    print("Pairwise Comparisons (savings %)")
    print("=" * 80)

    for scale, comps in comparisons.items():
        print(f"\n  Scale {scale}:")
        for label, comp in comps.items():
            pval_str = f"p={comp.get('p_value', 'N/A'):.4f}" if 'p_value' in comp else ""
            print(f"    {label}: {comp['mean_savings_pct']:+.1f}% ± {comp['std_savings_pct']:.1f}%  {pval_str}")
