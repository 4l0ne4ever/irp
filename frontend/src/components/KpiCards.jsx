import React from "react";

export function KpiCards({ result }) {
  if (!result) return null;
  const r = result;
  const items = [
    ["Total cost", `${Math.round(r.total_cost).toLocaleString()} VND`],
    ["Inventory %", `${r.cost_pct_inventory}%`],
    ["Distance %", `${r.cost_pct_distance}%`],
    ["Travel time %", `${r.cost_pct_time}%`],
    ["Feasible", r.feasible ? "Yes" : "No"],
    ["TW compliance", `${r.tw_compliance_rate}%`],
  ];
  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 12 }}>
      {items.map(([k, v]) => (
        <div key={k} style={{ border: "1px solid #ccc", borderRadius: 8, padding: 12 }}>
          <div style={{ fontSize: 12, color: "#666" }}>{k}</div>
          <div style={{ fontSize: 18, fontWeight: 600 }}>{v}</div>
        </div>
      ))}
    </div>
  );
}
