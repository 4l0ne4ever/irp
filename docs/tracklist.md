# IRP-TW-DT — Implementation Plan & Task Tracker

**Stack:** React (Vite) · FastAPI · Kafka (KRaft, local) · existing `src/` solver  
**Rule:** Solver logic untouched except one emit added to `hga.py`

**Trạng thái code:** Planning chỉ chạy solver → `run_complete` + `artifacts.pkl`. Monitoring: tab riêng, `POST /monitor/start|stop`, replay theo `day`, WS `sim_complete` / `monitor_error`. TW violation: consumer riêng `backend/telemetry_alert_worker.py` → topic `irp-alerts`.

---

## Two modes

**Planning mode** — user cấu hình và chạy HGA, xem kết quả tối ưu. Solver là trung tâm.

**Monitoring mode** — user quan sát vận hành trong ngày. Simulation replay là trung tâm. Phát hiện vi phạm, xem trạng thái từng xe và từng khách hàng theo thời gian thực.

Hai mode dùng chung backend và Kafka pipeline. Switch bằng tab trên header.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     React (Vite)                            │
│                                                             │
│  [ Planning ]                    [ Monitoring ]             │
│  ─────────────────────           ─────────────────────────  │
│  Sidebar controls                Day selector               │
│  Convergence chart               Vehicle status panel       │
│  Result KPI cards                Customer status panel      │
│  Static route map                Live ETA table             │
│                                  Timeline bar               │
│                                  Alert panel (primary)      │
│                                  Live route map             │
└──────────────────────────┬──────────────────────────────────┘
                           │ REST + WebSocket
┌──────────────────────────▼──────────────────────────────────┐
│                      FastAPI                                 │
│                                                             │
│  /run  /result  /upload  /instances  /monitor/start  /ws    │
│                                                             │
│  Background threads:                                        │
│  - HGA solver (Planning)                                    │
│  - Simulation replay (Monitoring)                           │
│  - Alert consumer (Monitoring)                              │
└──────────────────┬──────────────────────────────────────────┘
                   │ produce / consume
┌──────────────────▼──────────────────────────────────────────┐
│                 Kafka (KRaft, local)                         │
│                                                             │
│  convergence-log      ← HGA emits per generation           │
│  vehicle-telemetry    ← replay.py emits per time step      │
│  irp-alerts           ← alert consumer emits on violation  │
└──────────────────┬──────────────────────────────────────────┘
                   │ import trực tiếp
