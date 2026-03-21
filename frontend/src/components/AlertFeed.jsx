import React from "react";

export function AlertFeed({ alerts }) {
  if (!alerts.length) return <p style={{ color: "#888" }}>No alerts</p>;
  return (
    <div
      style={{
        maxHeight: 200,
        overflowY: "auto",
        border: "1px solid #ddd",
        borderRadius: 8,
        padding: 8,
        fontSize: 13,
      }}
    >
      {alerts.map((a, i) => (
        <div key={i} style={{ marginBottom: 8, borderBottom: "1px solid #eee", paddingBottom: 6 }}>
          <span
            style={{
              display: "inline-block",
              padding: "2px 6px",
              borderRadius: 4,
              background: "#ede7f6",
              marginRight: 8,
              fontSize: 11,
            }}
          >
            {a.type || "alert"}
          </span>
          {a.message || JSON.stringify(a)}
        </div>
      ))}
    </div>
  );
}
