# Hướng Dẫn Setup và Chạy — IRP-TW-DT

## Mục lục

1. [Cài đặt môi trường](#1-cài-đặt-môi-trường)
2. [Chạy giao diện web (FastAPI + React + Kafka)](#2-chạy-giao-diện-web-fastapi--react--kafka)
3. [Cấu trúc thư mục](#3-cấu-trúc-thư-mục)
4. [Chạy thí nghiệm qua CLI](#4-chạy-thí-nghiệm-qua-cli)
5. [Chạy toàn bộ thí nghiệm (batch)](#5-chạy-toàn-bộ-thí-nghiệm-batch)
6. [Đọc kết quả](#6-đọc-kết-quả)
7. [Xuất dữ liệu JSON/CSV](#7-xuất-dữ-liệu-jsoncsv)
8. [Chuyển đổi dữ liệu VRPTW](#8-chuyển-đổi-dữ-liệu-vrptw)
9. [Chạy tests](#9-chạy-tests)
10. [Các tham số quan trọng](#10-các-tham-số-quan-trọng)
11. [Biến môi trường (tùy chọn)](#11-biến-môi-trường-tùy-chọn)
12. [Xử lý lỗi thường gặp](#12-xử-lý-lỗi-thường-gặp)
13. [Hướng dẫn riêng cho Windows](#13-hướng-dẫn-riêng-cho-windows)

---

## 1. Cài đặt môi trường

### Yêu cầu hệ thống

- Python **3.10+** (khuyến nghị 3.11–3.13)
- **Node.js 18+** (cho frontend Vite)
- **Apache Kafka** broker (mặc định `localhost:9092`) — realtime convergence, telemetry, cảnh báo
- Kết nối internet khi cần gọi OSRM (ma trận khoảng cách, hình học tuyến trên bản đồ)

### Bước 1 — Virtualenv

**macOS / Linux:**

```bash
python3 -m venv .venv
source .venv/bin/activate
```

**Windows:** `python -m venv .venv` rồi `.venv\Scripts\activate` (CMD/PowerShell).

### Bước 2 — Cài Python dependencies

```bash
pip install -r requirements.txt
```

### Bước 3 — Frontend dependencies

```bash
cd frontend
npm install
cd ..
```

### Kiểm tra nhanh

```bash
python3 -c "import numpy, fastapi; print('Python OK')"
```

---

## 2. Chạy giao diện web (FastAPI + React + Kafka)

### Kafka

- Broker: `localhost:9092` hoặc danh sách máy chủ trong `KAFKA_BOOTSTRAP_SERVERS`.
- Topic dùng trong luồng app: `convergence-log`, `vehicle-telemetry`, `irp-alerts`, … (thường tự tạo khi producer gửi lần đầu).
- Cài đặt KRaft / broker: tham chiếu tài liệu nội bộ project (ví dụ `docs/ft.md` nếu có).

### Terminal 1 — Backend API

**Luôn chạy từ thư mục gốc dự án** (chứa `backend/`, `src/`). Đặt `PYTHONPATH=.` để import `src.*` và `backend.*`.

```bash
cd /đường/dẫn/tới/irp
source .venv/bin/activate   # nếu dùng venv
export PYTHONPATH=.
export KAFKA_BOOTSTRAP_SERVERS=localhost:9092
uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
```

> **Lưu ý:** Viết **hai lệnh `export` trên hai dòng** (hoặc `export PYTHONPATH=. && export KAFKA_BOOTSTRAP_SERVERS=localhost:9092`). Tránh dán dính kiểu `export PYTHONPATH=.export KAFKA_...` — shell sẽ không set đúng biến.

- API docs: `http://127.0.0.1:8000/docs`
- Health: `GET http://127.0.0.1:8000/health`

### Terminal 2 — Frontend (Vite)

```bash
cd frontend
npm run dev
```

Mở URL hiển thị trên terminal (thường `http://localhost:5173`).

### Cấu hình API cho frontend

Nếu API không chạy cùng host/port mặc định, tạo `frontend/.env`:

```env
VITE_API_URL=http://127.0.0.1:8000
```

Sau đó chạy lại `npm run dev`. Giá trị này dùng cho REST và ảnh hưởng tới `GET /monitor/context` (bản đồ monitoring).

### Luồng sử dụng UI (tóm tắt)

1. Chọn instance (built-in hoặc upload), scenario, traffic model, tham số GA → **Run experiment**.
2. Chờ job **complete** → có thể tải kết quả; **Go to Monitoring** khi sẵn sàng.
3. **Monitoring:** chọn **ngày horizon**, tốc độ replay (×), **Start replay**; có Stop, inject traffic, re-plan (theo tính năng UI).
4. Đồng hồ / thanh thời gian trên UI nội suy theo đúng `speed_x` đã gửi lên `POST /monitor/start` (cùng quy ước với backend: mỗi giây thực ≈ `speed_x/60` giờ mô phỏng).

### Build frontend (production)

```bash
cd frontend
npm run build
npm run preview    # xem bản build cục bộ
```

---

## 3. Cấu trúc thư mục

```
irp/
├── backend/                 # FastAPI: main, job_manager, kafka_bridge, traffic…
├── frontend/                # React + Vite + Leaflet
├── src/
│   ├── main.py              # CLI: run, batch, convert
│   ├── core/                # Instance, Solution, traffic, constants
│   ├── data/                # generator, upload_loader, distances (OSRM)
│   ├── solver/              # HGA, decode, fitness, local_search…
│   ├── simulation/          # replay, route_geometry (OSRM polyline)
│   ├── experiments/         # runner, visualize
│   ├── messaging/           # Kafka producers
│   └── data/irp-instances/  # Instance benchmark (.npy)
├── tests/
├── scripts/                 # ví dụ e2e product
├── requirements.txt
├── HUONG_DAN.md
└── export_instances.py
```

---

## 4. Chạy thí nghiệm qua CLI

```bash
export PYTHONPATH=.
python3 -m src.main run --scenario C --n 20 --m 2 --seed 42 --output results
```

Kết quả trong `results/...` (result.json, map.html, convergence.csv, …).

---

## 5. Chạy toàn bộ thí nghiệm (batch)

```bash
export PYTHONPATH=.
python3 -m src.main batch --output results
```

Thời gian lâu (nhiều instance × scenario). Cần OSRM ổn định.

---

## 6. Đọc kết quả

- **Web:** KPI, biểu đồ convergence (B/C), sau khi xong lấy JSON qua `GET /result/{run_id}`.
- **File:** `result.json`, `map.html` trong thư mục run (CLI hoặc `/tmp/irp_runs/<run_id>/` mặc định — đổi bằng `IRP_RUNS_DIR`).

---

## 7. Xuất dữ liệu JSON/CSV

```bash
python3 export_instances.py
```

Xuất từ `src/data/irp-instances/` sang thư mục JSON/CSV tương ứng (xem script và comment trong code).

---

## 8. Chuyển đổi dữ liệu VRPTW

```bash
export PYTHONPATH=.
python3 -m src.main convert --source-csv-dir src/data/test-dataset --output src/data/irp-instances
```

Cần internet cho OSRM.

---

## 9. Chạy tests

```bash
export PYTHONPATH=.
pytest tests/ -v
```

Một số test gọi OSRM qua mạng; môi trường không có mạng hoặc OSRM lỗi có thể làm fail test tích hợp. Test e2e stack có thể dùng biến môi trường/stub theo `tests/test_e2e_stack.py`.

---

## 10. Các tham số quan trọng

- Solver / GA: `src/core/constants.py` (`GA_POP_SIZE`, `GA_GENERATIONS`, `GA_TIME_LIMIT`, …).
- Chi phí, penalty: cùng file và DevGuide trong `docs/`.

---

## 11. Biến môi trường (tùy chọn)

| Biến | Ý nghĩa |
|------|--------|
| `PYTHONPATH` | Đặt `.` khi chạy từ gốc repo (bắt buộc cho uvicorn / CLI). |
| `KAFKA_BOOTSTRAP_SERVERS` | Danh sách broker Kafka, mặc định thường `localhost:9092`. |
| `VITE_API_URL` | Trong `frontend/.env` — URL backend cho fetch/WebSocket bridge. |
| `IRP_RUNS_DIR` | Thư mục lưu run (mặc định `/tmp/irp_runs`). |
| `IRP_OSRM_GEOMETRY_TIMEOUT` | Timeout giây cho request hình học OSRM (replay / map context). |
| `IRP_E2E_REPLAY_NO_OSRM` | Đặt `1` để replay không gọi OSRM từng chặng (dùng cho e2e nhanh; xem `scripts/run_e2e_product.sh`). |

---

## 12. Xử lý lỗi thường gặp

- **`ModuleNotFoundError: src` / `backend`:** Chạy lệnh từ thư mục gốc `irp/` và `export PYTHONPATH=.`.
- **Realtime / biểu đồ trống:** Kiểm tra Kafka đã chạy và `KAFKA_BOOTSTRAP_SERVERS` trùng với broker.
- **Monitoring không có depot/khách trên map:** Kiểm tra `GET /monitor/context` (curl hoặc Network tab); thường do `VITE_API_URL` sai hoặc CORS/host.
- **Đường trên map gần như thẳng:** OSRM public có thể từ chối hoặc rate-limit; xem log server; tăng `IRP_OSRM_GEOMETRY_TIMEOUT` hoặc dùng OSRM riêng.
- **OSRM ma trận khoảng cách fail:** Kiểm tra mạng; không có fallback ma trận nội bộ.
- **`feasible = False`:** Thử tăng `m`, kiểm tra instance; OSRM lệch có thể ảnh hưởng.
- **pytest fail ở bài tích hợp OSRM:** Chạy có mạng hoặc bỏ qua file test đó khi offline.

---

## 13. Hướng dẫn riêng cho Windows

- Dùng `python` thay `python3` nếu môi trường chỉ có tên đó.
- Venv: `.venv\Scripts\activate.bat` hoặc `Activate.ps1`.
- API:

  ```cmd
  set PYTHONPATH=.
  set KAFKA_BOOTSTRAP_SERVERS=localhost:9092
  uvicorn backend.main:app --host 127.0.0.1 --port 8000
  ```

- Frontend: `cd frontend && npm run dev`.
- Đường dẫn có dấu cách: bọc trong ngoặc kép, ví dụ `cd "D:\...\irp"`.

---

_Tài liệu tham chiếu kỹ thuật: các file trong `docs/` (DevGuide, tracklist, …)._
