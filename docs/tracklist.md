# IRP-TW-DT — Implementation Plan & Task Tracker

**Stack:** React (Vite) · FastAPI · Kafka (KRaft, local) · existing `src/` solver  
**Rule:** Solver logic untouched except one emit added to `hga.py`

**Tiến độ code (tóm tắt):** Các phase 1–4 đã implement xong trong repo (backend, frontend, messaging, replay). Kafka: cài broker local theo `docs/ft.md` §11 — **không dùng Docker trong plan/repo**. Kiểm tra: **UI web** hoặc **gọi REST** (`/health`, `/instances`, `/run`, `/result/...`); live chart/telemetry cần broker chạy tại `KAFKA_BOOTSTRAP_SERVERS`.

### Quy trình làm việc (đề xuất cho phase mới hoặc refactor)

1. **Backend và frontend tách nhau:** Trong một phase, ưu tiên xong **một phía** (API + contract ổn định *hoặc* UI với mock/fixture) rồi mới ghép. Bước **đồng bộ** là milestone riêng: cùng `RunIn`/JSON WS, URL env, CORS.
2. **Cổng nghiệm thu theo phase:** Chỉ bắt đầu phase tiếp theo khi checklist phase hiện tại đạt (dưới đây). Không “nhảy” phase.
3. **Cách test:** Ưu tiên **OpenAPI `/docs`**, `curl`, hoặc **TestClient** cho backend; **`npm run build`** + chạy dev cho frontend; tích hợp cuối phase bằng UI thật hoặc REST như `README.md`.

| Phase | Nghiệm thu backend (tối thiểu) | Nghiệm thu frontend (tối thiểu) | Đồng bộ |
| ----- | ------------------------------ | --------------------------------- | ------- |
| 1 | `GET /health`, `GET /instances`, `POST /upload` + `POST /run` trả `run_id`, `GET /result/{id}` tiến trạng; job chạy nền | Form upload + chọn built-in (có thể trỏ mock API trước) | `VITE_API_URL`, cookie/CORS, body khớp `RunIn` |
| 2 | Kafka consumer → WS đẩy `convergence` (broker bật); HGA emit | Chart nhận điểm từ WS / mock cùng shape message | Cùng `run_id` trên payload |
| 3 | Replay → `telemetry` / `alert` lên WS | Map + feed cập nhật từ WS | — |
| 4 | Lỗi `400` upload, `run_error` trên WS | KPI, preset, ẩn GA cho P/A | Một lượt chạy UI từ đầu đến cuối |

---

## Architecture

```
React (Vite)
  └─ REST + WebSocket ──► FastAPI
                              ├─ produce ──► Kafka
                              │                ├── convergence-log
                              │                ├── vehicle-telemetry
                              │                └── irp-alerts
                              └─ consume ◄─── Kafka
                              └─ import ────► src/ solver
```

**WebSocket message types:** `convergence` · `telemetry` · `alert` · `run_complete` · `run_error`

---

## File map

| File                         | Status                         |
| ---------------------------- | ------------------------------ |
| `src/solver/hga.py`          | Done — Kafka emit per generation |
| `src/experiments/runner.py`  | Done — `run_single_from_instance()` |
| `src/data/upload_loader.py`  | Done                           |
| `src/simulation/__init__.py` | Done                           |
| `src/simulation/replay.py`   | Done                           |
| `backend/main.py`            | Done                           |
| `backend/kafka_bridge.py`    | Done                           |
| `backend/job_manager.py`     | Done                           |
| `frontend/` (Vite app)       | Done — gồm `RunControls.jsx`, `UploadForm.jsx`, các component chart/map |
| `requirements.txt`           | Done                           |
| `frontend/.env.example`      | Done — `VITE_API_URL` mẫu                                  |

---

## API contracts (confirmed from source)

### `Instance` dataclass

- `@dataclass` — 14 required fields, 3 optional with defaults
- `dist` is a **constructor param**, not post-assignment
- `demand` must be `np.ndarray shape (n, T)` — not a list
- `s` fills from `SERVICE_TIME` constant or per-customer CSV values
- Correct constant names: `DEFAULT_T`, `DEFAULT_Q`, `SERVICE_TIME`, `C_D`, `C_T`
- Always call `validate_instance(inst)` after construction — raise `RuntimeError` if errors

### `run_single`

- Accepts P, A, B, C — all valid
- Loads from disk only — cannot accept `Instance` directly
- Does **not** return run directory path — reconstruct from `SCALE_CONFIGS`
- Convergence data not in return dict — read `convergence.csv` from disk

### `run_single_from_instance` (done)

- Accepts pre-built `Instance` (dist already set at construction)
- Returns `(result_dict, run_dir_path, solution)` — third value for replay
- Reuses `_make_result` and `_save_run_output` unchanged

### `compute_osrm_distance_matrix`

- Input: `np.ndarray (N, 2)` — `[lon, lat]`, index 0 = depot
- Returns `(matrix_km, True)` — raises `RuntimeError` on failure
- Auto-batches N > 100 — expect +16–25s latency

### `get_osrm_route_geometry`

- Returns `[[lat, lon], ...]` or **`None`** on failure (does not raise)
- Used in simulation replay for road geometry per route
- Handle `None` gracefully — fall back to waypoint teleport, log warning

---

## Kafka topics

