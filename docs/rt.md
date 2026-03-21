# IRP-TW-DT — Implementation Plan & Task Tracker

**Stack:** React (Vite) · FastAPI · Kafka (KRaft, local) · TomTom Traffic Flow API  
**Rule:** Solver logic untouched except `hga.py` (emit) and `traffic.py` (façade)

---

## Two modes

**Planning mode** — cấu hình và chạy HGA, xem kết quả tối ưu. Solver là trung tâm.

**Monitoring mode** — quan sát vận hành trong ngày với traffic thực từ TomTom. Hệ số tắc nghẽn thay đổi real-time → ETA update tự động → replan trigger khi lệch đủ ngưỡng.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                      React (Vite)                            │
│                                                              │
│  [ Planning ]                   [ Monitoring ]               │
│  ─────────────────────          ───────────────────────────  │
│  Sidebar controls               Day selector + timeline      │
│  Convergence chart              Traffic status bar           │
│  KPI cards                      Vehicle / Customer panels    │
│  Static route map               Live ETA table               │
│                                 Alert panel (primary)        │
│                                 Live route map               │
│                                 [Re-optimize] button         │
│                                 [Inject congestion] button   │
│                                 Plan revision indicator      │
└────────────────────────┬─────────────────────────────────────┘
                         │ REST + WebSocket
┌────────────────────────▼─────────────────────────────────────┐
│                       FastAPI                                 │
│                                                              │
│  /run  /result  /upload  /instances                          │
│  /monitor/start  /monitor/stop  /monitor/replan              │
│  /monitor/traffic/inject                                      │
│  /ws                                                         │
│                                                              │
│  Background threads:                                         │
│  - HGA solver (Planning)                                     │
│  - Simulation replay (Monitoring)                            │
│  - Alert + auto-replan consumer                              │
│  - Re-optimization with warm start                           │
└──────────────────┬───────────────────────────────────────────┘
                   │ produce / consume
┌──────────────────▼───────────────────────────────────────────┐
│                  Kafka (KRaft, local)                         │
│                                                              │
│  convergence-log      ← HGA emits per generation            │
│  vehicle-telemetry    ← replay.py emits per time step       │
│  irp-alerts           ← alert consumer on violation         │
│  replan-events        ← re-optimization results             │
│  traffic-updates      ← ingest.py emits on profile change   │
└──────────┬───────────────────────────────┬───────────────────┘
           │ import                         │ fetch
