import React from "react";

function fmtVnd(n) {
  if (n == null || Number.isNaN(Number(n))) return "—";
  return `${Math.round(Number(n)).toLocaleString()} VND`;
}

function fmtNum(n, digits = 2) {
  if (n == null || Number.isNaN(Number(n))) return "—";
  return Number(n).toLocaleString(undefined, {
    maximumFractionDigits: digits,
    minimumFractionDigits: 0,
  });
}

export function ResultDetailPanel({ result, runParams }) {
  if (!result) return null;
  const r = result;
  const pd = Array.isArray(r.per_day) ? r.per_day : [];

  return (
    <section style={{ marginTop: 24 }}>
      <h3>Chi tiết kết quả &amp; thông số lần chạy</h3>

      {typeof r.ga_generations_run === "number" && (
        <div
          style={{
            marginTop: 12,
            padding: 12,
            background: "#e8f5e9",
            borderRadius: 8,
            fontSize: 13,
            border: "1px solid #c8e6c9",
          }}
        >
          <strong>GA — thế hệ đã chạy</strong>
          <p style={{ margin: "8px 0 0", lineHeight: 1.5 }}>
            Đã thực hiện <strong>{r.ga_generations_run}</strong> / {r.ga_generations_limit ?? "—"} thế hệ (mục tiêu tối đa).
            {r.ga_stop_reason === "stagnation" && (
              <> Lý do dừng: <strong>hội tụ</strong> (không giảm best đủ trong {r.ga_stagnation_window ?? "—"} thế hệ liên tiếp).</>
            )}
            {r.ga_stop_reason === "time_limit" && (
              <> Lý do dừng: hết <strong>time limit</strong> CPU.</>
            )}
            {r.ga_stop_reason === "max_generations" && <> Đã chạy đủ số thế hệ cấu hình.</>}
            {r.ga_stop_reason && !["stagnation", "time_limit", "max_generations"].includes(r.ga_stop_reason) && (
              <> Mã dừng backend: <code>{r.ga_stop_reason}</code></>
            )}
          </p>
        </div>
      )}

      {runParams && (
        <div
          style={{
            marginTop: 12,
            padding: 12,
            background: "#f5f5f5",
            borderRadius: 8,
            fontSize: 13,
          }}
        >
          <strong>Cấu hình đã gửi API</strong>
          <dl style={{ margin: "8px 0 0", display: "grid", gridTemplateColumns: "160px 1fr", gap: "4px 12px" }}>
            <dt style={{ color: "#555" }}>Scenario</dt>
            <dd style={{ margin: 0 }}>{runParams.scenario}</dd>
            <dt style={{ color: "#555" }}>Seed</dt>
            <dd style={{ margin: 0 }}>{runParams.seed}</dd>
            {runParams.showGa && (
              <>
                <dt style={{ color: "#555" }}>pop_size / generations / time_limit (s)</dt>
                <dd style={{ margin: 0 }}>
                  {runParams.popSize} / {runParams.generations} / {runParams.timeLimit}
                </dd>
              </>
            )}
            <dt style={{ color: "#555" }}>Nguồn instance</dt>
            <dd style={{ margin: 0 }}>{runParams.source === "upload" ? "Upload" : "Built-in"}</dd>
            {runParams.source === "builtin" && runParams.instanceKey && (
              <>
                <dt style={{ color: "#555" }}>instance_key</dt>
                <dd style={{ margin: 0 }}>
                  <code>{runParams.instanceKey}</code>
                </dd>
              </>
            )}
          </dl>
        </div>
      )}

      <div style={{ marginTop: 16, display: "grid", gridTemplateColumns: "repeat(2, 1fr)", gap: 16 }}>
        <div style={{ border: "1px solid #ddd", borderRadius: 8, padding: 12 }}>
          <h4 style={{ margin: "0 0 8px", fontSize: 14 }}>Bài toán &amp; KPI số</h4>
          <dl style={{ margin: 0, display: "grid", gridTemplateColumns: "140px 1fr", gap: "6px 10px", fontSize: 13 }}>
            <dt style={{ color: "#666" }}>scale</dt>
            <dd style={{ margin: 0 }}>{r.scale}</dd>
            <dt style={{ color: "#666" }}>n (KH) / m (xe)</dt>
            <dd style={{ margin: 0 }}>
              {r.n} / {r.m}
            </dd>
            <dt style={{ color: "#666" }}>Tổng giao (stops)</dt>
            <dd style={{ margin: 0 }}>{r.n_deliveries}</dd>
            <dt style={{ color: "#666" }}>TB giao / KH / chu kỳ</dt>
            <dd style={{ margin: 0 }}>{fmtNum(r.avg_deliveries_per_customer, 2)}</dd>
            <dt style={{ color: "#666" }}>Quãng đường (km)</dt>
            <dd style={{ margin: 0 }}>{fmtNum(r.total_distance_km, 2)}</dd>
            <dt style={{ color: "#666" }}>Mức tồn TB / capacity TB</dt>
            <dd style={{ margin: 0 }}>{fmtNum(r.avg_inventory_level_pct, 1)}%</dd>
            <dt style={{ color: "#666" }}>CPU time (s)</dt>
            <dd style={{ margin: 0 }}>{fmtNum(r.cpu_time_sec, 2)}</dd>
            <dt style={{ color: "#666" }}>Fitness</dt>
            <dd style={{ margin: 0 }}>{fmtNum(r.fitness, 4)}</dd>
          </dl>
        </div>

        <div style={{ border: "1px solid #ddd", borderRadius: 8, padding: 12 }}>
          <h4 style={{ margin: "0 0 8px", fontSize: 14 }}>Chi phí (VND) &amp; vi phạm</h4>
          <dl style={{ margin: 0, display: "grid", gridTemplateColumns: "140px 1fr", gap: "6px 10px", fontSize: 13 }}>
            <dt style={{ color: "#666" }}>Inventory</dt>
            <dd style={{ margin: 0 }}>{fmtVnd(r.cost_inventory)}</dd>
            <dt style={{ color: "#666" }}>Distance</dt>
            <dd style={{ margin: 0 }}>{fmtVnd(r.cost_distance)}</dd>
            <dt style={{ color: "#666" }}>Travel time</dt>
            <dd style={{ margin: 0 }}>{fmtVnd(r.cost_time)}</dd>
            <dt style={{ color: "#666" }}>TW violations</dt>
            <dd style={{ margin: 0 }}>{r.tw_violations}</dd>
            <dt style={{ color: "#666" }}>Stockout</dt>
            <dd style={{ margin: 0 }}>{r.stockout_violations}</dd>
            <dt style={{ color: "#666" }}>Capacity</dt>
            <dd style={{ margin: 0 }}>{r.capacity_violations}</dd>
            <dt style={{ color: "#666" }}>Vehicle</dt>
            <dd style={{ margin: 0 }}>{r.vehicle_violations ?? 0}</dd>
          </dl>
        </div>
      </div>

      {pd.length > 0 && (
        <div style={{ marginTop: 16 }}>
          <h4 style={{ fontSize: 14, marginBottom: 8 }}>Theo ngày (schedule)</h4>
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
              <thead>
                <tr style={{ background: "#eee", textAlign: "left" }}>
                  <th style={{ padding: 8, border: "1px solid #ccc" }}>Day</th>
                  <th style={{ padding: 8, border: "1px solid #ccc" }}>Routes</th>
                  <th style={{ padding: 8, border: "1px solid #ccc" }}>Deliveries</th>
                  <th style={{ padding: 8, border: "1px solid #ccc" }}>Distance km</th>
                </tr>
              </thead>
              <tbody>
                {pd.map((row) => (
                  <tr key={row.day}>
                    <td style={{ padding: 8, border: "1px solid #ccc" }}>{row.day}</td>
                    <td style={{ padding: 8, border: "1px solid #ccc" }}>{row.n_routes}</td>
                    <td style={{ padding: 8, border: "1px solid #ccc" }}>{row.n_deliveries}</td>
                    <td style={{ padding: 8, border: "1px solid #ccc" }}>{fmtNum(row.distance_km, 2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </section>
  );
}
