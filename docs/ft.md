# IRP-TW-DT — Master Implementation Plan

**Stack:** React (Vite) + FastAPI + Kafka (KRaft, local)  
**Audience:** Developer  
**Scope:** Full system — UI, backend, Kafka integration, simulation replay  
**Solver:** Unchanged except one modification to `hga.py`

---

## 1. Tổng quan kiến trúc

```
┌──────────────────────────────────────────────────────────┐
│                   FRONTEND (React + Vite)                 │
│  Sidebar controls │ KPI cards │ Convergence chart         │
│  Route map (Leaflet) │ Alert feed │ Upload form           │
└─────────────────────────┬────────────────────────────────┘
                          │ REST + WebSocket
                          │ ws://localhost:8000/ws
┌─────────────────────────▼────────────────────────────────┐
│                   BACKEND (FastAPI)                       │
│                                                           │
│  REST endpoints: /run, /instances, /result/{id}           │
│  WebSocket: bridge Kafka → frontend                       │
│  Background threads: solver + simulation replay           │
└────────────────┬─────────────────────────────────────────┘
                 │ produce / consume
┌────────────────▼─────────────────────────────────────────┐
│              KAFKA (local KRaft, no Zookeeper)            │
│  convergence-log │ vehicle-telemetry │ irp-alerts         │
└────────────────┬─────────────────────────────────────────┘
                 │ import trực tiếp
┌────────────────▼─────────────────────────────────────────┐
│               EXISTING SOLVER (src/)                      │
│  Instance, run_single, HGA, distances.py, visualize       │
└──────────────────────────────────────────────────────────┘
```

---

## 2. Files cần tạo hoặc sửa

```
backend/
  main.py                  # FastAPI app, WebSocket, REST endpoints
  kafka_bridge.py          # Producer/consumer wrappers
  job_manager.py           # Background thread management

src/
  solver/hga.py            # SỬA — thêm Kafka emit trong generation loop
  simulation/
    __init__.py            # Tạo mới
    replay.py              # Tạo mới — simulation replay module
  data/
    upload_loader.py       # Tạo mới — giữ nguyên từ plan v4
  experiments/
    runner.py              # SỬA — thêm run_single_from_instance()

frontend/
  src/
    hooks/useWebSocket.js  # WS connection + dispatch
    context/RunContext.jsx # Global state
    components/
      RunControls.jsx      # Sidebar
      KpiCards.jsx
      ConvergenceChart.jsx # Recharts
      RouteMap.jsx         # Leaflet
      AlertFeed.jsx
      UploadForm.jsx
  vite.config.js

requirements.txt           # Thêm fastapi, uvicorn, kafka-python, websockets
```

Tất cả `src/` hiện tại giữ nguyên trừ `hga.py` và `runner.py`.

---

## 3. Confirmed API contracts (từ source đã inspect)

### `Instance` dataclass

- 14 required fields, 3 optional — là `@dataclass`, không có custom `__init__`
- `dist` là constructor param, không phải post-assignment
- `demand` phải là numpy array shape `(n, T)` — không phải list
- `s` (service time) fill từ `SERVICE_TIME` constant hoặc per-customer CSV values
- Import constants đúng tên: `DEFAULT_T`, `DEFAULT_Q`, `SERVICE_TIME` — không phải `T`, `Q`
- Gọi `validate_instance(inst)` sau construction, raise `RuntimeError` nếu có lỗi

### `run_single`

- Nhận scenarios **P, A, B, C** — cả 4 đều valid
- Load instance từ disk, không nhận `Instance` object trực tiếp
- Không trả về run directory path — phải reconstruct
- Convergence data không có trong return dict — đọc `convergence.csv` từ disk

### `compute_osrm_distance_matrix`

- Input shape `(N, 2)` — `[lon, lat]`, index 0 là depot
- Raises `RuntimeError` khi fail — không silent return
- Auto-batch khi N > 100 — thêm ~16–25s latency