┌──────────▼──────────────┐   ┌────────────▼───────────────────┐
│     src/ solver          │   │   TomTom Traffic Flow API       │
│                          │   │                                 │
│  traffic.py façade       │   │  /flowSegmentData per coord     │
│   └── IGPModel (default) │   │  currentSpeed / freeFlowSpeed   │
│   └── TomTomModel        │   │  → congestion_factor per slot   │
│                          │   │                                 │
│  distances.py            │   │  Queried once before replay     │
│  instance.py             │   │  Cached in TrafficStateStore    │
│  hga.py · runner.py      │   │  Fallback: traffic_mock.json    │
└──────────────────────────┘   └─────────────────────────────────┘
```

**WebSocket message types:**

| Type              | Mode       | Trigger                                     |
| ----------------- | ---------- | ------------------------------------------- |
| `convergence`     | Planning   | Mỗi HGA generation                          |
| `run_complete`    | Planning   | Solver xong                                 |
| `run_error`       | Both       | Exception trong background thread           |
| `telemetry`       | Monitoring | Mỗi simulation time step                    |
| `traffic_update`  | Monitoring | TrafficStateStore nhận profile mới / inject |
| `alert`           | Monitoring | Violation phát hiện                         |
| `replan_started`  | Monitoring | Re-optimization bắt đầu                     |
| `replan_complete` | Monitoring | Revised schedule sẵn                        |
| `sim_complete`    | Monitoring | Replay xong toàn bộ ngày                    |

---

## File map

| File                         | Action                                                        |
| ---------------------------- | ------------------------------------------------------------- |
| `src/core/traffic.py`        | Modify — `TravelTimeModel` façade; `IGPModel` + `TomTomModel` |
| `src/solver/hga.py`          | Modify — Kafka emit per generation; accept `TravelTimeModel`  |
| `src/experiments/runner.py`  | Modify — add `run_single_from_instance()`                     |
| `src/data/upload_loader.py`  | Create                                                        |
| `src/simulation/__init__.py` | Create                                                        |
| `src/simulation/replay.py`   | Create                                                        |
| `backend/main.py`            | Create                                                        |
| `backend/kafka_bridge.py`    | Create                                                        |
| `backend/job_manager.py`     | Create                                                        |
| `backend/traffic_state.py`   | Create — TrafficStateStore in-memory + TTL                    |
| `backend/traffic_ingest.py`  | Create — TomTom fetch + factor compute                        |
| `config/traffic_mock.json`   | Create — fallback profile, not source of truth                |
| `config/api_keys.env`        | Create — gitignored                                           |
| `frontend/src/`              | Create                                                        |
| `requirements.txt`           | Update                                                        |

---

## TomTom Traffic Flow integration

### API được dùng

**TomTom Traffic Flow API** — `/traffic/services/4/flowSegmentData/absolute/10/json`

Trả về `currentSpeed` và `freeFlowSpeed` (km/h) cho một coordinate. Không cần OD pair — query per waypoint coordinate.

```
congestion_factor = currentSpeed / freeFlowSpeed
```

Factor = 1.0 là thông thoáng. Factor = 0.5 là tắc nặng, tốc độ chỉ bằng 50% freeflow.

Free tier: 2500 requests/ngày. Với n=20, có 21 waypoints × 7 time slots = 147 requests/profile. Rất thoải mái.

### Query strategy — batch trước replay, không query per step

Simulation chạy ở 60x speed. Gọi API live mỗi time step sẽ: (1) không đồng bộ được với sim_time_h, (2) đốt quota nhanh, (3) latency làm replay bị giật.

**Thay vào đó:** trước khi `/monitor/start`, `traffic_ingest.py` batch query TomTom cho 7 time slots (6h, 8h, 10h, 12h, 14h, 17h, 19h) × tất cả waypoint coordinates của instance. Tính factor trung bình per slot. Lưu vào `TrafficStateStore` dưới dạng day profile.

Trong replay loop, `get_factor(sim_time_h)` chỉ đọc từ cache — không gọi mạng.

### Congestion factor trong replay

```
Mỗi time step:
  factor = TrafficStateStore.get_factor(sim_time_h)
  actual_duration = igp_duration(dist_km, depart_h) * factor
  new_eta = last_stop_time + actual_duration + service_time

  Nếu factor thay đổi so với step trước:
    recalculate ETA tất cả stops còn lại
    emit telemetry với updated ETAs
    emit traffic_update (factor, source, sim_time_h)

  Nếu |new_eta - planned_arrival| > drift_threshold (20 phút):
    emit tw_violation alert
    nếu không trong cooldown → auto-trigger replan
