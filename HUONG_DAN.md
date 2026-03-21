# Hướng Dẫn Sử Dụng — IRP-TW-DT

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
11. [Xử lý lỗi thường gặp](#11-xử-lý-lỗi-thường-gặp)
12. [Hướng dẫn riêng cho Windows](#12-hướng-dẫn-riêng-cho-windows)

---

## 1. Cài đặt môi trường

### Yêu cầu hệ thống

- Python **3.10** trở lên (khuyến nghị 3.13)
- macOS, Linux **hoặc Windows 10/11**
- Kết nối internet (gọi OSRM API lấy khoảng cách đường bộ)

### Bước 1 — Tạo môi trường ảo

**macOS / Linux:**

```bash
python3 -m venv .venv
source .venv/bin/activate
```

**Windows (Command Prompt / PowerShell):**

```cmd
python -m venv .venv
.venv\Scripts\activate.bat
:: hoặc PowerShell:
.venv\Scripts\Activate.ps1
```

> **PowerShell:** Nếu gặp lỗi execution policy: `Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser`

### Bước 2 — Cài thư viện

```bash
pip install -r requirements.txt
```

### Kiểm tra

```bash
python3 -c "import numpy, pandas, folium, fastapi; print('OK')"
```

---

## 2. Chạy giao diện web (FastAPI + React + Kafka)

Giao diện chính: **API FastAPI** (REST + WebSocket), **React (Vite)**, luồng realtime qua **Kafka** (hội tụ HGA, telemetry, cảnh báo). Cần **Node.js** cho frontend.

### Yêu cầu Kafka

Broker mặc định `localhost:9092` (đổi bằng biến `KAFKA_BOOTSTRAP_SERVERS`). Topic: `convergence-log`, `vehicle-telemetry`, `irp-alerts` (thường auto-create khi có message đầu tiên). **Cài Kafka KRaft trên máy** theo `docs/ft.md` mục 11 — plan không dùng Docker trong repo; kiểm thử bằng **UI** hoặc **REST** (`/docs`, `curl`), không có script test tự động kèm theo.

### Khởi chạy

**Cửa sổ 1 — API (từ thư mục gốc `irp/`):**

```bash
export PYTHONPATH=.
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

**Cửa sổ 2 — Frontend:**

```bash
cd frontend
npm install
npm run dev
```

Mở URL Vite (thường `http://localhost:5173`). Nếu API không cùng host/port, đặt `VITE_API_URL` trong `frontend/.env` (ví dụ `http://127.0.0.1:8000`).

### Cấu hình và chạy (tóm tắt)

1. **Instance:** Chọn built-in từ danh sách, hoặc upload JSON / CSV. Với CSV: **n** phải bằng đúng số dòng dữ liệu (sau dòng `#` nếu có); nhập **m** và tọa độ depot trên form.
2. **Scenario P/A/B/C** và tham số GA (B/C).
3. **Chạy:** UI gọi API; WebSocket nhận sự kiện từ hàng đợi (Kafka bridge). Sau khi xong, tải kết quả qua `GET /result/{run_id}`. File run nằm dưới `/tmp/irp_runs/<run_id>/`.

### Lưu ý

- Nếu không có Kafka, API vẫn chạy được nhưng biểu đồ / cảnh báo realtime có thể trống.
- OSRM bắt buộc cho ma trận khoảng cách; không có fallback.

---

## 3. Cấu trúc thư mục

```
irp/
├── backend/                        # FastAPI, job_manager, kafka_bridge
├── frontend/                       # React + Vite
├── pyproject.toml
├── requirements.txt
├── README.md
├── HUONG_DAN.md                    # File này
├── export_instances.py             # Xuất .npy → JSON/CSV
│
├── docs/
│   └── decuong.tex
│
├── src/
│   ├── main.py                     # CLI: run, batch, convert
│   ├── core/                       # Instance, Solution, traffic, constants
│   ├── data/                       # generator, upload_loader, distances (OSRM)
│   ├── solver/                    # HGA (hga, decode, fitness, local_search…)
│   ├── baselines/                  # periodic, rmi
│   ├── milp/                       # validator
│   ├── experiments/                # runner, visualize
│   └── data/irp-instances/        # Benchmark .npy (S/M/L × seeds)
│   └── data/irp-instances-json/   # Bản JSON/CSV xuất từ export_instances.py
│
├── tests/
└── results/                        # Kết quả CLI (khi chạy batch/run)
```

---

## 4. Chạy thí nghiệm qua CLI

Có thể chạy một lần từ dòng lệnh (không qua web):

```bash
python3 -m src.main run --scenario C --n 20 --m 2 --seed 42 --output results
```

Kết quả: `results/C_S_n20_seed42/` (result.json, map.html, convergence.csv, …).

---

## 5. Chạy toàn bộ thí nghiệm (batch)

```bash
python3 -m src.main batch --output results
```

Chạy ma trận thí nghiệm (scenario × scale × seed). Thời gian ước tính vài giờ. Kết quả từng instance trong `results/<scenario>_<scale>_n<n>_seed<seed>/`.

---

## 6. Đọc kết quả

### Trên giao diện web

- KPI, biểu đồ hội tụ (B/C), bản đồ tuyến, luồng cảnh báo — dữ liệu realtime qua WebSocket (Kafka).
- Kết quả đầy đủ: JSON từ `GET /result/{run_id}` sau khi job xong.

### File result.json (CLI / thư mục kết quả)

Các trường chính: `scenario`, `n`, `m`, `feasible`, `total_cost`, `cost_inventory`, `cost_distance`, `cost_time`, `cost_pct_*`, `tw_violations`, `stockout_violations`, `capacity_violations`, `tw_compliance_rate`, `n_deliveries`, `total_distance_km`, `avg_inventory_level_pct`, `cpu_time_sec`, `per_day`, …

### File map.html

Mở bằng trình duyệt để xem bản đồ tương tác (depot, khách hàng, tuyến đường).

---

## 7. Xuất dữ liệu JSON/CSV

```bash
python3 export_instances.py
```

Xuất các instance trong `src/data/irp-instances/` sang `src/data/irp-instances-json/` (JSON + CSV). CSV có thể có dòng `# ...` (bị bỏ qua khi load); **n** = số dòng dữ liệu; **m** và depot nhập khi upload.

Cột CSV: `customer_id`, `lon`, `lat`, `initial_inventory`, `min_inventory`, `tank_capacity`, `service_time_h`, `holding_cost_vnd`, `time_window_start_h`, `time_window_end_h`, `demand_day0` … `demand_day6`.

---

## 8. Chuyển đổi dữ liệu VRPTW

```bash
python3 -m src.main convert --source-csv-dir src/data/test-dataset --output src/data/irp-instances
```

Cần internet để gọi OSRM. OSRM là nguồn khoảng cách duy nhất.

---

## 9. Chạy tests

```bash
pytest tests/ -v
```

Ví dụ test cụ thể: `pytest tests/test_integration.py -v`, `pytest tests/test_traffic.py -v`.

---

## 10. Các tham số quan trọng

Trong `src/core/constants.py`: `LAMBDA_TW`, `C_D`, `C_T`, `DEFAULT_Q`, `DEFAULT_T`, `GA_POP_SIZE`, `GA_GENERATIONS`, … Tham chiếu đầy đủ: DevGuide (`docs/`).

---

## 11. Xử lý lỗi thường gặp

- **ModuleNotFoundError 'src':** Chạy từ thư mục gốc dự án; với API dùng `PYTHONPATH=.` hoặc `python3 -m src.main ...`.
- **Load file chậm:** Lần đầu load CSV/JSON với n lớn phải gọi OSRM (30–90s).
- **Run không bắt đầu:** Đảm bảo đã chọn built-in hoặc upload thành công, rồi chạy từ UI hoặc `POST /run`.
- **Realtime trống:** Kiểm tra Kafka và topic; biến `KAFKA_BOOTSTRAP_SERVERS`.
- **feasible = False / tw_violations > 0:** Kiểm tra kết nối OSRM; thử tăng số xe `m`.
- **OSRM lỗi:** Kiểm tra internet; OSRM public server đôi khi giới hạn. Không có fallback nội bộ.

---

## 12. Hướng dẫn riêng cho Windows

- Dùng `python` thay cho `python3`.
- Kích hoạt venv: `.venv\Scripts\activate.bat` (CMD) hoặc `.venv\Scripts\Activate.ps1` (PowerShell).
- Chạy API: `set PYTHONPATH=.` rồi `uvicorn backend.main:app --host 0.0.0.0 --port 8000`; frontend: `cd frontend && npm run dev`.
- Đường dẫn có dấu cách: dùng dấu ngoặc kép, ví dụ `cd "C:\Users\...\irp"`.

---

_Tài liệu kỹ thuật: DevGuide trong `docs/`._
