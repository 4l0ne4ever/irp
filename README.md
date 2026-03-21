# IRP-TW-DT: Inventory Routing Problem with Time Windows & Dynamic Traffic

## Overview

**IRP-TW-DT** solves the Inventory Routing Problem with Time Windows and Dynamic Traffic in Hanoi. It uses real road distances (OSRM), time-dependent travel times (IGP Ichoua 2003), and a Hybrid Genetic Algorithm (HGA) with local search.

**Scenarios:**

- **P:** Periodic baseline (TW-split)
- **A (RMI):** Retailer-Managed Inventory baseline
- **B:** HGA without Time-Shift (2-opt only)
- **C:** HGA with Time-Shift + 2-opt

## Quick start (API + React UI)

Stack: **FastAPI** (REST + WebSocket), **React (Vite)** dashboard, **Kafka** for live convergence / telemetry / alerts. OSRM is required for distances (no fallback).

```bash
# From project root
pip install -r requirements.txt

# Terminal 1 — Kafka must expose bootstrap (default localhost:9092) and topics:
#   convergence-log, vehicle-telemetry, irp-alerts

# Terminal 2 — API (repo root on PYTHONPATH)
export PYTHONPATH=.
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000

# Terminal 3 — frontend
cd frontend && npm install && npm run dev
```

Open the Vite URL (e.g. `http://localhost:5173`). Optional: `VITE_API_URL=http://127.0.0.1:8000` in `frontend/.env`. Backend env: `KAFKA_BOOTSTRAP_SERVERS` (default `localhost:9092`), `CORS_ORIGINS` if needed.

Run artifacts: `/tmp/irp_runs/<run_id>/` (configurable via job manager).

## Key features

- **Web UI:** Built-in instances, upload, run B/C with GA params, live WebSocket feed (Kafka-forwarded convergence, telemetry, alerts), charts and map.
- **Real routing:** OSRM road distances + IGP time-dependent travel times (5 time zones).
- **Instance source:** Built-in `.npy` list, JSON upload, or CSV upload (**n** must equal data row count; **m** and depot from the form).
- **Scenarios:** P, A, B, C with configurable GA (pop size, generations, time limit).
- **Metrics:** Cost breakdown (%), feasibility, violations, deliveries, distance, inventory %, CPU time (in API result payload).

## Project structure

```
.
├── backend/                  # FastAPI: main, job_manager, kafka_bridge, realtime
├── frontend/                 # Vite + React dashboard
├── README.md
├── HUONG_DAN.md              # User guide (Vietnamese)
├── requirements.txt
├── export_instances.py       # Export .npy → JSON/CSV
├── docs/
├── src/
│   ├── main.py               # CLI: run, batch, convert
│   ├── messaging/            # Kafka producers (solver / replay)
│   ├── simulation/           # replay → telemetry + alerts
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

- **JSON:** Full instance (metadata with n, T, m; depot; customers with `daily_demand` length T; etc.). Parsed by `load_from_json`; OSRM builds the distance matrix.
- **CSV:** One data row per customer. Optional first line starting with `#` is skipped. You must set **n** in the UI/API equal to the number of data rows; set **m** and depot coordinates in the form. Columns: `customer_id`, `lon`, `lat`, `initial_inventory`, `min_inventory`, `tank_capacity`, `service_time_h`, `holding_cost_vnd`, `time_window_start_h`, `time_window_end_h`, `demand_day0`…`demand_day6`.

`export_instances.py` can emit a `# …` header line for convenience; **n** is still the row count after skipping that line.

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

**Kiểm tra stack (UI hoặc API, không script tự động trong repo):**

1. Cài Kafka local (KRaft) theo `docs/ft.md` §11 — hoặc bỏ qua nếu chỉ cần chạy solver (live chart/telemetry sẽ không có).
2. Chạy API + frontend như [Quick start](#quick-start-api--react-ui).
3. **Qua UI:** mở Vite, chọn instance → Run → xem chart / map / KPI sau khi xong.
4. **Qua REST:** mở `http://127.0.0.1:8000/docs` hoặc ví dụ:

```bash
curl -s http://127.0.0.1:8000/instances
curl -s -X POST http://127.0.0.1:8000/run \
  -H 'Content-Type: application/json' \
  -d '{"scenario":"C","seed":42,"pop_size":20,"generations":40,"time_limit":120,"source":"builtin","instance_key":"S_n20_seed42"}'
# dùng run_id trả về:
curl -s http://127.0.0.1:8000/result/<run_id>
```

## Troubleshooting

- **Slow upload:** First OSRM matrix build for many points can take 30–90s.
- **Run does not start:** Upload or select a built-in instance successfully, then POST `/run` (or use the UI).
- **OSRM errors:** Check network; public OSRM may rate-limit. No built-in fallback.
- **No live charts:** Ensure Kafka is running and the three topics exist; check `KAFKA_BOOTSTRAP_SERVERS`.

## References

- DevGuide in `docs/`
- OSRM: [project-osrm.org](http://project-osrm.org)
- IGP: Ichoua et al. (2003). "Vehicle Routing under Time-Dependent Travel Times"

## License

MIT — see LICENSE.