```

### `traffic_ingest.py`

Trách nhiệm:

- `fetch_day_profile(coords, api_key, slots)` — batch query TomTom, trả về `{slot_h: factor}`
- `compute_factor(current_speed, free_flow_speed)` — simple ratio, clamp [0.3, 1.0]
- Lưu metadata per observation: `provider="tomtom"`, `timestamp`, `valid_until`, `request_id`
- Fallback về `traffic_mock.json` nếu API fail hoặc quota exceeded

### `TomTomModel` trong `traffic.py`

Implement `TravelTimeModel` façade. `duration_h()` = `IGPModel.duration_h()` × `congestion_factor` từ store.

`IGPModel` vẫn là default khi chạy Planning mode. `TomTomModel` active trong Monitoring mode khi profile đã được fetch.

### `TrafficStateStore` (`backend/traffic_state.py`)

In-memory, không cần Redis.

- `load_profile(day_profile)` — load từ ingest result, set TTL 24h
- `get_factor(sim_time_h)` — linear interpolate giữa 2 slots gần nhất
- `inject_event(from_h, to_h, factor, label)` — override profile trong khoảng thời gian, emit `traffic-updates` topic
- `get_current_observation()` — trả về factor + source + timestamp cho UI display

### Fallback

Nếu TomTom API fail (network error, 429, quota hết):

- Log warning rõ ràng
- Load `config/traffic_mock.json` làm fallback profile
- UI hiển thị `Traffic: Mock (TomTom unavailable)` thay vì `Traffic: TomTom Live`
- Replay vẫn chạy bình thường

---

## Auto-replan trigger

Ngoài user-initiated replan, có automatic trigger khi congestion đủ xấu:

**Conditions (tất cả phải thỏa):**

1. `factor` drop > 30% so với profile ban đầu tại slot đó — tức là worse than expected
2. Ít nhất 1 stop có ETA drift > 20 phút so với `planned_arrival`
3. Không trong cooldown (2 phút từ lần replan cuối)
4. Simulation đang chạy, không phải paused

**Phân biệt với user replan:**

- Alert type: `auto_replan_triggered` (khác `user_replan_triggered`)
- UI hiển thị: "Auto-replan — congestion detected" thay vì "Re-optimizing..."
- Cả hai đi qua cùng replan pipeline

---

## Inject congestion event (demo feature)

`/monitor/traffic/inject` — POST với `{ from_h, to_h, factor, label }`.

Dùng để demo live trước committee: inject một sự kiện tắc đường đột xuất trong khi replay đang chạy, xe bị delay, alert fire, replan trigger. Timing hoàn toàn controllable.

Ví dụ inject: `{ from_h: 8.5, to_h: 9.5, factor: 0.35, label: "Accident Cầu Giấy" }`.

UI có button "Inject Congestion" với preset scenarios để demo nhanh.

---

## Kafka topics

| Topic               | Emitted by          | Consumed by                                                    |
| ------------------- | ------------------- | -------------------------------------------------------------- |
| `convergence-log`   | `hga.py`            | FastAPI → WS → ConvergenceChart                                |
| `vehicle-telemetry` | `replay.py`         | FastAPI → WS → RouteMap, VehiclePanel, ETATable, AlertConsumer |
| `irp-alerts`        | alert consumer      | FastAPI → WS → AlertPanel + fan-out 4 components               |
| `replan-events`     | replan thread       | FastAPI → WS → RouteMap update, ETATable, PlanRevision         |
| `traffic-updates`   | `traffic_ingest.py` | FastAPI → WS → TrafficStatusBar, store update                  |

---

## Alert types và fan-out

| Type                    | Condition                          | Fan-out                                                                                 |
| ----------------------- | ---------------------------------- | --------------------------------------------------------------------------------------- |
| `tw_violation`          | `eta_h > planned_arrival_h + 0.25` | AlertPanel · RouteMap xe đỏ · ETATable row đỏ · VehiclePanel badge · enable/auto replan |
| `stockout_risk`         | Inventory → 0 trước khi xe đến     | AlertPanel · CustomerPanel highlight vàng                                               |
| `route_complete`        | Xe xong tất cả stops               | AlertPanel · VehiclePanel status done                                                   |
| `auto_replan_triggered` | Auto-trigger conditions thỏa       | AlertPanel · monitoringState → `replanning`                                             |

---

## Backend endpoints

| Endpoint                  | Method    | Description                                                |
| ------------------------- | --------- | ---------------------------------------------------------- |
| `/instances`              | GET       | List built-in instances                                    |
| `/run`                    | POST      | Chạy solver với traffic model chỉ định, trả về `run_id`    |
| `/result/{run_id}`        | GET       | Result dict + map HTML                                     |
| `/upload`                 | POST      | Parse JSON/CSV, trả về instance metadata                   |
| `/monitor/start`          | POST      | Fetch TomTom profile → bắt đầu replay cho `run_id` + `day` |
| `/monitor/stop`           | POST      | Dừng replay                                                |
| `/monitor/replan`         | POST      | User-triggered replan từ `sim_time_h` hiện tại             |
| `/monitor/traffic/inject` | POST      | Inject congestion event vào TrafficStateStore              |
| `/monitor/context`        | GET       | Current job state, plan_revision, traffic source           |
| `/ws`                     | WebSocket | Stream tất cả Kafka events                                 |

---

## Monitoring mode — UI

```
┌──────────────────────────────────────────────────────────────┐
│  Day selector: [Day 0] [Day 1] ... [Day 6]                   │
│  Sim controls: [▶ Start]  [■ Stop]   Speed: [60x ▼]          │
│  Timeline:  6h ──────────────●──────────────── 18h           │
│  Traffic: TomTom Live  factor=0.72  (updated 14:32)          │
│  Plan: v2  (auto-replanned 14:35)  [Inject Congestion ▼]     │
├──────────────────────┬───────────────────────────────────────┤
│  Vehicle panel       │  Live route map  (Leaflet)            │
│                      │                                       │
│  V1  en_route   🟢   │  Xe di chuyển theo OSRM geometry      │
│  V2  delivering 🟡   │  Màu: xanh=on-time, vàng=at-risk      │
│  V3  done       ⚫   │        đỏ=violated                    │
│                      │  Re-optimized routes: màu cam         │
│  Load: 240/500       │  Stop markers: pending/done/violated  │
│  Stops: 4/7          │                                       │
├──────────────────────┼───────────────────────────────────────┤
│  ETA table           │  Alert panel  (primary)               │
│                      │                                       │
│  Stop  Plan  ETA   Δ │  🔴 TW violation — V1 → C14          │
│  C12   9:30  9:35    │     ETA 10:45, window closes 10:30    │
│  C14  10:30  10:45 ← │     Congestion factor: 0.48           │
│       ↑ highlighted  │     [Re-optimize remaining stops]     │
│  C07  11:00  11:02   │                                       │
│                      │  ⚡ Auto-replan — congestion detected  │
│                      │     Factor dropped 0.85→0.48 at 8:30  │
│                      │                                       │
│                      │  🟡 Stockout risk — C08              │
│                      │                                       │
│                      │  ✅ Route complete — V2               │
├──────────────────────┴───────────────────────────────────────┤
│  Customer panel                                              │
│  C01 ✅ delivered    C08 🟡 at risk    C14 ⏳ waiting        │
└──────────────────────────────────────────────────────────────┘
```

**Traffic status bar** — hiển thị: source (TomTom Live / Mock / Injected), factor hiện tại, thời điểm cập nhật cuối. Đổi màu theo factor: xanh ≥ 0.8, vàng 0.5–0.8, đỏ < 0.5.

**Inject Congestion dropdown** — preset scenarios: "Morning Peak Cầu Giấy", "Accident Hoàng Quốc Việt", "Custom...". Dùng cho demo live.

---

## Frontend state

**`RunContext`** (global):

- `planningState`: `idle` / `running` / `complete` / `error`
- `monitoringState`: `idle` / `simulating` / `replanning` / `complete`
- `currentRunId`: string | null
- `currentResult`: result dict
- `convergenceData`: array
- `selectedDay`: 0–6
- `trafficModel`: `igp` | `tomtom`

**`MonitoringContext`** (reset khi đổi day):

- `vehicles`: map `vehicle_id → { lat, lon, status, stops_done, stops_total, load }`
- `customers`: map `customer_id → { status, current_inventory }`
- `etaRows`: array `{ stop_id, planned_h, eta_h, delta_min, violated }`
- `alerts`: array, prepend
- `simTimeH`: drives timeline bar
- `planRevision`: int
- `replanCooldown`: bool
- `trafficFactor`: float — current congestion factor
- `trafficSource`: `"tomtom"` | `"mock"` | `"injected"`
- `trafficUpdatedAt`: ISO timestamp

---

## Thứ tự implement

### Phase 1 — Backend foundation

- [x] Kafka local setup (KRaft)
- [x] 4 topics ban đầu
- [ ] Thêm topic `traffic-updates`
- [x] `TravelTimeModel` façade trong `traffic.py` / `IGPModel`
- [ ] `TomTomModel` trong `traffic.py` — nhận `congestion_factor` từ store
- [ ] `traffic_ingest.py` — TomTom fetch + factor compute + fallback
- [ ] `traffic_state.py` — `load_profile`, `get_factor` (interpolate), `inject_event`
- [ ] `config/api_keys.env` — gitignored, TOMTOM_API_KEY
- [ ] `config/traffic_mock.json` — fallback profile với 7 slots
- [x] `upload_loader.py`
- [x] `run_single_from_instance()` trong `runner.py`
- [x] FastAPI skeleton
- [x] `job_manager.py`

### Phase 2 — Planning pipeline

- [x] `kafka_bridge.py`
- [x] Kafka emit trong `hga.py`
- [x] HGA nhận `TravelTimeModel`
- [x] FastAPI WS cho `convergence-log`
- [x] React scaffold, `useWebSocket`, `RunContext`
- [x] Planning mode layout + sidebar
- [x] `ConvergenceChart`, `KpiCards`
- [x] Folium map iframe
- [x] "Go to Monitoring" button
- [ ] Traffic model selector trên sidebar (IGP / TomTom)
- [ ] **Checkpoint: Planning mode hoàn chỉnh với traffic selector ✓**

### Phase 3 — Monitoring pipeline

- [x] `simulation/replay.py` — OSRM geometry, IGP time steps
- [ ] Sửa `replay.py` — query `TrafficStateStore.get_factor()` mỗi step thay vì IGP fixed
- [ ] ETA recalculate khi factor thay đổi
- [ ] Emit `traffic_update` WS message khi factor đổi
- [x] Alert consumer, `/monitor/start`, `/monitor/stop`
- [x] FastAPI WS bridge cho `vehicle-telemetry`, `irp-alerts`
- [x] `MonitoringContext`, Monitoring layout
- [x] `RouteMap`, `VehiclePanel`, `ETATable`, `CustomerPanel`, `AlertPanel`
- [x] Alert fan-out 4 components
- [ ] Thêm `trafficFactor`, `trafficSource` vào `MonitoringContext`
- [ ] `TrafficStatusBar` component
- [ ] FastAPI WS bridge cho `traffic-updates`
- [ ] `/monitor/start` gọi `traffic_ingest.fetch_day_profile` trước khi start replay
- [ ] **Checkpoint: replay với adaptive factor → ETA update → fan-out ✓**

### Phase 4 — Rolling horizon

- [x] `/monitor/replan`, sub-instance builder, warm-start HGA
- [x] `replan_started` / `replan_complete` emit
- [x] Frontend nhận `replan_complete` → update RouteMap + ETATable
- [x] 2-minute cooldown
- [ ] Auto-replan trigger trong alert consumer — check 3 conditions
- [ ] Phân biệt `auto_replan_triggered` vs user-triggered trong UI
- [ ] `/monitor/traffic/inject` endpoint
- [ ] `TrafficStateStore.inject_event()` — override + emit `traffic-updates`
- [ ] "Inject Congestion" dropdown trên Monitoring UI với preset scenarios
- [ ] **Checkpoint: inject event → factor drop → auto-replan → revised route ✓**

### Phase 5 — Polish

- [x] Run directory cleanup
- [ ] Upload flow — UploadForm, CSV depot fields
- [ ] Fast Demo preset — `pop=20, gen=40, time_limit=45`
- [ ] Ẩn GA params / ConvergenceChart cho P/A
- [ ] Simulation speed selector (30x / 60x / 120x)
- [ ] Error states + loading states
- [ ] TomTom fallback UI — hiển thị "Mock" khi API unavailable
- [ ] **Checkpoint: full flow, tất cả scenarios, error cases, inject demo ✓**

---

## Out of scope

- Stochastic SAA layer — nhân thời gian HGA 5–20x
- Redis TrafficStateStore
- Markov regime model
- Historical traffic API (chỉ dùng current-time TomTom, không retroactive)

---

## Notes

- **TomTom query timing:** chạy trước `/monitor/start`, không query per step trong replay. Latency fetch ~1–2s cho n=20.
- **Factor interpolation:** linear giữa 2 slots gần nhất. `get_factor(8.3)` interpolate giữa slot 8h và 10h.
- **Factor clamp:** [0.3, 1.0] — không để factor < 0.3 để tránh duration phi thực tế.
- **Kafka failure non-fatal** — tất cả producer calls trong try/except.
- **`IGPModel` là default** cho Planning mode — behavior không đổi.
- **Hai map:** Folium iframe (Planning) + Leaflet (Monitoring). Không merge.
- **`config/api_keys.env` gitignored** — không commit API key.
- **`MonitoringContext` reset khi đổi day** — tránh stale data.
- **Inject event là demo feature** — không cần persist qua session restart.
