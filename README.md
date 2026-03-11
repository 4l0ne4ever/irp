# IRP-TW-DT: Inventory Routing Problem with Time Windows & Dynamic Traffic

## Overview

**IRP-TW-DT** is a research project solving the Inventory Routing Problem with Time Windows and Dynamic Traffic in Hanoi. The project integrates real-world traffic models (IGP Ichoua 2003), OSRM road network distances, and a Hybrid Genetic Algorithm (HGA) metaheuristic with local search operators.

**Scenarios:**

- **Scenario A (Baseline):** Periodic routing (TW-split heuristic)
- **Scenario B (HGA without Time-Shift):** Hybrid GA + 2-opt only
- **Scenario C (HGA with Time-Shift):** Hybrid GA + Time-Shift + 2-opt

## Key Features

- ✅ **Real-world routing:** OSRM road distances + IGP time-dependent travel times (5-zone model)
- ✅ **Time windows:** Morning [8h, 12h] and Afternoon [14h, 18h] with 50/50 split
- ✅ **Multi-scale instances:** S (n=20), M (n=50), L (n=100) with 5 seeds each
- ✅ **Hybrid metaheuristic:** Two-part chromosome, TD-Split DP decoder, local search (2-opt + time-shift)
- ✅ **Detailed metrics:** Cost breakdown (%), feasibility checks, per-customer inventory traces, per-day insights
- ✅ **Visualization:** Folium maps with OSRM road geometry
- ✅ **Performance:** HGA for n=20-50 in ~1-2 min; decode (n=100) < 50ms

## Project Structure

```
.
├── README.md                 # This file
├── pyproject.toml            # Python project config
├── requirements.txt          # Dependencies
├── docs/
│   └── IRP_TW_DT_DevGuide.pdf # Technical specification
├── src/
│   ├── main.py              # CLI entry point
│   ├── core/                # Core data structures
│   │   ├── constants.py     # Problem parameters (T=7, Q=500, LAMBDA_TW=10K, etc.)
│   │   ├── instance.py      # Instance class
│   │   ├── solution.py      # Solution class
│   │   ├── traffic.py       # IGP time-dependent travel time
│   │   └── inventory.py     # Inventory tracking
│   ├── data/                # Data processing & instances
│   │   ├── distances.py     # OSRM Table API wrapper
│   │   ├── converter.py     # VRPTW JSON → IRP instance
│   │   ├── generator.py     # Random instance generation
│   │   └── irp-instances/   # 15 pre-computed instances (S/M/L × 5 seeds)
│   ├── solver/              # HGA metaheuristic
│   │   ├── chromosome.py    # Chromosome init/copy
│   │   ├── decode.py        # TD-Split DP decoder (→ routes + cost)
│   │   ├── fitness.py       # Evaluation function
│   │   ├── operators.py     # Crossover, mutation, repair
│   │   ├── local_search.py  # 2-opt + incremental time-shift
│   │   └── hga.py           # Main HGA loop (200 gen, pop=50)
│   ├── baselines/           # Baseline algorithms
│   │   ├── periodic.py      # Periodic TW-split routing
│   │   └── rmi.py           # RMI baseline
│   └── experiments/
│       ├── runner.py        # Experiment orchestration
│       ├── analysis.py      # Post-experiment analysis
│       └── visualize.py     # Folium map generation
└── tests/
    ├── test_integration.py  # End-to-end tests
    ├── test_inventory.py    # Inventory logic
    └── test_traffic.py      # Traffic model
```

## Installation

### Prerequisites

- Python 3.13+
- macOS/Linux environment
- OSRM API access (or local OSRM server)

### Setup

```bash
# Clone repository
git clone <repo-url>
cd AI\ /irp

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### Environment Variables (Optional)

Create a `.env` file in the project root:

```env
OSRM_BASE_URL=http://router.project-osrm.org
PYTHONPATH=
```

## Usage

### Run a Single Experiment

```bash
# Scenario C, S-scale (n=20), m=2 vehicles, seed=42
python3 -m src.main run --scenario C --n 20 --m 2 --seed 42 --output results

# Output:
# Results saved to: results/C_S_n20_seed42/
#   ├── result.json        # Raw metrics (JSON)
#   ├── metrics.txt        # Detailed 7-section report
#   ├── map.html           # Folium visualization
#   └── convergence.csv    # HGA fitness trajectory
```

### Run All Experiments (3 scenarios × 3 scales × 5 seeds = 45 instances)

```bash
python3 -m src.main batch --output results
# Estimated runtime: ~6 hours
# Individual runs: A_S_n20_seed42, B_M_n50_seed123, C_L_n100_seed456, ...
```

### Convert VRPTW Data to IRP

```bash
# Convert Hanoi test datasets to IRP instances
python3 -m src.main convert --source-csv-dir src/data/test-dataset --output converted_instances
```

### Visualize Solution

```bash
# Generate Folium map for solution
python3 -m src.main visualize --instance S_n20_seed42 --solution results/C_S_n20_seed42/result.json --output map.html
```

### Run Tests

```bash
# All tests (33 tests, ~0.7s)
pytest tests/ -v

# Specific test file
pytest tests/test_integration.py -v