### `get_osrm_route_geometry`

- Trả về `[[lat, lon], ...]` hoặc `None` khi fail (không raise)
- Dùng trong simulation replay để lấy road geometry cho từng route

---

## 4. Sửa `src/solver/hga.py`

Đây là thay đổi duy nhất trong solver. Tại điểm trong generation loop đang append vào `convergence_log`, thêm một Kafka producer call song song.

Emit mỗi generation một message lên topic `convergence-log` với: `generation`, `best_fitness`, `avg_fitness`, `feasible_count`, `elapsed_sec`.

Wrap producer call trong try/except — emit failure là non-fatal, solver tiếp tục bình thường. Nếu Kafka không chạy thì chỉ log warning.

---

## 5. Thêm `run_single_from_instance()` vào `runner.py`

Thêm một function sau `run_single`. Nhận `Instance` đã build sẵn (dist đã set từ constructor), chạy solver, trả về `(result_dict, run_dir_path, solution)` và lưu `artifacts.pkl` (instance + solution) trong `run_dir` để Monitoring replay.

Khác với `run_single`:

- Không load từ disk
- Trả về run directory path trực tiếp (không cần reconstruct)
- `dist_matrix` không cần pass riêng — đã có trong `instance.dist`

Reuse `_make_result` và `_save_run_output` không thay đổi.

---

## 6. `src/data/upload_loader.py`

Hai public functions: `load_from_json(file_bytes)` và `load_from_csv(file_bytes, depot_lon, depot_lat, n, m)`.

Cả hai đều: parse input → build coords array → gọi OSRM → construct `Instance` với tất cả required fields → validate → return `(instance, dist_matrix)`.

Raise `RuntimeError` trên mọi failure. FastAPI endpoint bắt exception này và trả về HTTP 400 với message.

---

## 7. `src/simulation/replay.py`

Nhận `Instance` + `Solution` sau khi solver xong. Emit simulation theo thời gian thực (accelerated).

**Logic:**

1. Với mỗi route trong schedule, gọi `get_osrm_route_geometry` để lấy road path
2. Dùng IGP speed model (cùng logic với solver) để tính vị trí xe tại mỗi time step
3. Emit `vehicle-telemetry` messages vào Kafka theo sequence
4. Một consumer song song đọc telemetry, check violations, emit `irp-alerts`

**Simulation speed:** 1 giờ simulation = 1 giây real time (60x). Configurable qua parameter. Đủ để replay một ngày giao hàng trong ~14 giây.

**Fallback:** Nếu `get_osrm_route_geometry` trả về `None`, skip route geometry và emit xe teleport giữa các waypoints. Log warning rõ ràng.

---

## 8. Kafka topics

### `convergence-log`

Emit từ: `hga.py` trong generation loop  
Consumer: FastAPI → WebSocket → `ConvergenceChart` update live

Message fields: `run_id`, `generation`, `best_fitness`, `avg_fitness`, `feasible_count`, `elapsed_sec`

---

### `vehicle-telemetry`

Emit từ: `simulation/replay.py` sau khi solver xong  
Consumer: FastAPI → WebSocket → `RouteMap` animate xe

Message fields: `run_id`, `vehicle_id`, `day`, `lat`, `lon`, `status`, `next_customer_id`, `eta_h`, `planned_arrival_h`, `sim_time_h`

Status values: `en_route` / `delivering` / `done`

---

### `irp-alerts`

Emit từ: consumer của `vehicle-telemetry` khi phát hiện violation  
Consumer: FastAPI → WebSocket → `AlertFeed`

Alert types:

| Type             | Điều kiện                                          |
| ---------------- | -------------------------------------------------- |
| `tw_violation`   | `eta_h > planned_arrival_h + 0.25` (trễ > 15 phút) |
| `stockout_risk`  | Inventory customer sắp về 0 trước khi xe đến       |
| `route_complete` | Xe hoàn thành toàn bộ route trong ngày             |

