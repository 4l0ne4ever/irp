# Dynamic / stochastic traffic & rolling horizon — research architecture

Mục tiêu: **không** lấy thời gian đi đường từ hằng số cố định trong repo; mọi con số “tắc / tốc độ / duration” đến từ **nguồn runtime** (API, stream, hoặc phân phối xác suất ước lượng) và có thể **lập lịch lại** khi trạng thái giao thông đổi.

---

## 1. Nguyên tắc tránh hardcode

- **Không** commit bảng `TRAFFIC_ZONES` kiểu nguồn sự thật duy nhất. Nếu cần fallback khi API chết, đặt trong **file cấu hình ngoài git** hoặc **secret/config server**, có version + timestamp.
- **Tách** “mô hình tối ưu” (HGA, decode, FIFO IGP) khỏi “nguồn dữ liệu thời gian đi”: solver chỉ gọi qua một **lớp façade** `TravelTimeModel` / `TrafficState`.

---

## 2. Lớp trừu tượng (data plane)

Định nghĩa giao diện (research-friendly, có thể implement dần):

| Thành phần | Trách nhiệm |
|------------|-------------|
| **TrafficObservation** | Snapshot tại thời điểm `t`: toàn cục (city-wide factors) hoặc cục bộ (per-edge, per-OD). Kèm `valid_until`, `source`, `confidence`. |
| **DurationResolver** | `duration_h(od, depart_h, context)` hoặc `matrix_slice(od_pairs, depart_h_window)` — trả về **giờ** hoặc **phân phối** (xem mục 4). |
| **GeometryResolver** | Giữ OSRM / provider khác cho polyline (có thể tách khỏi duration nếu API khác nhau). |

**Realtime:** một luồng (Kafka topic `traffic-updates`, SSE, hoặc poll có backoff) đẩy `TrafficObservation` vào **TrafficStateStore** (in-memory + TTL + optional Redis).

---

## 3. Rolling horizon (lập lịch lại khi traffic đổi)

1. **Trigger** (bất kỳ điều kiện nào đủ mạnh):
   - Thay đổi duration ước lượng vượt ngưỡng so với ma trận đang dùng (ví dụ > ε% hoặc > Δ phút trên cạnh quan trọng).
   - Hết `valid_until` của snapshot.
   - Sự kiện nghiệp vụ (thêm đơn, xe hỏng).

2. **Vòng lặp:**
   - Đọc `TrafficState` mới nhất → build **ma trận thời gian** (hoặc vài **slice theo khung giờ**) cho instance hiện tại.
   - Chạy **re-optimize** với **warm start**: seed HGA từ nhiệm sắc / giant tour hiện có (giảm thời gian so với cold start).
   - Xuất delta plan → đẩy Kafka / WS cho Monitoring; lưu `artifacts.pkl` phiên bản hoá (`run_id` + `plan_revision`).

3. **Giới hạn thực tế:** tần suất re-run (ví dụ tối đa 1 lần / 2–5 phút / vùng) để tránh bão API và bão GA.

---

## 4. Stochastic traffic (research)

Không cố định một duration duy nhất:

- **Kịch bản (SAA):** mỗi lần evaluate fitness, lấy `S` mẫu duration từ phân phối (log-normal, empirical từ lịch sử API) → kỳ vọng hoặc CVaR của cost / vi phạm TW.
- **Robust:** duration = `base + worst_case_delta` theo quantile từ provider.
- **Markov / regime:** trạng thái ẩn (sáng/trưa/tối) với transition; provider realtime cập nhật belief.

Tích hợp với code hiện tại: thay `igp_travel_time(dist, depart_h)` bằng gọi vào **StochasticDurationResolver** trong `evaluate` / decode (chi phí tính toán tăng — cần batching và cache theo `(od, slot)`.

---

## 5. Nguồn realtime đáng tin (tham chiếu triển khai)

- **TomTom / HERE / Google Routes** (duration có traffic, `departure_time` / `arrival_time`).
- **Probe / incident feeds** (đóng đường) → scale factor trên subgraph hoặc reject edge.

Mỗi response nên lưu **metadata**: provider, request_id, timestamp, TTL để audit và tái lập thí nghiệm (partial reproducibility).

---

## 6. Chỗ nối vào repo hiện tại

| Vị trí | Việc làm |
|--------|----------|
| `src/core/traffic.py` | Giữ IGP làm **một implementation** của façade; sau này thêm `APIDurationModel`, `StochasticIGP`. |
| `src/data/distances.py` | Ma trận OSRM: tùy chọn second pass **duration có traffic** theo OD + `depart_h` (batch API). |
| `backend/` | Service **TrafficIngest** consume stream → cập nhật store; endpoint hoặc nội bộ gọi **schedule_revision** khi trigger. |
| `frontend/Monitoring` | Hiển thị `plan_revision`, nguồn traffic, thời điểm cập nhật cuối (minh bạch với user). |

---

## 7. Thứ tự nghiên cứu đề xuất

1. Façade + inject duration từ **file JSON do cron tải API** (vẫn realtime so với git, chưa cần stream).
2. **Rolling horizon** với một ngưỡng đơn giản + warm-start HGA.
3. **Stream** traffic + giới hạn tần suất re-plan.
4. **Stochastic layer** trong fitness (SAA nhỏ `S=5–20`).

Tài liệu này là khung; không thay thế hợp đồng API cụ thể của từng nhà cung cấp.