# Coverage
pytest tests/ --cov=src --cov-report=term-missing
```

## Parameters

| Constant              | Value                                        | Notes                                 |
| --------------------- | -------------------------------------------- | ------------------------------------- |
| **Horizon**           | T = 7 days                                   | Weekly planning                       |
| **Vehicle Capacity**  | Q = 500 units                                | Shared across all vehicles            |
| **Distance Cost**     | C_D = 3,500 VND/km                           | Distance-based penalty                |
| **Time Cost**         | C_T = 74,000 VND/h                           | Time-dependent penalty                |
| **TW Penalty**        | LAMBDA_TW = 10,000                           | TW violation penalty (DevGuide §3.4)  |
| **GA pop_size**       | 50                                           | Chromosome population (DevGuide §6.1) |
| **GA generations**    | 200                                          | Iterations (DevGuide §6.1)            |
| **GA crossover_prob** | 0.90                                         | Crossover probability (DevGuide §6.1) |
| **Departure slots**   | Morning: [6h, 7h, 8h], Afternoon: [12h, 13h] | Time window splits                    |

## Algorithms

### HGA (Hybrid Genetic Algorithm)

1. **Chromosome:** 2-part encoding
   - **Part Y:** Binary allocation {0,1}^(C×m) (customers × vehicles)
   - **Part π:** Giant tour permutation of all customers

2. **Decoder (TD-Split DP):**
   - Splits π into daily routes via dynamic programming
   - Assigns time windows (morning/afternoon) per delivery
   - Computes route costs with IGP travel times
   - Validates capacity/TW constraints; flags violations

3. **Local Search:**
   - **Scenario B:** 2-opt only (no time-shift per DevGuide §4.3)
   - **Scenario C:** Time-Shift + 2-opt
     - Time-Shift: Incremental evaluation (re-decodes 2 affected days only)
     - 2-opt: Swap route order within each day

4. **Fitness:** Cost + penalties
   ```
   Z = Σ(inventory) + Σ(distance × C_D) + Σ(travel_time × C_T)
       + LAMBDA_TW × (TW_violations + Stockout_violations)
   ```

### IGP Traffic Model (Ichoua 2003)

5 time-dependent speed profiles (km/h):

- **Night (0h-6h):** 27 km/h
- **Morning Peak (6h-9h):** 15 km/h
- **Business (9h-17h):** 19 km/h
- **Evening Peak (17h-20h):** 14 km/h
- **Evening (20h-0h):** 21 km/h

## Output Files

### result.json (Metrics)

```json
{
  "scenario": "C",
  "n": 20,
  "feasible": true,
  "total_cost": 4229866,
  "cost_inventory": 2867862,
  "cost_distance": 632441,
  "cost_time": 729562,
  "cost_pct_inventory": 67.8,
  "cost_pct_distance": 15.0,
  "cost_pct_time": 17.2,
  "tw_compliance_rate": 100.0,
  "tw_violations": 0,
  "stockout_violations": 0,
  "cpu_time_sec": 69.0,
  "per_day": [...]
}
```

### metrics.txt (Detailed Report)

7-section report:

1. **Objective Function Breakdown** — Cost by component (VND + %)
2. **Feasibility** — Violation counts & compliance rate
3. **Delivery Statistics** — Total deliveries, per-customer average, distance
4. **Inventory Analysis** — Avg inventory %, per-customer traces (top 10)
5. **Per-Day Breakdown** — Daily deliveries, routes, distance
6. **Route Details** — Stops, arrival times, loads per day
7. **Performance** — CPU time, fitness value

### map.html (Folium Map)

Interactive Folium map with:

- Customer markers (clustered)
- Daily routes with OSRM geometry
- Depot position
- Route direction indicators

### convergence.csv

HGA fitness trajectory:

```csv
generation,best_fitness,avg_fitness,feasible_count,time_sec
0,4864447,5887096,38,0.1
50,4440471,5931821,37,17.2
100,4440471,5735715,39,35.7
...
199,4229866,5403596,48,68.7
```

## Key Findings (Preliminary)

| Scenario         | Time | Feasible | Cost (4-fig) | Notes                                          |
| ---------------- | ---- | -------- | ------------ | ---------------------------------------------- |
| **A (Baseline)** | <1s  | ✓        | ~4,500K      | Periodic routes; no optimization               |
| **B (2-opt)**    | ~45s | ✓        | ~4,350K      | Faster convergence; no time-shift              |
| **C (HGA+TS)**   | ~70s | ✓        | ~4,230K      | Best cost; time-shift exploits dynamic traffic |

## Troubleshooting

### OSRM API Connection

- Check: `python3 -c "from src.data.distances import osrm_distance; print(osrm_distance(10.77, 106.70, 10.81, 106.69))"`
- If fails, use local OSRM server or pre-computed distances in `irp-instances/`

### Slow Experiments

- HGA runtime depends on instance size (n) and vehicle count (m)
- S-scale (n=20, m=2): ~60-90s
- M-scale (n=50, m=3): ~2-3 min
- L-scale (n=100, m=5): ~5+ min

### Tests Fail

```bash
# Verbose output + stop on first failure
pytest tests/ -vvs -x

# Check Python version
python3 --version  # Must be ≥3.13
```

## Contributing & Development

### Code Style

- Black formatter (line length: 100)
- Type hints encouraged
- Docstrings for all functions

### Adding New Instances

```bash
# Generate 5 random instances (S-scale, n=20)
python3 -m src.main generate --n 20 --m 2 --num 5 --output new_instances

# Convert from VRPTW JSON
python3 -m src.main convert --source-csv-dir data/ --output instances/
```

### Running Profiler

```bash
# Profile HGA decode speed
python3 -m cProfile -s cumulative -m src.main run --scenario C --n 100 --m 5 --seed 1 --output /tmp/results
```

## References

- **DevGuide:** [docs/IRP_TW_DT_DevGuide.pdf](docs/IRP_TW_DT_DevGuide.pdf)
- **OSRM:** [Project-OSRM](http://project-osrm.org)
- **IGP Model:** Ichoua et al. (2003). "Vehicle Routing under Time-Dependent Travel Times"
- **HGA:** Hart & Lamont (1994). "Handbook of Genetic Algorithms"

## License

MIT License — See LICENSE file for details.