---

## 9. FastAPI backend

### REST endpoints

| Endpoint           | Method | Mô tả                                                                  |
| ------------------ | ------ | ---------------------------------------------------------------------- |
| `/instances`       | GET    | List built-in instances trong `src/data/irp-instances/`                |
| `/run`             | POST   | Chạy solver, bắt đầu emit Kafka, trả về `run_id`                       |
| `/result/{run_id}` | GET    | Trả về result dict + map HTML sau khi run xong                         |
| `/upload`          | POST   | Nhận file JSON hoặc CSV, gọi `upload_loader`, trả về instance metadata |
| `/monitor/start`   | POST   | Body `{ run_id, day (0–6), speed_x }` — replay một ngày, emit telemetry |
| `/monitor/stop`    | POST   | Body `{ run_id }` — hủy replay đang chạy                                  |

### WebSocket `/ws`

Một connection duy nhất per client. Tất cả Kafka events đi qua một channel, phân biệt bằng field `type`:

| Type           | Trigger                                      |
| -------------- | -------------------------------------------- |
| `convergence`  | Mỗi HGA generation                           |
| `telemetry`    | Mỗi simulation time step                     |
| `alert`        | Mỗi khi consumer phát hiện violation         |
| `run_complete` | Solver (Planning) xong — bản đồ Folium + `artifacts.pkl` |
| `sim_complete` | Replay Monitoring cho một `day` xong (hoặc đã Stop)     |
| `run_error`    | Exception trong thread Planning                          |
| `monitor_error`| Exception khi load replay / `artifacts.pkl`             |

### Job lifecycle

Mỗi `/run` tạo `run_id` (UUID). Thread Planning chỉ chạy solver, emit `convergence-log`, lưu `artifacts.pkl`, rồi `run_complete`. Simulation theo ngày: `POST /monitor/start` với `{ run_id, day, speed_x }` — emit `vehicle-telemetry` / `irp-alerts`, kết thúc bằng `sim_complete` (hoặc `monitor_error`).

### OSRM error handling

Nếu OSRM fail ở upload phase, FastAPI trả về HTTP 400 với message rõ ràng. Frontend hiển thị error, không cho phép run. Không có fallback distances.

---

## 10. React frontend

**Stack:** React + Vite. Không cần Next.js — không có SSR requirement.

### State management

Một `RunContext` ở root, cung cấp:

- `runState`: `idle` / `running` / `simulating` / `complete` / `error`
- `currentResult`: KPI data sau khi run xong
- `convergenceData`: array các generation points, append live
- `telemetryData`: map từ `vehicle_id` → vị trí hiện tại
- `alerts`: array alerts, prepend (mới nhất lên đầu)

`useWebSocket` hook kết nối WS, parse message, dispatch vào context theo `type`.

### Layout

```
┌─────────────────────────────────────────────────────────┐
│  Header                                                  │
├──────────────┬──────────────────────────────────────────┤
│              │                                           │
│   Sidebar    │   KPI cards  (6 cards, show on complete)  │
│              │                                           │
│  Source:     ├──────────────────────────────────────────┤
│  ○ Built-in  │                                           │
│  ○ Upload    │   Convergence chart  (live update)        │
│              │   Recharts LineChart                      │
│  Scenario    │   Best + Average traces                   │
│  P/A/B/C     │                                           │
│              ├──────────────────────────────────────────┤
│  GA params   │                                           │
│  (ẩn P/A)   │   Route map  (Leaflet)                    │
│              │   Animate xe sau simulation phase         │
│  [▶ Run]     │                                           │
│              ├──────────────────────────────────────────┤
│              │   Alert feed  (scroll, newest first)      │
└──────────────┴──────────────────────────────────────────┘
```

### Components

