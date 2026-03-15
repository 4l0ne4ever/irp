# IRP-TW-DT: Inventory Routing Problem with Time Windows & Dynamic Traffic

## Overview

**IRP-TW-DT** solves the Inventory Routing Problem with Time Windows and Dynamic Traffic in Hanoi. It uses real road distances (OSRM), time-dependent travel times (IGP Ichoua 2003), and a Hybrid Genetic Algorithm (HGA) with local search.

**Scenarios:**

- **P:** Periodic baseline (TW-split)
- **A (RMI):** Retailer-Managed Inventory baseline
- **B:** HGA without Time-Shift (2-opt only)
- **C:** HGA with Time-Shift + 2-opt

## Quick start (Streamlit UI)

The main way to run experiments is the **Streamlit web app**: configure instance, run the solver, and view results in the browser.

```bash
# From project root
pip install -r requirements.txt
streamlit run app.py
```

Open `http://localhost:8501`. Then:

1. **Source:** Choose **Built-in instance** (set Scenario, n, m, then click **Generate**) or **Upload file** (JSON or CSV).
2. For CSV: first load computes **OSRM** distance matrix (30–90s for large n); a spinner explains the wait. Later runs use cache.
3. Set GA parameters if using Scenario B or C (Population size, Generations, Time limit).
4. Click **Run Experiment**. The **Run log** section streams solver output; when the run finishes, **Results** and **Detailed metrics** appear, plus solution map and (for B/C) convergence chart.

No export step: all output is shown on screen. Run artifacts are written under `/tmp/irp_runs` for the session.

## Key features

- **Streamlit UI:** Single screen for config, instance map, live run log, detailed results, solution map, convergence plot.
- **Real routing:** OSRM road distances + IGP time-dependent travel times (5 time zones).
- **Instance source:** Built-in generator (Hanoi, lognormal demand, water/exclusion checks) or upload JSON/CSV (n, m from file when possible).
- **Scenarios:** P, A, B, C with configurable GA (pop size, generations, time limit).
- **Metrics:** Cost breakdown (%), feasibility, violations, deliveries, distance, inventory %, CPU time, per-day stats.
- **Visualization:** Instance map (OSRM) and solution map (Folium + OSRM geometry).

## Project structure

```
.
├── app.py                    # Streamlit app (main entry for UI)
├── README.md
├── HUONG_DAN.md              # User guide (Vietnamese)
├── requirements.txt
├── export_instances.py       # Export .npy → JSON/CSV
├── docs/
├── src/
│   ├── main.py               # CLI: run, batch, convert
│   ├── core/                 # Instance, Solution, traffic, constants
│   ├── data/                 # generator, upload_loader, distances (OSRM)
│   ├── solver/               # HGA (hga, decode, fitness, local_search…)
│   ├── baselines/            # periodic, rmi
│   ├── milp/                 # validator
│   └── experiments/          # runner, visualize
└── tests/
```

## CLI usage (optional)

If you prefer the command line:

```bash
# Single run (e.g. Scenario C, n=20, m=2, seed=42)
python3 -m src.main run --scenario C --n 20 --m 2 --seed 42 --output results

# Batch (matrix of scenarios × scales × seeds)
python3 -m src.main batch --output results

# Convert VRPTW data to IRP
python3 -m src.main convert --source-csv-dir src/data/test-dataset --output converted_instances
```

Output: `results/<scenario>_<scale>_n<n>_seed<seed>/` with `result.json`, `map.html`, `convergence.csv`, etc.

## Upload file formats

- **JSON:** Full instance (metadata with n, T, m; depot; customers with lon, lat, inventory, demand, time windows, etc.). Used as-is.
- **CSV:** One row per customer. Optional first line: `# m=3` or `# m=3,depot_lon=105.86,depot_lat=20.99`. If present, n = number of data rows, m (and optionally depot) from that line. Otherwise enter depot manually; m defaults to 2. Columns: customer_id, lon, lat, initial_inventory, min_inventory, tank_capacity, service_time_h, holding_cost_vnd, time_window_start_h, time_window_end_h, demand_day0…demand_day6.

Export script `export_instances.py` writes CSV with the `# m=...,depot_lon=...,depot_lat=...` header so uploaded files carry n and m.

## Parameters (constants.py)

| Constant        | Value        | Notes              |
| --------------- | ------------ | ------------------ |
| T               | 7 days       | Planning horizon   |
| Q               | 500 units    | Vehicle capacity   |
| C_D             | 3,500 VND/km | Distance cost      |
| C_T             | 74,000 VND/h | Time cost          |
| GA_POP_SIZE     | 50           | Population size    |
| GA_GENERATIONS  | 200          | Generations        |
| GA_TIME_LIMIT   | 300 s        | Time limit (B/C)   |

## Tests

```bash
pytest tests/ -v
```

## Troubleshooting

- **Slow first load (upload):** OSRM matrix for many points takes 30–90s; spinner and caption explain. Subsequent loads (same file) use cache.
- **Run does not start:** Ensure an instance is ready (Generate or Upload + wait for load), then click **Run Experiment**.
- **OSRM errors:** Check internet; public OSRM server may rate-limit. No built-in fallback.

## References

- DevGuide in `docs/`
- OSRM: [project-osrm.org](http://project-osrm.org)
- IGP: Ichoua et al. (2003). "Vehicle Routing under Time-Dependent Travel Times"

## License

MIT — see LICENSE.