┌──────────────────▼──────────────────────────────────────────┐
│                   src/ solver (unchanged)                    │
│  Instance · run_single · HGA · distances · visualize        │
└─────────────────────────────────────────────────────────────┘
```

**WebSocket message types:**

| Type           | Mode       | Trigger                       |
| -------------- | ---------- | ----------------------------- |
| `convergence`  | Planning   | Mỗi HGA generation            |
| `run_complete` | Planning   | Solver xong                   |
| `run_error`    | Planning   | Exception trong solver thread |
| `telemetry`    | Monitoring | Mỗi simulation time step      |
| `alert`        | Monitoring | Violation phát hiện           |
| `sim_complete` | Monitoring | Replay xong toàn bộ ngày      |

---

## File map

| File                         | Action                                    |
| ---------------------------- | ----------------------------------------- |
| `src/solver/hga.py`          | Modify — add Kafka emit per generation    |
| `src/experiments/runner.py`  | Modify — add `run_single_from_instance()` |
| `src/data/upload_loader.py`  | Create                                    |
| `src/simulation/__init__.py` | Create                                    |
| `src/simulation/replay.py`   | Create                                    |
| `backend/main.py`            | Create                                    |
| `backend/kafka_bridge.py`    | Create                                    |
| `backend/telemetry_alert_worker.py` | Create — TW từ `vehicle-telemetry` → `irp-alerts` |
| `backend/job_manager.py`     | Create                                    |
| `frontend/src/`              | Create                                    |
| `requirements.txt`           | Update                                    |

---

## API contracts (confirmed from source)

### `Instance` dataclass

- `@dataclass` — 14 required fields, 3 optional
- `dist` là constructor param, không phải post-assignment
- `demand` phải là `np.ndarray shape (n, T)` — không phải list
- `s` fills từ `SERVICE_TIME` constant hoặc per-customer CSV values
- Đúng tên constants: `DEFAULT_T`, `DEFAULT_Q`, `SERVICE_TIME`, `C_D`, `C_T`
- Gọi `validate_instance(inst)` sau construction, raise `RuntimeError` nếu có lỗi

### `run_single`

- Nhận P, A, B, C — cả 4 valid
- Load từ disk, không nhận `Instance` trực tiếp
- Không trả về run directory path — reconstruct từ `SCALE_CONFIGS`
- Convergence data không có trong return dict — đọc `convergence.csv` từ disk

### `run_single_from_instance` (done)

- Nhận pre-built `Instance` (dist đã set tại construction)
- Trả về `(result_dict, run_dir_path, solution)` — lưu `artifacts.pkl` trong `run_dir`
- Reuse `_make_result` và `_save_run_output` không đổi

### `compute_osrm_distance_matrix`

- Input: `np.ndarray (N, 2)` — `[lon, lat]`, index 0 = depot
- Raises `RuntimeError` khi fail — không silent return
- Auto-batch N > 100 — thêm ~16–25s latency

### `get_osrm_route_geometry`

- Trả về `[[lat, lon], ...]` hoặc `None` — không raise
- Dùng trong replay để lấy road geometry
- Handle `None`: fallback waypoint teleport, log warning

---

## Kafka topics

| Topic               | Emitted by             | Consumed by                                                                           |
| ------------------- | ---------------------- | ------------------------------------------------------------------------------------- |
| `convergence-log`   | `hga.py`               | FastAPI → WS → ConvergenceChart                                                       |
| `vehicle-telemetry` | `simulation/replay.py` | FastAPI → WS → RouteMap, VehiclePanel, ETATable, AlertConsumer                        |
| `irp-alerts`        | alert consumer         | FastAPI → WS → AlertPanel, RouteMap highlight, ETATable highlight, VehiclePanel badge |

`irp-alerts` fan-out vào nhiều components đồng thời — đây là điểm khác biệt so với run UI thuần.

### Alert types

| Type             | Condition                               | Fan-out                                                                      |
| ---------------- | --------------------------------------- | ---------------------------------------------------------------------------- |
| `tw_violation`   | `eta_h > planned_arrival_h + 0.25`      | AlertPanel · RouteMap xe + stop đỏ · ETATable row đỏ · VehiclePanel badge đỏ |
| `stockout_risk`  | Inventory customer → 0 trước khi xe đến | AlertPanel · CustomerPanel highlight vàng                                    |
| `route_complete` | Xe hoàn thành toàn bộ stops trong ngày  | AlertPanel · VehiclePanel status done                                        |

---

## Backend endpoints

| Endpoint           | Method    | Description                                    |
| ------------------ | --------- | ---------------------------------------------- |
| `/instances`       | GET       | List built-in instances                        |
| `/run`             | POST      | Chạy solver, trả về `run_id`                   |
| `/result/{run_id}` | GET       | Result dict + map HTML                         |
| `/upload`          | POST      | Parse JSON/CSV, trả về instance metadata       |
| `/monitor/start`   | POST      | Bắt đầu simulation replay cho `run_id` + `day` |
| `/monitor/stop`    | POST      | Dừng replay đang chạy                          |
| `/ws`              | WebSocket | Stream tất cả Kafka events                     |

`/monitor/start` nhận `run_id` và `day` (0–6). Replay chỉ chạy schedule của ngày đó.

---

## Planning mode — UI

```
┌──────────────┬───────────────────────────────────────────────┐
│   Sidebar    │  KPI cards  (hiện sau run_complete)            │
│              ├───────────────────────────────────────────────┤
│  Source      │  Convergence chart  (Recharts, live update)   │
│  Scenario    │  Best + Average traces. Ẩn cho P/A            │
│  GA params   ├───────────────────────────────────────────────┤
│  (ẩn P/A)   │  Static route map  (Folium HTML, iframe)       │
│              │  Hiện sau run_complete                         │
│  [▶ Run]     ├───────────────────────────────────────────────┤
│              │  [→ Go to Monitoring]  (enable sau run xong)  │
└──────────────┴───────────────────────────────────────────────┘
```

"Go to Monitoring" chỉ enable sau `run_complete`. Click thì switch sang Monitoring tab và tự load `run_id` vừa chạy.

---

## Monitoring mode — UI

```
┌──────────────────────────────────────────────────────────────┐
│  Day selector: [Day 0] [Day 1] ... [Day 6]                   │
│  Sim controls: [▶ Start]  [■ Stop]   Speed: [60x ▼]          │
│  Timeline bar: 6h ─────────────●───────────────── 18h        │
├──────────────────────┬───────────────────────────────────────┤
│  Vehicle panel       │  Live route map  (Leaflet)            │
│                      │                                       │
│  V1  en_route   🟢   │  Xe di chuyển theo OSRM geometry      │
│  V2  delivering 🟢   │  Màu xe: xanh=on-time, đỏ=violated   │
│  V3  done       ⚫   │  Stop markers: pending/done/violated  │
│                      │  Alert highlights real-time           │
│  Load: 240/500       │                                       │
│  Stops: 4/7          │                                       │
├──────────────────────┼───────────────────────────────────────┤
│  ETA table           │  Alert panel  (primary feature)       │
│                      │                                       │
│  Stop  Plan   ETA  Δ │  🔴 TW violation — V1 → C14          │
│  C12   09:30  09:35  │     ETA 10:45, window closes 10:30    │
│  C14   10:30  10:45← │                                       │
│        ↑ highlighted │  🟡 Stockout risk — C08              │
│  C07   11:00  11:02  │     Inventory 12 units, ETA 13:20     │
│                      │                                       │
│                      │  ✅ Route complete — V2               │
├──────────────────────┴───────────────────────────────────────┤
│  Customer panel                                              │
│                                                              │
│  C01  ✅ delivered    C08  🟡 at risk    C14  ⏳ waiting     │
└──────────────────────────────────────────────────────────────┘
```

### Alert fan-out — cụ thể

Một `tw_violation` Kafka event → dispatch vào `MonitoringContext` → tất cả component subscribe đồng thời update:

- `AlertPanel` prepend entry
- `RouteMap` xe đổi màu đỏ + stop marker đổi đỏ
- `ETATable` row highlight đỏ
- `VehiclePanel` badge đỏ trên xe đó

Đây là lý do cần Kafka event-driven — không phải chỉ để pipe data vào một chỗ.

---

## `src/simulation/replay.py`

Nhận `Instance` + `Solution` + `day` index.

1. Với mỗi route trong `solution.schedule[day]`, gọi `get_osrm_route_geometry`
2. Tính vị trí xe tại mỗi time step dùng IGP speed model (cùng logic với solver)
3. Emit `vehicle-telemetry` messages theo sequence với `sim_time_h` tăng dần
4. Tính inventory depletion cho từng customer giữa các deliveries
5. Alert consumer chạy song song, check violations per telemetry message, emit `irp-alerts`

Simulation speed mặc định 60x. Configurable qua `/monitor/start` payload.

---

## Frontend state

**`RunContext`** (global, persist qua tab switch):

- `planningState`: `idle` / `running` / `complete` / `error`
- `monitoringState`: `idle` / `simulating` / `complete`
- `currentRunId`: string | null
- `currentResult`: result dict sau planning
- `convergenceData`: array, append per `convergence` event
- `selectedDay`: 0–6

**`MonitoringContext`** (reset khi đổi day):

- `vehicles`: map `vehicle_id → { lat, lon, status, stops_done, stops_total, load }`
- `customers`: map `customer_id → { status, current_inventory }`
- `etaRows`: array `{ stop_id, planned_h, eta_h, delta_min, violated }`
- `alerts`: array, prepend per alert
- `simTimeH`: current sim time, drives timeline bar

---

## Thứ tự implement

### Phase 1 — Backend foundation

- [x] Kafka local setup (KRaft) — verify Java version trước
- [x] Tạo 3 topics, smoke test console producer/consumer
- [x] `upload_loader.py`
- [x] `run_single_from_instance()` trong `runner.py`
- [x] FastAPI skeleton — `/instances`, `/run`, `/upload`
- [x] `job_manager.py` — UUID tracking, job state, background thread

### Phase 2 — Planning pipeline (first end-to-end)

- [x] `kafka_bridge.py` — producer/consumer wrappers
- [x] Kafka emit trong `hga.py` generation loop (non-fatal try/except)
- [x] FastAPI WS consumer cho `convergence-log`
- [x] React scaffold — Vite, folder structure, tab routing
- [x] `useWebSocket` hook — `WebSocketBridge` tách Planning vs Monitoring
- [x] `RunContext` — state shape
- [x] Planning mode layout — sidebar + `RunControls`
- [x] `ConvergenceChart` — Recharts, live append per `convergence` event
- [x] `KpiCards` — render on `run_complete`
- [x] Folium map HTML iframe embed
- [x] "Go to Monitoring" button — enable on `run_complete`
- [x] **Checkpoint: solver chạy → chart update live → KPIs hiện ✓**

### Phase 3 — Monitoring pipeline

- [x] `simulation/replay.py` — OSRM geometry, emit telemetry; replay theo `day`; `stop_event`
- [x] Alert consumer — `telemetry_alert_worker.py` (TW) + replay emit `stockout` / `route_complete`
- [x] `/monitor/start` và `/monitor/stop` endpoints
- [x] FastAPI WS bridge cho `vehicle-telemetry` và `irp-alerts`
- [x] `MonitoringContext` — state shape, reset on day change
- [x] Monitoring mode layout — day selector, sim time, speed, Start/Stop
- [x] `RouteMap` (Leaflet) — markers + highlight TW violation
- [x] `VehiclePanel` — status list (trong `MonitoringView`)
- [x] `ETATable` — planned vs ETA từ telemetry
- [x] `CustomerPanel` — risk từ alerts stockout
- [x] `AlertPanel` — `AlertFeed` trong monitoring
- [x] Alert fan-out — một `alert` WS cập nhật map + bảng ETA + list xe + feed
- [x] **Checkpoint: planning xong → monitoring → replay → alerts fan-out đồng thời ✓**

### Phase 4 — Polish

- [x] Upload flow — UploadForm, CSV depot fields, OSRM error handling
- [x] Fast Demo preset — `pop=20, gen=40, time_limit=45`
- [x] Ẩn GA params cho P/A, ẩn ConvergenceChart cho P/A
- [x] Simulation speed selector (30x / 60x / 120x)
- [x] Error states — `run_error` WS, HTTP 400 từ `/upload`
- [x] Loading states — tối thiểu: Run disabled + status text (`RunControls`); spinner OSRM / progress solver tùy chọn
- [x] Run directory cleanup — giữ 10 runs gần nhất
- [x] **Checkpoint: full flow với upload, tất cả scenarios, error cases ✓**
- [x] Product E2E (build + `vite preview` smoke + uvicorn thật + `scripts/e2e_product.py` HTTP/WS); `IRP_E2E_REPLAY_NO_OSRM=1` khi cần replay nhanh

---

## Notes

- **Kafka failure là non-fatal.** Wrap tất cả producer calls trong try/except. Solver chạy bình thường nếu Kafka down.
- **`KafkaProducer` thread-safe** — HGA và replay chạy trong FastAPI background threads, không cần lock.
- **Simulation speed:** 60x default. Giảm xuống 30x nếu frontend không kịp render.
- **Hai map khác nhau:** Folium HTML iframe trong Planning mode cho static result. Leaflet map trong Monitoring mode cho live animation. Không cố dùng một map cho cả hai.
- **OSRM errors block run.** HTTP 400 từ `/upload`, frontend không cho phép `/run` nếu không có dist matrix hợp lệ.
- **`MonitoringContext` reset khi đổi day** — tránh stale data từ ngày trước hiển thị trong panels.