| Component          | Thư viện                | Behavior                                                                                    |
| ------------------ | ----------------------- | ------------------------------------------------------------------------------------------- |
| `RunControls`      | —                       | Gọi `/run` hoặc `/upload` + `/run`. Disable khi `runState !== idle`                         |
| `KpiCards`         | —                       | 6 cards, render khi `runState === complete`                                                 |
| `ConvergenceChart` | Recharts                | Append data point mỗi `convergence` WS message. Ẩn cho scenario P/A                         |
| `RouteMap`         | Leaflet + React-Leaflet | Marker xe update vị trí mỗi `telemetry` message. Folium map HTML embed trong iframe sau run |
| `AlertFeed`        | —                       | List alerts với type badge + timestamp. Prepend mỗi `alert` message                         |
| `UploadForm`       | —                       | File input + depot fields nếu CSV. Gọi `/upload` endpoint                                   |

### Fast Demo preset

Sidebar có preset selector: Full Defaults / Fast Demo. Fast Demo set `pop_size=20, generations=40, time_limit=45`. Preset selector update number inputs ngay lập tức.

### Scenario P/A behavior

Khi chọn P hoặc A: ẩn GA Parameters section, ẩn ConvergenceChart. Hai scenario này không emit `convergence-log`.

---

## 11. Cài đặt Kafka local (KRaft, không Zookeeper)

1. Download Kafka binary 3.x từ kafka.apache.org
2. Format storage với UUID mới
3. Start broker bằng KRaft config
4. Tạo 3 topics: `convergence-log`, `vehicle-telemetry`, `irp-alerts`

Chỉ cần chạy một lần. Một Java process duy nhất, RAM ~512MB. Để background khi develop.

Python package: `pip install kafka-python`

---

## 12. Thứ tự implement

**Phase 1 — Backend foundation**

1. Kafka local setup + smoke test 3 topics
2. FastAPI skeleton: `/instances` và `/run` endpoint (chưa có Kafka)
3. `upload_loader.py`
4. `run_single_from_instance()` trong `runner.py`

**Phase 2 — Convergence pipeline (end-to-end đầu tiên)** 5. Kafka producer trong `hga.py` 6. `kafka_bridge.py` — producer/consumer wrappers 7. FastAPI WebSocket consumer cho `convergence-log` 8. React skeleton + `useWebSocket` hook + `ConvergenceChart` 9. Test: chạy solver, chart update live từng generation ✓

**Phase 3 — Simulation pipeline** 10. `simulation/replay.py` — emit `vehicle-telemetry` 11. Alert consumer — emit `irp-alerts` 12. FastAPI bridge cho 2 topics mới 13. `RouteMap` component animate xe 14. `AlertFeed` component

**Phase 4 — Polish** 15. `KpiCards`, full sidebar, upload flow 16. Error states, loading states 17. Fast Demo preset 18. Test toàn bộ flow end-to-end — **chỉ qua UI web hoặc gọi API** (`/docs`, `curl`); không bắt buộc script test trong repo; Kafka cài local theo §11 (không Docker trong plan này)

---

## 13. Lưu ý quan trọng

**Kafka failure là non-fatal:** Wrap tất cả producer calls trong try/except. Nếu Kafka không chạy, solver vẫn chạy bình thường, chỉ không có live updates.

**Thread safety:** Kafka `KafkaProducer` thread-safe với `kafka-python`. HGA và simulation chạy trong background threads của FastAPI — không cần lock cho producer.

**Simulation speed:** Mặc định 60x (1 giờ = 1 giây). Nếu frontend không kịp render, giảm xuống 30x. Consumer-side có thể throttle thêm nếu cần.

**Map HTML:** `visualize_solution()` trong runner vẫn generate `map.html` ra disk sau khi solve xong. React embed qua iframe thông qua `/result/{run_id}` endpoint. Không re-generate trong frontend.

**Run directory:** Tất cả outputs vào `/tmp/irp_runs/<run_id>/`. Cleanup giữ 10 runs gần nhất. Dùng `run_id` (UUID) thay vì timestamp để khớp với FastAPI job tracking.
