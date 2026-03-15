# Hướng Dẫn Sử Dụng — IRP-TW-DT

## Mục lục

1. [Cài đặt môi trường](#1-cài-đặt-môi-trường)
2. [Chạy giao diện Streamlit (khuyến nghị)](#2-chạy-giao-diện-streamlit-khuyến-nghị)
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
python3 -c "import numpy, pandas, folium, streamlit; print('OK')"
```

---

## 2. Chạy giao diện Streamlit (khuyến nghị)

Ứng dụng chính để chạy thí nghiệm là **giao diện web Streamlit**: cấu hình trên màn hình chính, xem bản đồ instance, nhật ký chạy (live) và kết quả chi tiết ngay trên trình duyệt.

### Khởi chạy

```bash
# Từ thư mục gốc dự án (irp/)
streamlit run app.py
```

Trình duyệt sẽ mở tại `http://localhost:8501`. Nếu không, mở thủ công địa chỉ đó.

### Cấu hình và chạy

1. **Nguồn dữ liệu (Source)**
   - **Built-in instance:** Sinh instance ngẫu nhiên (Hà Nội, lognormal, kiểm tra vùng nước).
     - Chọn **Scenario** (P, A, B, C), nhập **n (số khách hàng)** và **m (số xe)**.
     - Bấm **Generate** để tạo instance và xem bản đồ OSRM (depot + khách hàng).
   - **Upload file:** Tải lên file JSON hoặc CSV.
     - **JSON:** Định dạng đầy đủ (metadata, depot, customers). n, m lấy từ file.
     - **CSV:** Mỗi dòng là một khách hàng. Dòng đầu tiên có thể là dòng meta:
       - `# m=3` hoặc `# m=3,depot_lon=105.86,depot_lat=20.99`
       - Nếu có dòng meta thì **n** = số dòng dữ liệu, **m** (và có thể depot) lấy từ file.
       - Nếu không có dòng meta: nhập depot (kinh độ, vĩ độ) thủ công; m mặc định = 2.
     - **Lần tải đầu:** Ứng dụng gọi OSRM để tính ma trận khoảng cách đường bộ → có thể mất **30–90 giây** với n lớn (ví dụ n≈100). Có thông báo chờ và spinner.
     - Lần chạy sau (cùng file) dùng bộ nhớ cache, không gọi OSRM lại.

2. **Tham số GA (chỉ khi Scenario B hoặc C)**
   - Preset: Full Defaults / Fast Demo.
   - Population size, Generations, Time limit (s).

3. **Chạy thí nghiệm**
   - Khi đã có instance (Generate xong hoặc Upload và load xong), dòng trạng thái hiển thị: *"Instance ready (n=..., m=...). Click **Run Experiment** to start the solver."*
   - Bấm **Run Experiment**. Solver chạy nền; trang tự làm mới mỗi giây.
   - **Run log:** Trong lúc chạy, nhật ký solver (và HGA nếu B/C) hiển thị live trong phần **Run log** phía dưới.
   - Khi xong: phần **Results** hiện tổng quan (Total cost, %, Feasible, TW compliance) và **Detailed metrics** (chi phí, vi phạm, giao hàng, khoảng cách, inventory, CPU time, per-day). Có **Solution map (OSRM)** và nếu B/C có **convergence chart**.

### Lưu ý

- Không tắt trình duyệt hay refresh trang khi đang chạy; chờ đến khi có kết quả hoặc lỗi.
- Kết quả và log chỉ hiển thị trên màn hình; thư mục tạm `/tmp/irp_runs` dùng để lưu run (có thể dọn định kỳ).

---

## 3. Cấu trúc thư mục

```
irp/
├── app.py                          # Ứng dụng Streamlit (điểm vào chính)
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

Nếu không dùng Streamlit, có thể chạy một lần từ dòng lệnh:

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

### Trên Streamlit

- **Results:** Tổng quan (Total cost, %, Feasible, TW compliance).
- **Detailed metrics (expand):** Chi phí (VND + %), vi phạm (TW, stockout, capacity, vehicle), giao hàng & khoảng cách, inventory, CPU time, per-day.
- **Run log:** Nhật ký solver (và HGA) trong lúc chạy và sau khi xong.
- **Solution map:** Bản đồ Folium với tuyến OSRM.
- **Convergence chart:** Đường hội tụ HGA (B/C).

### File result.json (CLI / thư mục kết quả)

Các trường chính: `scenario`, `n`, `m`, `feasible`, `total_cost`, `cost_inventory`, `cost_distance`, `cost_time`, `cost_pct_*`, `tw_violations`, `stockout_violations`, `capacity_violations`, `tw_compliance_rate`, `n_deliveries`, `total_distance_km`, `avg_inventory_level_pct`, `cpu_time_sec`, `per_day`, …

### File map.html

Mở bằng trình duyệt để xem bản đồ tương tác (depot, khách hàng, tuyến đường).

---

## 7. Xuất dữ liệu JSON/CSV

```bash
python3 export_instances.py
```

Xuất các instance trong `src/data/irp-instances/` sang `src/data/irp-instances-json/` (JSON + CSV). CSV có dòng đầu tiên dạng `# m=...,depot_lon=...,depot_lat=...` để Streamlit/loader đọc n và m từ file.

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

- **ModuleNotFoundError 'src':** Chạy từ thư mục gốc dự án, dùng `python3 -m src.main ...` hoặc `streamlit run app.py`.
- **Load file chậm:** Lần đầu load CSV/JSON với n lớn phải gọi OSRM (30–90s). Có spinner và caption giải thích.
- **Run không bắt đầu:** Đảm bảo đã Generate (built-in) hoặc Upload và chờ load xong; sau đó bấm **Run Experiment**.
- **feasible = False / tw_violations > 0:** Kiểm tra kết nối OSRM; thử tăng số xe `m`.
- **OSRM lỗi:** Kiểm tra internet; OSRM public server đôi khi giới hạn. Không có fallback nội bộ.

---

## 12. Hướng dẫn riêng cho Windows

- Dùng `python` thay cho `python3`.
- Kích hoạt venv: `.venv\Scripts\activate.bat` (CMD) hoặc `.venv\Scripts\Activate.ps1` (PowerShell).
- Chạy Streamlit: `streamlit run app.py`.
- Đường dẫn có dấu cách: dùng dấu ngoặc kép, ví dụ `cd "C:\Users\...\irp"`.

---

_Tài liệu kỹ thuật: DevGuide trong `docs/`._
