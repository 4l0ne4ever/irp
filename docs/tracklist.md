# IRP-TW-DT — Implementation Plan & Task Tracker

**Stack:** React (Vite) · FastAPI · Kafka (KRaft, local) · existing `src/` solver  
**Rule:** Solver logic untouched except `hga.py` (emit) and `traffic.py` (façade)

---

## Two modes

**Planning mode** — cấu hình và chạy HGA, xem kết quả tối ưu. Solver là trung tâm.

**Monitoring mode** — quan sát vận hành trong ngày. Khi vi phạm xảy ra, có thể trigger re-optimization cho các stops chưa giao. Không chỉ xem — có thể can thiệp.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                      React (Vite)                            │
│                                                              │
│  [ Planning ]                   [ Monitoring ]              │
│  ─────────────────────          ──────────────────────────  │
│  Sidebar controls               Day selector + timeline     │
│  Convergence chart              Vehicle / Customer panels   │
│  KPI cards                      Live ETA table              │
│  Static route map               Alert panel (primary)       │
│                                 Live route map              │
│                                 [Re-optimize] button        │
│                                 Plan revision indicator     │
└────────────────────────┬─────────────────────────────────────┘
                         │ REST + WebSocket
┌────────────────────────▼─────────────────────────────────────┐
│                       FastAPI                                │
│                                                              │
│  /run  /result  /upload  /instances                          │
│  /monitor/start  /monitor/stop  /monitor/replan              │
│  /ws                                                         │
│                                                              │
│  Background threads:                                         │
│  - HGA solver (Planning)                                     │
│  - Simulation replay (Monitoring)                            │
│  - Alert consumer (Monitoring)                               │
│  - Re-optimization with warm start (on demand)               │
└──────────────────┬───────────────────────────────────────────┘
                   │ produce / consume
┌──────────────────▼───────────────────────────────────────────┐
│                  Kafka (KRaft, local)                         │
│                                                              │
│  convergence-log      ← HGA emits per generation            │
│  vehicle-telemetry    ← replay.py emits per time step       │
│  irp-alerts           ← alert consumer on violation         │
│  replan-events        ← re-optimization results             │
└──────────────────┬───────────────────────────────────────────┘
                   │ import
