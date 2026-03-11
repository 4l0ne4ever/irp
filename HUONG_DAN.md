# Hướng Dẫn Sử Dụng — IRP-TW-DT

## Mục lục

1. [Cài đặt môi trường](#1-cài-đặt-môi-trường)
2. [Cấu trúc thư mục](#2-cấu-trúc-thư-mục)
3. [Chạy thí nghiệm đơn lẻ](#3-chạy-thí-nghiệm-đơn-lẻ)
4. [Chạy toàn bộ thí nghiệm](#4-chạy-toàn-bộ-thí-nghiệm)
5. [Đọc kết quả](#5-đọc-kết-quả)
6. [Xuất dữ liệu JSON/CSV](#6-xuất-dữ-liệu-jsoncsv)
7. [Chuyển đổi dữ liệu VRPTW](#7-chuyển-đổi-dữ-liệu-vrptw)
8. [Chạy tests](#8-chạy-tests)
9. [Các tham số quan trọng](#9-các-tham-số-quan-trọng)
10. [Xử lý lỗi thường gặp](#10-xử-lý-lỗi-thường-gặp)
11. [Hướng dẫn riêng cho Windows](#11-hướng-dẫn-riêng-cho-windows)

---

## 1. Cài đặt môi trường

### Yêu cầu hệ thống

- Python **3.13** trở lên
- macOS, Linux **hoặc Windows 10/11**
- Kết nối internet (để gọi OSRM API lấy khoảng cách thực tế)

### Bước 1 — Tạo môi trường ảo

**macOS / Linux:**

```bash
# Tạo môi trường ảo
python3 -m venv .venv

# Kích hoạt môi trường
source .venv/bin/activate
```

**Windows (Command Prompt / PowerShell):**

```cmd
:: Tạo môi trường ảo
python -m venv .venv

:: Kích hoạt môi trường (Command Prompt)
.venv\Scripts\activate.bat

:: Kích hoạt môi trường (PowerShell)
.venv\Scripts\Activate.ps1
```

> **Windows - lưu ý PowerShell:** Nếu gặp lỗi `execution policy`, chạy lệnh này một lần duy nhất:
>
> ```powershell
> Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
> ```

### Bước 2 — Cài các thư viện cần thiết

```bash
pip install -r requirements.txt
```

> **macOS/Linux:** Dùng `.venv/bin/python3` thay vì `python3` hệ thống.  
> **Windows:** Dùng `.venv\Scripts\python` thay vì `python`.

### Kiểm tra cài đặt thành công

```bash
# macOS / Linux
python3 -c "import numpy, pandas, folium; print('OK')"

# Windows
python -c "import numpy, pandas, folium; print('OK')"
```

---

## 2. Cấu trúc thư mục

```
irp/
├── pyproject.toml                     # Cấu hình project (tên, dependencies)
├── requirements.txt                   # Danh sách thư viện cần cài
├── README.md                          # Tài liệu tổng quan (tiếng Anh)
├── HUONG_DAN.md                       # File này (hướng dẫn tiếng Việt)
├── export_instances.py                # Script xuất dữ liệu .npy → JSON/CSV
├── .gitignore                         # Loại trừ .venv, __pycache__, results/…
│
├── docs/
│   └── decuong.tex                    # Đề cương nghiên cứu (LaTeX)
│
├── src/
│   ├── main.py                        # Điểm vào CLI chính (lệnh run / batch)
│   │
│   ├── core/                          # Cấu trúc dữ liệu cốt lõi
│   │   ├── constants.py               # Tham số: LAMBDA_TW, GA_POP_SIZE, Q, v.v.
│   │   ├── instance.py                # Class IRPInstance (load & validate dữ liệu)
│   │   ├── inventory.py               # Logic tính tồn kho (reorder, holding cost)
│   │   ├── solution.py                # Class Solution (lưu lịch giao hàng)
│   │   └── traffic.py                 # Tích hợp OSRM API (ma trận khoảng cách)
│   │
│   ├── data/                          # Dữ liệu và tiện ích tạo dữ liệu
│   │   ├── converter.py               # Chuyển đổi định dạng (VRPTW ↔ IRP)
│   │   ├── generator.py               # Sinh instance ngẫu nhiên (lognormal, normal…)
│   │   │
│   │   ├── irp-instances/             # 15 bộ dữ liệu benchmark (S/M/L × 5 seeds)
│   │   │   ├── S_n20_seed42/          # Nhỏ: 20 khách hàng
│   │   │   │   ├── meta.json          #   Thông tin: n, T, Q, scenario…
│   │   │   │   ├── coords.npy         #   Tọa độ (lat, lon) — shape (n+1, 2)
│   │   │   │   ├── dist.npy           #   Ma trận khoảng cách — shape (n+1, n+1)
│   │   │   │   ├── demand.npy         #   Nhu cầu hàng ngày — shape (n, T)
│   │   │   │   ├── I0.npy             #   Tồn kho ban đầu — shape (n,)
│   │   │   │   ├── U.npy              #   Sức chứa tối đa kho — shape (n,)
│   │   │   │   ├── L_min.npy          #   Mức tồn kho tối thiểu — shape (n,)
│   │   │   │   ├── h.npy              #   Chi phí lưu kho — shape (n,)
│   │   │   │   ├── l.npy              #   Cửa sổ thời gian mở (TW early) — shape (n,)
│   │   │   │   ├── e.npy              #   Cửa sổ thời gian đóng (TW late) — shape (n,)
│   │   │   │   └── s.npy              #   Thời gian phục vụ tại điểm — shape (n,)
│   │   │   ├── S_n20_seed123/
│   │   │   ├── S_n20_seed456/
│   │   │   ├── S_n20_seed789/
│   │   │   ├── S_n20_seed1000/
│   │   │   ├── M_n50_seed42/          # Trung: 50 khách hàng
│   │   │   ├── M_n50_seed123/
│   │   │   ├── M_n50_seed456/
│   │   │   ├── M_n50_seed789/
│   │   │   ├── M_n50_seed1000/
│   │   │   ├── L_n100_seed42/         # Lớn: 100 khách hàng
│   │   │   ├── L_n100_seed123/
│   │   │   ├── L_n100_seed456/
│   │   │   ├── L_n100_seed789/
│   │   │   └── L_n100_seed1000/
│   │   │
│   │   ├── irp-instances-json/        # Phiên bản JSON/CSV của các instances
│   │   │   ├── S_n20_seed42.json
│   │   │   ├── S_n20_seed42_customers.csv
│   │   │   └── …                      # (12 file cho 6 instances đại diện)
│   │   │
│   │   └── test-dataset/              # Dataset thực tế Hà Nội (CSV + JSON)
│   │       ├── hanoi_lognormal_20_customers.json
│   │       ├── hanoi_lognormal_50_customers.json
│   │       ├── hanoi_lognormal_100_customers.json
│   │       └── …                      # (nhiều biến thể: normal, relaxed, large…)
│   │
│   ├── baselines/                     # Thuật toán baseline để so sánh
│   │   ├── periodic.py                # Chính sách giao hàng định kỳ (periodic)
│   │   └── rmi.py                     # Chính sách RMI (Retailer-Managed Inventory)
│   │
│   ├── solver/                        # Thuật toán HGA chính
│   │   ├── hga.py                     # Vòng lặp GA chính (selection, crossover, LS)
│   │   ├── chromosome.py              # Biểu diễn nhiễm sắc thể & khởi tạo quần thể
│   │   ├── decode.py                  # Giải mã nhiễm sắc thể → lịch giao hàng
│   │   ├── fitness.py                 # Tính hàm mục tiêu (chi phí + phạt TW)
│   │   ├── operators.py               # Toán tử di truyền (OX crossover, mutation…)
│   │   └── local_search.py            # Tìm kiếm cục bộ (time-shift, 2-opt…)
│   │
│   ├── milp/                          # Kiểm chứng bằng MILP (tùy chọn)
│   │   └── validator.py               # So sánh lời giải HGA với MILP optimal
│   │
│   └── experiments/                   # Chạy & phân tích thí nghiệm hàng loạt
│       ├── runner.py                  # Chạy nhiều instances, ghi metrics.txt
│       └── analysis.py                # Tổng hợp & vẽ biểu đồ kết quả
│
├── tests/                             # Unit tests & integration tests
│   ├── test_integration.py            # Test end-to-end toàn bộ pipeline
│   ├── test_inventory.py              # Test logic tồn kho
│   └── test_traffic.py                # Test tích hợp OSRM API
│
└── results/                           # Kết quả chạy (tự động tạo)
    └── C_S_n20_seed42/                # Ví dụ: Scenario C, S, n=20, seed=42
        ├── metrics.txt                #   KPI: cost, feasible, TW violations…
        ├── map.html                   #   Bản đồ tuyến đường tương tác (Folium)
        └── solution.json              #   Lịch giao hàng chi tiết
```

---

## 3. Chạy thí nghiệm đơn lẻ

### Cú pháp

```bash
python3 -m src.main run \
  --scenario <A|B|C> \
  --n <20|50|100> \
  --m <số_xe> \
  --seed <seed> \
  --output <thư_mục_kết_quả>
```

### Các Scenario

| Scenario | Mô tả                                       | Thời gian ước tính |
| -------- | ------------------------------------------- | ------------------ |
| `A`      | Baseline: Định tuyến định kỳ (không tối ưu) | < 1 giây           |
| `B`      | HGA + 2-opt (không dùng Time-Shift)         | ~45 giây (n=20)    |
| `C`      | HGA + Time-Shift + 2-opt (đầy đủ)           | ~70 giây (n=20)    |

### Ví dụ cụ thể

```bash
# Chạy Scenario C, tập nhỏ (n=20, 2 xe, seed=42)
python3 -m src.main run --scenario C --n 20 --m 2 --seed 42 --output results

# Chạy Scenario B, tập trung bình (n=50, 3 xe, seed=123)
python3 -m src.main run --scenario B --n 50 --m 3 --seed 123 --output results

# Chạy Scenario A, tập lớn (n=100, 5 xe, seed=1000)
python3 -m src.main run --scenario A --n 100 --m 5 --seed 1000 --output results
```

### Kết quả đầu ra

```
results/
└── C_S_n20_seed42/          # Tên thư mục = <scenario>_<scale>_n<n>_seed<seed>
    ├── result.json          # Toàn bộ chỉ số dạng JSON
    ├── metrics.txt          # Báo cáo chi tiết 7 phần
    ├── map.html             # Bản đồ Folium (mở bằng trình duyệt)
    └── convergence.csv      # Đường cong hội tụ HGA theo thế hệ
```

---

## 4. Chạy toàn bộ thí nghiệm

Chạy **45 thí nghiệm** = 3 scenario × 3 quy mô × 5 seeds:

```bash
python3 -m src.main batch --output results
```

> **Lưu ý:** Ước tính ~4–6 giờ với máy tính thông thường.  
> Kết quả từng instance được lưu vào `results/<scenario>_<scale>_n<n>_seed<seed>/`.

### Chạy một nhóm nhỏ (thử nghiệm nhanh)

Nếu muốn chạy thử một nhóm, chỉnh sửa trực tiếp trong `src/experiments/runner.py`:

```python
# Ví dụ: giới hạn chỉ chạy seeds 42 và 123
SEEDS = [42, 123]  # thay vì [42, 123, 456, 789, 1000]
```

---

## 5. Đọc kết quả

### File `result.json`

```json
{
  "scenario": "C",
  "n": 20,
  "feasible": true,          ← Nghiệm có khả thi không
  "tw_violations": 0,        ← Số vi phạm cửa sổ thời gian
  "stockout_violations": 0,  ← Số lần hết hàng
  "total_cost": 4229866,     ← Tổng chi phí (đồng VND)
  "cost_pct_inventory": 67.8, ← % chi phí lưu kho
  "cost_pct_distance": 15.0,  ← % chi phí quãng đường
  "cost_pct_time": 17.2,      ← % chi phí thời gian (giao thông)
  "tw_compliance_rate": 100.0, ← Tỷ lệ tuân thủ cửa sổ thời gian (%)
  "cpu_time_sec": 69.0,      ← Thời gian chạy (giây)
  "per_day": [...]            ← Chi tiết từng ngày
}
```

### File `metrics.txt`

Báo cáo chi tiết gồm 7 phần:

```
1. OBJECTIVE FUNCTION BREAKDOWN   ← Phân tích chi phí theo từng thành phần
2. FEASIBILITY                    ← Tính khả thi và số vi phạm
3. DELIVERY STATISTICS            ← Thống kê giao hàng
4. INVENTORY ANALYSIS             ← Biến động tồn kho từng khách hàng
5. PER-DAY BREAKDOWN              ← Bảng phân tích từng ngày (7 ngày)
6. ROUTE DETAILS                  ← Chi tiết lộ trình: stops, giờ đến, tải
7. PERFORMANCE                    ← Thời gian CPU, fitness
```

### File `map.html`

Mở bằng trình duyệt để xem bản đồ tương tác:

```bash
# macOS
open results/C_S_n20_seed42/map.html

# Linux
xdg-open results/C_S_n20_seed42/map.html

# Windows (Command Prompt)
start results\C_S_n20_seed42\map.html

# hoặc kéo thả file vào Chrome/Firefox
```

### File `convergence.csv`

```csv
generation,best_fitness,avg_fitness,feasible_count,time_sec
0,4864447,5887096,38,0.1
50,4440471,5931821,37,17.2
...
199,4229866,5403596,48,68.7
```

Dùng Pandas/Excel để vẽ đường cong hội tụ:

```python
import pandas as pd
import matplotlib.pyplot as plt

df = pd.read_csv("results/C_S_n20_seed42/convergence.csv")
plt.plot(df["generation"], df["best_fitness"])
plt.xlabel("Thế hệ")
plt.ylabel("Fitness tốt nhất")
plt.title("Đường cong hội tụ HGA")
plt.show()
```

---

## 6. Xuất dữ liệu JSON/CSV

Các bộ dữ liệu `.npy` đã được xuất sẵn sang JSON và CSV trong `src/data/irp-instances-json/`.

Để xuất thêm instances:

```bash
# Chỉnh danh sách instances muốn xuất trong export_instances.py
# rồi chạy:
python3 export_instances.py
```

**Giải thích các cột trong CSV:**

| Cột                           | Ý nghĩa                                                     |
| ----------------------------- | ----------------------------------------------------------- |
| `customer_id`                 | Mã khách hàng (0-based)                                     |
| `lon`, `lat`                  | Tọa độ GPS (kinh độ, vĩ độ)                                 |
| `initial_inventory`           | Tồn kho ban đầu (đơn vị)                                    |
| `min_inventory`               | Mức tồn kho tối thiểu (safety stock)                        |
| `tank_capacity`               | Dung tích kho tối đa (đơn vị)                               |
| `lead_time_days`              | Thời gian đặt hàng (ngày)                                   |
| `service_time_h`              | Thời gian phục vụ tại kho (giờ)                             |
| `holding_cost_vnd`            | Chi phí lưu kho (VND/đơn vị/ngày)                           |
| `time_window_start_h`         | Giờ bắt đầu cửa sổ thời gian (VD: 8.0 = 8:00, 14.0 = 14:00) |
| `time_window_end_h`           | Giờ kết thúc cửa sổ thời gian (VD: 12.0, 18.0)              |
| `demand_day0` → `demand_day6` | Nhu cầu từng ngày trong tuần                                |

---

## 7. Chuyển đổi dữ liệu VRPTW

Nếu có file dữ liệu VRPTW (JSON) mới của Hà Nội, chuyển đổi sang định dạng IRP:

```bash
python3 -m src.main convert \
  --source-csv-dir src/data/test-dataset \
  --output src/data/irp-instances
```

> **Yêu cầu:** Cần kết nối internet để lấy khoảng cách thực từ OSRM API.  
> Nếu OSRM không khả dụng, hệ thống tự động fallback sang khoảng cách Haversine (GPS).

---

## 8. Chạy tests

### Chạy toàn bộ tests

```bash
# Kết quả mong đợi: 33 tests passed
pytest tests/ -v
```

### Chạy test cụ thể

```bash
# Test tích hợp (end-to-end, n=5)
pytest tests/test_integration.py -v

# Test mô hình tồn kho
pytest tests/test_inventory.py -v

# Test mô hình giao thông IGP
pytest tests/test_traffic.py -v
```

### Chạy test với thông tin chi tiết hơn

```bash
# Dừng ngay khi có test đầu tiên thất bại
pytest tests/ -v -x

# In đầy đủ stdout/stderr
pytest tests/ -vvs
```

---

## 9. Các tham số quan trọng

Tất cả tham số cốt lõi nằm trong `src/core/constants.py`:

| Tham số             | Giá trị                   | Ý nghĩa                             |
| ------------------- | ------------------------- | ----------------------------------- |
| `LAMBDA_TW`         | 10,000                    | Hệ số phạt vi phạm cửa sổ thời gian |
| `C_D`               | 3,500 VND/km              | Chi phí theo quãng đường            |
| `C_T`               | 74,000 VND/giờ            | Chi phí theo thời gian              |
| `DEFAULT_Q`         | 500 đơn vị                | Tải trọng xe                        |
| `DEFAULT_T`         | 7 ngày                    | Độ dài kỳ kế hoạch                  |
| `GA_POP_SIZE`       | 50                        | Kích thước quần thể GA              |
| `GA_GENERATIONS`    | 200                       | Số thế hệ GA                        |
| `GA_CROSSOVER_PROB` | 0.90                      | Xác suất lai ghép                   |
| `IGP_SPEEDS`        | [27, 15, 19, 14, 21] km/h | Tốc độ 5 khung giờ (Ichoua 2003)    |

> **Chú ý:** Không thay đổi các giá trị này tuỳ tiện — chúng được xác định trong DevGuide (`docs/IRP_TW_DT_DevGuide.pdf`). Thay đổi sẽ ảnh hưởng đến tính khả thi và khả năng so sánh kết quả.

---

## 10. Xử lý lỗi thường gặp

### ❌ Lỗi: `ModuleNotFoundError: No module named 'src'`

```bash
# Đảm bảo đang ở đúng thư mục gốc của dự án
cd "/Users/duongcongthuyet/Downloads/workspace/AI /irp"

# Chạy với cú pháp -m (module)
python3 -m src.main run ...
```

### ❌ Lỗi: `folium/requests not found`

```bash
# Đảm bảo đang dùng môi trường ảo
source .venv/bin/activate
pip install -r requirements.txt
```

### ❌ Nghiệm `feasible = False` hoặc có `tw_violations > 0`

Kiểm tra các nguyên nhân phổ biến:

1. **OSRM thất bại** → khoảng cách Haversine ngắn hơn thực tế → TW bị vi phạm  
   → Kiểm tra kết nối internet, chạy lại lệnh convert
2. **Tham số `m` quá nhỏ** → không đủ xe cho tất cả khách hàng  
   → Tăng `--m` lên (S: 2–3, M: 3–4, L: 5–6)

### ❌ Thời gian chạy quá lâu (> 10 phút cho n=20)

```bash
# Giảm số thế hệ tạm thời để thử nghiệm nhanh
# Chỉnh trong src/core/constants.py:
GA_GENERATIONS = 50  # thay vì 200
```

> **Lưu ý:** Nhớ khôi phục về 200 trước khi chạy thí nghiệm chính thức.

### ❌ Lỗi OSRM API

```bash
# macOS / Linux — kiểm tra API
curl "http://router.project-osrm.org/table/v1/driving/105.79,21.03;105.85,21.01?annotations=distance"

# Windows — dùng PowerShell
Invoke-WebRequest "http://router.project-osrm.org/table/v1/driving/105.79,21.03;105.85,21.01?annotations=distance"
```

Nếu OSRM không hoạt động, hệ thống tự fallback sang khoảng cách Haversine (GPS). Kết quả vẫn hợp lệ nhưng khoảng cách có thể nhỏ hơn thực tế ~20–30%.

---

## Quy trình chạy thí nghiệm hoàn chỉnh

**macOS / Linux:**

```bash
# 1. Kích hoạt môi trường
source .venv/bin/activate

# 2. Chạy thử một instance nhỏ để kiểm tra
python3 -m src.main run --scenario C --n 20 --m 2 --seed 42 --output results

# 3. Kiểm tra kết quả
cat results/C_S_n20_seed42/metrics.txt

# 4. Xem bản đồ
open results/C_S_n20_seed42/map.html

# 5. Nếu ổn, chạy toàn bộ
python3 -m src.main batch --output results
```

**Windows (Command Prompt):**

```cmd
:: 1. Kích hoạt môi trường
.venv\Scripts\activate.bat

:: 2. Chạy thử một instance nhỏ để kiểm tra
python -m src.main run --scenario C --n 20 --m 2 --seed 42 --output results

:: 3. Kiểm tra kết quả
type results\C_S_n20_seed42\metrics.txt

:: 4. Xem bản đồ (mở bằng trình duyệt mặc định)
start results\C_S_n20_seed42\map.html

:: 5. Nếu ổn, chạy toàn bộ
python -m src.main batch --output results
```

---

## 11. Hướng dẫn riêng cho Windows

### Cài đặt Python trên Windows

1. Tải Python 3.13 tại [python.org/downloads](https://www.python.org/downloads/)
2. Trong trình cài đặt: **bật tùy chọn "Add Python to PATH"**
3. Kiểm tra sau khi cài:

```cmd
python --version
pip --version
```

### Di chuyển vào thư mục dự án

```cmd
:: Nếu dự án nằm trong thư mục có dấu cách, dùng dấu ngoặc kép
cd "C:\Users\YourName\Downloads\irp"
```

> **Lưu ý tên thư mục có dấu cách trên Windows:** Luôn bao quanh đường dẫn bằng dấu `"..."`.

### Tạo và kích hoạt môi trường ảo

```cmd
:: Tạo môi trường ảo
python -m venv .venv

:: Kích hoạt (Command Prompt)
.venv\Scripts\activate.bat

:: Kích hoạt (PowerShell)
.venv\Scripts\Activate.ps1

:: Cài thư viện
pip install -r requirements.txt
```

### Chạy thí nghiệm trên Windows

Thay `python3` → `python` và `/` → `\` trong đường dẫn:

```cmd
:: Chạy Scenario C, nhỏ
python -m src.main run --scenario C --n 20 --m 2 --seed 42 --output results

:: Chạy toàn bộ thí nghiệm
python -m src.main batch --output results

:: Xuất dữ liệu JSON/CSV
python export_instances.py

:: Chạy tests
pytest tests\ -v
```

### Xem kết quả trên Windows

```cmd
:: Xem file metrics.txt
type results\C_S_n20_seed42\metrics.txt

:: Mở bản đồ trong trình duyệt
start results\C_S_n20_seed42\map.html

:: Mở thư mục kết quả trong Explorer
explorer results\C_S_n20_seed42
```

### Lỗi thường gặp riêng trên Windows

**❌ `python3` không nhận diện được**

Windows dùng `python` thay vì `python3`:

```cmd
python --version   ← dùng lệnh này
python3 --version  ← thường không hoạt động trên Windows
```

**❌ Lỗi encoding UTF-8 khi đọc file**

```cmd
:: Đặt encoding mặc định cho terminal
set PYTHONUTF8=1
python -m src.main run ...
```

Hoặc thêm vào đầu script Python:

```python
import sys
sys.stdout.reconfigure(encoding='utf-8')
```

**❌ `pytest` không tìm thấy sau khi cài**

```cmd
:: Chạy pytest qua python module
python -m pytest tests\ -v
```

**❌ Lỗi `FileNotFoundError` khi dùng đường dẫn**

Trên Windows hãy dùng `\\` hoặc `/` trong code Python — cả hai đều hoạt động:

```python
# Đều hoạt động trong Python trên Windows:
Path("src/data/irp-instances/S_n20_seed42")
Path("src\\data\\irp-instances\\S_n20_seed42")
```

### Bảng so sánh lệnh macOS vs Windows

| Tác vụ                  | macOS / Linux               | Windows CMD                  |
| ----------------------- | --------------------------- | ---------------------------- |
| Kích hoạt venv          | `source .venv/bin/activate` | `.venv\Scripts\activate.bat` |
| Chạy Python             | `python3 -m src.main ...`   | `python -m src.main ...`     |
| Xem file text           | `cat file.txt`              | `type file.txt`              |
| Mở trình duyệt          | `open file.html`            | `start file.html`            |
| Mở thư mục              | `open folder/`              | `explorer folder\`           |
| Dấu phân cách đường dẫn | `/`                         | `\` (hoặc `/` đều được)      |
| Biến môi trường         | `export VAR=value`          | `set VAR=value`              |

---

_Tài liệu kỹ thuật chi tiết: xem [`docs/IRP_TW_DT_DevGuide.pdf`](docs/IRP_TW_DT_DevGuide.pdf)_
