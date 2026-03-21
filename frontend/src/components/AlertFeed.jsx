import React, { useState } from "react";

export function AlertFeed({ alerts, onReplanTw, replanDisabled }) {
  const [localErr, setLocalErr] = useState(null);

  if (!alerts.length) return <p style={{ color: "#888" }}>No alerts</p>;

  const onClickReplan = async () => {
    if (!onReplanTw || replanDisabled) return;
    setLocalErr(null);
    try {
      await onReplanTw();
    } catch (e) {
      setLocalErr(String(e.message || e));
    }
  };

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
      {localErr && <div style={{ color: "coral", marginBottom: 8 }}>{localErr}</div>}
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
          {a.type === "tw_violation" && typeof onReplanTw === "function" && (
            <div style={{ marginTop: 6 }}>
              <button
                type="button"
                disabled={!!replanDisabled}
                onClick={onClickReplan}
                style={{
                  padding: "4px 10px",
                  fontSize: 12,
                  borderRadius: 6,
                  border: "1px solid #c62828",
                  background: replanDisabled ? "#eee" : "#ffebee",
                  cursor: replanDisabled ? "not-allowed" : "pointer",
                }}
              >
                Re-optimize remaining stops
              </button>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