┌──────────────────▼───────────────────────────────────────────┐
│                  src/ solver                                  │
│                                                              │
│  traffic.py  →  TravelTimeModel façade                       │
│    └── IGPModel (existing, default)                          │
│    └── MockAPIModel (inject JSON, simulate real API)         │
│                                                              │
│  distances.py · instance.py · hga.py · runner.py            │
└──────────────────────────────────────────────────────────────┘
```

**WebSocket message types:**

| Type              | Mode                  | Trigger                                    |
| ----------------- | --------------------- | ------------------------------------------ |
| `convergence`     | Planning              | Mỗi HGA generation                         |
| `run_complete`    | Planning              | Solver xong                                |
| `run_error`       | Planning / Monitoring | Exception trong background thread          |
| `telemetry`       | Monitoring            | Mỗi simulation time step                   |
| `alert`           | Monitoring            | Violation phát hiện                        |
| `replan_started`  | Monitoring            | Re-optimization bắt đầu                    |
| `replan_complete` | Monitoring            | Re-optimization xong, revised schedule sẵn |
| `sim_complete`    | Monitoring            | Replay xong toàn bộ ngày                   |

---

## File map

| File                         | Action                                                           |
| ---------------------------- | ---------------------------------------------------------------- |
| `src/core/traffic.py`        | Modify — thêm `TravelTimeModel` façade; IGP trở thành một impl   |
| `src/solver/hga.py`          | Modify — add Kafka emit per generation; accept `TravelTimeModel` |
| `src/experiments/runner.py`  | Modify — add `run_single_from_instance()`                        |
| `src/data/upload_loader.py`  | Create                                                           |
| `src/simulation/__init__.py` | Create                                                           |
| `src/simulation/replay.py`   | Create                                                           |
| `backend/main.py`            | Create                                                           |
| `backend/kafka_bridge.py`    | Create                                                           |
| `backend/job_manager.py`     | Create                                                           |
| `backend/traffic_state.py`   | Create — TrafficStateStore (in-memory + TTL)                     |
| `config/traffic_mock.json`   | Create — mock traffic data, not committed as source of truth     |
| `frontend/src/`              | Create                                                           |
| `requirements.txt`           | Update                                                           |

---

## API contracts (confirmed from source)

### `Instance` dataclass

- `@dataclass` — 14 required fields, 3 optional
- `dist` là constructor param, không phải post-assignment
- `demand` phải là `np.ndarray shape (n, T)`
- `s` fills từ `SERVICE_TIME` hoặc per-customer CSV values
- Đúng tên constants: `DEFAULT_T`, `DEFAULT_Q`, `SERVICE_TIME`, `C_D`, `C_T`
- Gọi `validate_instance(inst)` sau construction, raise `RuntimeError` nếu có lỗi

### `run_single`

- Nhận P, A, B, C — cả 4 valid
- Load từ disk, không nhận `Instance` trực tiếp
- Không trả về run directory — reconstruct từ `SCALE_CONFIGS`
- Convergence data không có trong return dict — đọc `convergence.csv` từ disk

### `run_single_from_instance` (to be added)

- Nhận pre-built `Instance` (dist đã set tại construction)
- Trả về `(result_dict, run_dir_path)`
- Reuse `_make_result` và `_save_run_output` không đổi

### `compute_osrm_distance_matrix`

- Input: `np.ndarray (N, 2)` — `[lon, lat]`, index 0 = depot
- Raises `RuntimeError` khi fail
- Auto-batch N > 100 — thêm ~16–25s latency

### `get_osrm_route_geometry`

- Trả về `[[lat, lon], ...]` hoặc `None` — không raise
- Handle `None`: fallback waypoint teleport, log warning

---

## `TravelTimeModel` façade (`src/core/traffic.py`)

Tách solver khỏi nguồn dữ liệu traffic. Solver gọi façade, không gọi trực tiếp IGP constants.

**Interface:**

```
TravelTimeModel.duration_h(from_idx, to_idx, depart_h, dist_km) → float
TravelTimeModel.matrix_slice(od_pairs, depart_h) → np.ndarray
```

**Implementations:**

| Class          | Dùng khi         | Source                                                  |
| -------------- | ---------------- | ------------------------------------------------------- |
| `IGPModel`     | Default, offline | Existing hardcoded speed zones                          |
| `MockAPIModel` | Demo, thesis     | `config/traffic_mock.json` (simulate real API response) |

`IGPModel` là default — existing behavior không đổi. `MockAPIModel` đọc từ JSON file ngoài git, có `valid_until` và `source` metadata. File này có thể được cron update từ API thực nếu muốn, nhưng solver không biết và không cần biết.

**Không làm (scope ra ngoài thesis):**

- Stochastic SAA layer — nhân thời gian chạy 5–20x, không realistic
- Full Markov regime model
- Redis TrafficStateStore — in-memory đủ dùng cho local

---

## `TrafficStateStore` (`backend/traffic_state.py`)

In-memory store, đơn giản. Lưu `TrafficObservation` hiện tại với TTL. Không cần Redis.

Mỗi `TrafficObservation` có: `source`, `timestamp`, `valid_until`, `data` (speed factors per zone hoặc per OD pair), `confidence`.

Khi TTL hết hoặc có observation mới, store update. Simulation replay đọc từ store thay vì hardcode.

---

## Kafka topics

| Topic               | Emitted by             | Consumed by                                                    |
| ------------------- | ---------------------- | -------------------------------------------------------------- |
| `convergence-log`   | `hga.py`               | FastAPI → WS → ConvergenceChart                                |
| `vehicle-telemetry` | `simulation/replay.py` | FastAPI → WS → RouteMap, VehiclePanel, ETATable, AlertConsumer |
| `irp-alerts`        | alert consumer         | FastAPI → WS → AlertPanel + fan-out                            |
| `replan-events`     | re-optimization thread | FastAPI → WS → RouteMap update, PlanRevisionIndicator          |

### Alert types và fan-out

| Type             | Condition                          | Fan-out                                                                                        |
| ---------------- | ---------------------------------- | ---------------------------------------------------------------------------------------------- |
| `tw_violation`   | `eta_h > planned_arrival_h + 0.25` | AlertPanel · RouteMap xe đỏ · ETATable row đỏ · VehiclePanel badge · enable Re-optimize button |
| `stockout_risk`  | Inventory → 0 trước khi xe đến     | AlertPanel · CustomerPanel highlight                                                           |
| `route_complete` | Xe hoàn thành toàn bộ stops        | AlertPanel · VehiclePanel status done                                                          |

---

## Rolling horizon re-optimization

Đây là điểm biến Monitoring mode từ passive → interactive.

**Trigger:** user click "Re-optimize" sau khi `tw_violation` alert fire. Không tự động — user control.

**Flow:**

1. Frontend gọi `/monitor/replan` với `run_id` + `day` + `sim_time_h` hiện tại
2. Backend xác định các stops chưa giao tính từ `sim_time_h`
3. Build sub-instance chỉ gồm các stops đó + trạng thái inventory hiện tại
4. Chạy HGA với **warm start** từ giant tour hiện có (giảm thời gian so với cold start)
5. Emit `replan_started` → Kafka → WS
6. Khi xong, emit `replan_complete` kèm revised schedule
7. Frontend update RouteMap + ETATable theo plan mới
8. `plan_revision` counter tăng lên — hiển thị trên UI

**Giới hạn tần suất:** tối đa 1 re-plan mỗi 2 phút để tránh bão. Button disable trong cooldown.

**Warm start:** seed HGA population từ chromosome của run gốc thay vì khởi tạo random. Giảm thời gian hội tụ ~30–50% theo kinh nghiệm với các vấn đề tương tự.

---

## Backend endpoints

| Endpoint           | Method    | Description                                                 |
| ------------------ | --------- | ----------------------------------------------------------- |
| `/instances`       | GET       | List built-in instances                                     |
| `/run`             | POST      | Chạy solver với `TravelTimeModel` chỉ định, trả về `run_id` |
| `/result/{run_id}` | GET       | Result dict + map HTML                                      |
| `/upload`          | POST      | Parse JSON/CSV, trả về instance metadata                    |
| `/monitor/start`   | POST      | Bắt đầu simulation replay cho `run_id` + `day`              |
| `/monitor/stop`    | POST      | Dừng replay đang chạy                                       |
| `/monitor/replan`  | POST      | Trigger re-optimization từ `sim_time_h` hiện tại            |
| `/ws`              | WebSocket | Stream tất cả Kafka events                                  |

---

## Planning mode — UI

```
┌──────────────┬────────────────────────────────────────────────┐
│   Sidebar    │  KPI cards  (hiện sau run_complete)             │
│              ├────────────────────────────────────────────────┤
│  Source      │  Convergence chart  (Recharts, live update)    │
│  Scenario    │  Best + Average traces. Ẩn cho P/A             │
│  GA params   ├────────────────────────────────────────────────┤
│  (ẩn P/A)   │  Static route map  (Folium HTML, iframe)        │
│              ├────────────────────────────────────────────────┤
│  Traffic     │  [→ Go to Monitoring]  (enable sau run xong)   │
│  model:      │                                                │
│  [IGP ▼]     │                                                │
│  [Mock API]  │                                                │
│              │                                                │
│  [▶ Run]     │                                                │
└──────────────┴────────────────────────────────────────────────┘
```

Traffic model selector cho phép so sánh IGP vs MockAPI — relevant cho thesis argument về dynamic traffic.

---

## Monitoring mode — UI

```
┌──────────────────────────────────────────────────────────────┐
│  Day selector: [Day 0] [Day 1] ... [Day 6]                   │
│  Sim controls: [▶ Start]  [■ Stop]   Speed: [60x ▼]          │
│  Timeline:  6h ──────────────●──────────────── 18h           │
│  Plan revision: v1  (updated 14:32)   Traffic: IGP / Mock    │
├──────────────────────┬───────────────────────────────────────┤
│  Vehicle panel       │  Live route map  (Leaflet)            │
│                      │                                       │
│  V1  en_route   🟢   │  Xe di chuyển theo OSRM geometry      │
│  V2  delivering 🟢   │  Màu xe: xanh=on-time, đỏ=violated   │
│  V3  done       ⚫   │  Re-optimized route hiển thị khác màu │
│                      │  Stop markers: pending/done/violated  │
│  Load: 240/500       │                                       │
│  Stops: 4/7          │                                       │
├──────────────────────┼───────────────────────────────────────┤
│  ETA table           │  Alert panel  (primary)               │
│                      │                                       │
│  Stop  Plan  ETA  Δ  │  🔴 TW violation — V1 → C14          │
│  C12   9:30  9:35    │     ETA 10:45, window 10:30           │
│  C14   10:30 10:45 ← │     [Re-optimize remaining stops]     │
│        ↑ highlighted │                                       │
│  C07   11:00 11:02   │  🟡 Stockout risk — C08              │
│                      │                                       │
│                      │  ✅ Route complete — V2               │
├──────────────────────┴───────────────────────────────────────┤
│  Customer panel                                              │
│  C01 ✅ delivered    C08 🟡 at risk    C14 ⏳ waiting        │
└──────────────────────────────────────────────────────────────┘
```

"Re-optimize remaining stops" button xuất hiện trong AlertPanel khi có `tw_violation`. Disabled trong 2-minute cooldown sau mỗi re-plan. Plan revision indicator cập nhật khi `replan_complete` nhận được.

---

## Frontend state

**`RunContext`** (global):

- `planningState`: `idle` / `running` / `complete` / `error`
- `monitoringState`: `idle` / `simulating` / `replanning` / `complete`
- `currentRunId`: string | null
- `currentResult`: result dict
- `convergenceData`: array, append per `convergence`
- `selectedDay`: 0–6
- `trafficModel`: `igp` | `mock_api`

**`MonitoringContext`** (reset khi đổi day):

- `vehicles`: map `vehicle_id → { lat, lon, status, stops_done, stops_total, load }`
- `customers`: map `customer_id → { status, current_inventory }`
- `etaRows`: array `{ stop_id, planned_h, eta_h, delta_min, violated }`
- `alerts`: array, prepend
- `simTimeH`: drives timeline bar
- `planRevision`: int, increment on `replan_complete`
- `replanCooldown`: bool, true for 2min after replan

---

## Thứ tự implement

### Phase 1 — Backend foundation

- [ ] Kafka local setup (KRaft) — verify Java version trước
- [ ] Tạo 4 topics: `convergence-log`, `vehicle-telemetry`, `irp-alerts`, `replan-events`
- [ ] Smoke test topics với console producer/consumer
- [ ] `TravelTimeModel` façade trong `traffic.py` — IGP trở thành `IGPModel`
- [ ] `MockAPIModel` — đọc từ `config/traffic_mock.json`
- [ ] `upload_loader.py`
- [ ] `run_single_from_instance()` trong `runner.py`
- [ ] FastAPI skeleton — `/instances`, `/run`, `/upload`
- [ ] `job_manager.py` — UUID tracking, job state, background threads
- [ ] `traffic_state.py` — TrafficStateStore in-memory

### Phase 2 — Planning pipeline (first end-to-end)

- [ ] `kafka_bridge.py` — producer/consumer wrappers
- [ ] Kafka emit trong `hga.py` (non-fatal try/except)
- [ ] HGA nhận `TravelTimeModel` parameter — default `IGPModel`
- [ ] FastAPI WS consumer cho `convergence-log`
- [ ] React scaffold — Vite, folder structure, tab routing
- [ ] `useWebSocket` hook
- [ ] `RunContext`
- [ ] Planning mode layout — sidebar với traffic model selector
- [ ] `ConvergenceChart` — live append
- [ ] `KpiCards` — on `run_complete`
- [ ] Folium map HTML iframe
- [ ] "Go to Monitoring" button
- [ ] **Checkpoint: solver chạy → chart live → KPIs → switch to Monitoring ✓**

### Phase 3 — Monitoring pipeline

- [ ] `simulation/replay.py` — OSRM geometry, IGP time steps, emit telemetry
- [ ] Alert consumer — check violations, emit `irp-alerts`
- [ ] `/monitor/start` và `/monitor/stop`
- [ ] FastAPI WS bridge cho `vehicle-telemetry` và `irp-alerts`
- [ ] `MonitoringContext`
- [ ] Monitoring layout — day selector, timeline, sim controls, plan revision indicator
- [ ] `RouteMap` (Leaflet) — vehicle markers, alert highlights
- [ ] `VehiclePanel`, `ETATable`, `CustomerPanel`
- [ ] `AlertPanel` — fan-out đồng thời update 4 components
- [ ] **Checkpoint: planning → monitoring → replay → alerts fan-out ✓**

### Phase 4 — Rolling horizon

- [ ] `/monitor/replan` endpoint
- [ ] Sub-instance builder từ `sim_time_h` — chỉ lấy stops chưa giao
- [ ] Warm-start HGA từ chromosome hiện có
- [ ] Emit `replan_started` / `replan_complete` lên `replan-events`
- [ ] FastAPI WS bridge cho `replan-events`
- [ ] "Re-optimize" button trong AlertPanel — enable on `tw_violation`, disable on cooldown
- [ ] Frontend nhận `replan_complete` → update RouteMap + ETATable + planRevision
- [ ] 2-minute cooldown logic
- [ ] **Checkpoint: alert fire → replan → revised route trên map ✓**

### Phase 5 — Polish

- [ ] Upload flow — UploadForm, CSV depot fields
- [ ] Fast Demo preset — `pop=20, gen=40, time_limit=45`
- [ ] Ẩn GA params / ConvergenceChart cho P/A
- [ ] Simulation speed selector (30x / 60x / 120x)
- [ ] Error states và loading states
- [ ] Run directory cleanup — giữ 10 runs
- [ ] **Checkpoint: full flow với upload, tất cả scenarios, error cases ✓**

---

## Out of scope (future work)

- Stochastic SAA layer trong fitness function — nhân thời gian chạy 5–20x
- Real-time traffic API subscription (TomTom/HERE) — `MockAPIModel` đủ để demonstrate
- Redis TrafficStateStore — in-memory đủ cho local
- Automatic re-plan trigger — user-initiated là đủ và safer để demo
- Markov regime model

---

## Notes

- **Kafka failure non-fatal.** Wrap tất cả producer calls trong try/except.
- **`KafkaProducer` thread-safe** — không cần lock.
- **`IGPModel` là default** — behavior hiện tại không thay đổi nếu không chọn MockAPI.
- **Hai map:** Folium iframe (Planning, static) + Leaflet (Monitoring, live). Không merge.
- **`config/traffic_mock.json` không commit là source of truth** — chỉ là mock data với timestamp/TTL metadata, có thể swap bằng cron từ API thực.
- **OSRM errors block run** — HTTP 400 từ `/upload`, frontend không cho phép `/run`.
- **`MonitoringContext` reset khi đổi day** — tránh stale data.