| Topic               | Emitted by                      | Consumed by  | When                  |
| ------------------- | ------------------------------- | ------------ | --------------------- |
| `convergence-log`   | `hga.py`                        | FastAPI → WS | Each HGA generation   |
| `vehicle-telemetry` | `simulation/replay.py`          | FastAPI → WS | Each sim time step    |
| `irp-alerts`        | consumer of `vehicle-telemetry` | FastAPI → WS | On violation detected |

### Alert types

| Type             | Condition                                     |
| ---------------- | --------------------------------------------- |
| `tw_violation`   | `eta_h > planned_arrival_h + 0.25`            |
| `stockout_risk`  | Customer inventory → 0 before vehicle arrives |
| `route_complete` | Vehicle finishes all stops for the day        |

---

## Backend endpoints

| Endpoint           | Method    | Description                                                    |
| ------------------ | --------- | -------------------------------------------------------------- |
| `/instances`       | GET       | List built-in instances from `src/data/irp-instances/`         |
| `/run`             | POST      | Start solver + simulation, returns `run_id`                    |
| `/result/{run_id}` | GET       | Returns result dict + map HTML                                 |
| `/upload`          | POST      | Parse JSON/CSV, call `upload_loader`, return instance metadata |
| `/ws`              | WebSocket | Stream all Kafka events to frontend                            |

---

## Frontend components

| Component          | Library                 | Notes                                                                     |
| ------------------ | ----------------------- | ------------------------------------------------------------------------- |
| `RunControls`      | —                       | Sidebar. Disabled when `runState !== idle`                                |
| `KpiCards`         | —                       | 6 cards. Render on `run_complete`                                         |
| `ConvergenceChart` | Recharts                | Live append per `convergence` event. Hidden for P/A                       |
| `RouteMap`         | Leaflet + React-Leaflet | Animate vehicles per `telemetry`. Folium HTML in iframe for static result |
| `AlertFeed`        | —                       | Prepend per `alert` event, newest first                                   |
| `UploadForm`       | —                       | Show depot fields only for `.csv` uploads                                 |

**State:** Single `RunContext` at root. `useWebSocket` hook dispatches by `type` into context.

**Run states:** `idle` → `running` → `simulating` → `complete` / `error`

---

## Notes

- **Kafka failure is non-fatal.** Wrap all producer calls in try/except. Solver runs normally if Kafka is down.
- **`KafkaProducer` is thread-safe** — HGA and replay run in FastAPI background threads, no lock needed.
- **Simulation speed:** default 60x (1 hour = 1 second). Tune down to 30x if frontend can't keep up.
- **Map HTML:** `visualize_solution()` writes `map.html` to disk. React embeds via iframe through `/result/{run_id}`. Do not re-generate in frontend.
- **Run directory:** `/tmp/irp_runs/<run_id>/` using UUID. Keep last 10 runs, cleanup after each successful run.
- **OSRM errors block the run.** Return HTTP 400 from `/upload`. Frontend must not allow `/run` if instance has no valid dist matrix.

---

## Task Tracker

### Phase 1 — Backend foundation

- [x] Kafka local (KRaft, no Zookeeper) — môi trường dev: làm theo `docs/ft.md` §11 (binary Apache Kafka); topic có thể auto-create khi produce lần đầu
- [x] Topics: `convergence-log`, `vehicle-telemetry`, `irp-alerts`
- [x] Smoke / regression — **không script trong repo**; dùng UI hoặc `curl`/OpenAPI (xem `README.md`)
- [x] `src/data/upload_loader.py` — `load_from_json`, `load_from_csv`
- [x] Add `run_single_from_instance()` to `runner.py`
- [x] FastAPI — `/instances`, `/run`, `/upload`, `/result`, `/ws`, `/health`
- [x] `/upload` endpoint calling `upload_loader`
- [x] `backend/job_manager.py` — UUID tracking, background thread, job state dict

### Phase 2 — Convergence pipeline (first end-to-end)

- [x] `kafka_bridge.py` — consumer → `outbound_queue` → WebSocket
- [x] Add Kafka emit to `hga.py` generation loop (non-fatal try/except)
- [x] FastAPI WebSocket broadcasts Kafka-backed events
- [x] React app — Vite setup, folder structure
- [x] `useWebSocket` hook — connect, parse, dispatch by `type`
- [x] `RunContext` — state shape, reducer
- [x] `ConvergenceChart` — Recharts LineChart, live append
- [x] Run controls sidebar — built-in + upload
- [x] **Checkpoint:** run solver, chart updates live per generation ✓

### Phase 3 — Simulation pipeline

- [x] `src/simulation/replay.py` — OSRM geometry (or straight line + warning), telemetry
- [x] `kafka_bridge.py` — `vehicle-telemetry` and `irp-alerts` → WS
- [x] `RouteMap` — React-Leaflet, telemetry updates
- [x] Folium map HTML iframe embed after `run_complete`
- [x] `AlertFeed` — alerts from WS
- [x] **Checkpoint:** full flow — solve → animate → alerts ✓

### Phase 4 — Polish

- [x] `KpiCards` — render on `run_complete`
- [x] Upload flow — CSV depot fields, OSRM error handling (HTTP 400)
- [x] Fast Demo preset in UI
- [x] Hide GA params section for scenario P/A
- [x] Error states — `run_error` WS message, HTTP 400 from `/upload`
- [x] Loading states — spinners / disabled run while busy
- [x] Run directory cleanup — keep last 10
- [x] **Checkpoint:** E2E thủ công — UI + API ✓
