import React, { useEffect, useState } from "react";
import { useMonitoring } from "../context/MonitoringContext.jsx";
import { RouteMap } from "./RouteMap.jsx";
import { AlertFeed } from "./AlertFeed.jsx";
import { formatDayHour, clamp01 } from "../utils/timeFormat.js";

export function MonitoringView() {
  const { state, dispatch, startMonitor, stopMonitor, API_BASE } = useMonitoring();
  const [speedX, setSpeedX] = useState(60);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [mapCtx, setMapCtx] = useState(null);
  const [ctxErr, setCtxErr] = useState(null);

  const rid = state.monitorRunId;
  const atRisk = {};
  for (const a of state.alerts) {
    if (a.type === "stockout_risk" && a.customer_id != null) {
      atRisk[a.customer_id] = true;
    }
  }

  useEffect(() => {
    if (!rid) {
      setMapCtx(null);
      setCtxErr(null);
      return;
    }
    let cancelled = false;
    setCtxErr(null);
    fetch(`${API_BASE}/monitor/context?run_id=${encodeURIComponent(rid)}&day=${state.selectedDay}`)
      .then((r) => {
        if (!r.ok) throw new Error(r.statusText);
        return r.json();
      })
      .then((j) => {
        if (!cancelled) setMapCtx(j);
      })
      .catch((e) => {
        if (!cancelled) {
          setMapCtx(null);
          setCtxErr(String(e.message || e));
        }
      });
    return () => {
      cancelled = true;
    };
  }, [rid, state.selectedDay, API_BASE]);

  const etaRows = Object.entries(state.telemetry)
    .filter(([, p]) => p.next_customer_id > 0 && p.status !== "done")
    .map(([vid, p]) => ({
      vid,
      stop: p.next_customer_id,
      plan: p.planned_arrival_h,
      eta: p.eta_h,
      spd: p.speed_kmh_sim,
      bad: state.violatedVehicles[vid],
    }));

  const win = mapCtx?.day_window_h || { start: 6, end: 20 };
  const span = Math.max(0.25, Number(win.end) - Number(win.start));
  const tickPct = clamp01((state.simTimeH - Number(win.start)) / span) * 100;

  const onStart = async () => {
    if (!rid) return;
    setErr(null);
    setBusy(true);
    try {
      await startMonitor(rid, state.selectedDay, speedX);
    } catch (e) {
      setErr(String(e.message || e));
    } finally {
      setBusy(false);
    }
  };

  const onStop = async () => {
    if (!rid) return;
    setErr(null);
    try {
      await stopMonitor(rid);
    } catch (e) {
      setErr(String(e.message || e));
    }
  };

  if (!rid) {
    return (
      <div style={{ padding: 24, color: "#666" }}>
        Chưa có <code>run_id</code>. Hoàn tất Planning rồi bấm <strong>Go to Monitoring</strong>.
      </div>
    );
  }

  const nCust = mapCtx?.customers?.length ?? 0;
  const nRoutes = mapCtx?.planned_routes?.length ?? 0;

  return (
    <div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 12, alignItems: "center", marginBottom: 12 }}>
        <span style={{ fontWeight: 600 }}>Ngày (horizon):</span>
        {[0, 1, 2, 3, 4, 5, 6].map((d) => (
          <button
            key={d}
            type="button"
            onClick={() => dispatch({ type: "SET_DAY", day: d })}
            disabled={state.monitoringState === "simulating"}
            style={{
              padding: "6px 10px",
              borderRadius: 6,
              border: "1px solid #ccc",
              background: state.selectedDay === d ? "#e3f2fd" : "#fff",
              cursor: state.monitoringState === "simulating" ? "not-allowed" : "pointer",
            }}
          >
            {d}
          </button>
        ))}
        <label style={{ marginLeft: 12 }}>
          Tốc độ{" "}
          <select value={speedX} onChange={(e) => setSpeedX(+e.target.value)} disabled={state.monitoringState === "simulating"}>
            <option value={30}>30×</option>
            <option value={60}>60×</option>
            <option value={120}>120×</option>
          </select>
        </label>
        <button type="button" onClick={onStart} disabled={busy || state.monitoringState === "simulating"}>
          ▶ Start replay
        </button>
        <button type="button" onClick={onStop} disabled={state.monitoringState !== "simulating"}>
          ■ Stop
        </button>
        <span style={{ fontSize: 13 }}>
          Trạng thái: <strong>{state.monitoringState}</strong>
          {state.monitoringState === "simulating" && (
            <span style={{ color: "#666", marginLeft: 8 }}>
              (tốc độ dropdown = số giờ mô phỏng / 1 giây thực, ví dụ 60× ≈ 1 phút thực ≈ 1 giờ trong ngày)
            </span>
          )}
        </span>
      </div>

      <div
        style={{
          marginBottom: 16,
          padding: "12px 14px",
          background: "#f5f9ff",
          borderRadius: 8,
          border: "1px solid #bbdefb",
        }}
      >
        <div style={{ fontSize: 15, marginBottom: 6 }}>
          <strong>Giờ trong ngày (mô phỏng):</strong>{" "}
          {state.monitoringState === "simulating" && Object.keys(state.telemetry).length === 0 ? (
            <span style={{ color: "#666" }}>Đang chờ bước đầu từ replay (đã bấm Start?)…</span>
          ) : (
            <>
              <span style={{ fontFamily: "ui-monospace, monospace", fontSize: 18 }}>{formatDayHour(state.simTimeH)}</span>
              <span style={{ color: "#666", marginLeft: 10, fontSize: 13 }}>({state.simTimeH.toFixed(2)} h — dạng số thập phân từ solver)</span>
            </>
          )}
        </div>
        <div style={{ position: "relative", height: 10, background: "#e3f2fd", borderRadius: 5, marginTop: 8 }}>
          <div
            style={{
              position: "absolute",
              left: 0,
              top: 0,
              bottom: 0,
              width: `${tickPct}%`,
              background: "linear-gradient(90deg,#1976d2,#42a5f5)",
              borderRadius: 5,
              transition: "width 0.15s ease-out",
            }}
          />
          <div
            style={{
              position: "absolute",
              left: `calc(${tickPct}% - 6px)`,
              top: -3,
              width: 12,
              height: 16,
              background: "#0d47a1",
              borderRadius: 2,
              boxShadow: "0 1px 4px rgba(0,0,0,.25)",
              transition: "left 0.15s ease-out",
            }}
          />
        </div>
        <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, color: "#555", marginTop: 6 }}>
          <span>{formatDayHour(win.start)}</span>
          <span>
            Cửa sổ gợi ý: {formatDayHour(win.start)} – {formatDayHour(win.end)} (từ lịch kế hoạch ngày {state.selectedDay})
          </span>
          <span>{formatDayHour(win.end)}</span>
        </div>
      </div>

      {ctxErr && (
        <div style={{ color: "#b71c1c", marginBottom: 12, fontSize: 13 }}>
          Không tải được bản đồ tĩnh (depot/khách): {ctxErr}
        </div>
      )}
      {mapCtx && !ctxErr && (
        <p style={{ fontSize: 13, color: "#444", marginTop: 0, marginBottom: 12 }}>
          Ngày {state.selectedDay}: <strong>{nCust}</strong> điểm giao trên bản đồ · <strong>{nRoutes}</strong> tuyến xe có lịch · Depot màu xanh dương đậm.
        </p>
      )}

      {err && <div style={{ color: "coral", marginBottom: 12 }}>{err}</div>}
      {state.monitorError && <div style={{ color: "coral", marginBottom: 12 }}>{state.monitorError}</div>}

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
        <section>
          <h4>Xe</h4>
          <ul style={{ fontSize: 13, paddingLeft: 18 }}>
            {Object.entries(state.telemetry).map(([vid, p]) => (
              <li key={vid}>
                <strong>V{vid}</strong> — {p.status}
                {p.next_customer_id > 0 && p.status !== "done" && (
                  <>
                    {" "}
                    → <strong>C{p.next_customer_id}</strong> (kế hoạch đến {formatDayHour(p.planned_arrival_h)})
                  </>
                )}
                {state.violatedVehicles[vid] ? " 🔴 trễ khung giờ" : ""}
                {p.speed_kmh_sim != null && Number.isFinite(p.speed_kmh_sim) && (
                  <span style={{ color: "#555" }}> · ~{Math.round(p.speed_kmh_sim)} km/h (ước lượng)</span>
                )}
              </li>
            ))}
            {Object.keys(state.telemetry).length === 0 && <li>Chưa có telemetry — bấm Start replay</li>}
          </ul>
        </section>
        <section>
          <h4>ETA (theo telemetry)</h4>
          <table style={{ width: "100%", fontSize: 12, borderCollapse: "collapse" }}>
            <thead>
              <tr>
                <th style={{ textAlign: "left" }}>Xe</th>
                <th>Điểm</th>
                <th>Kế hoạch</th>
                <th>ETA</th>
                <th>~km/h</th>
              </tr>
            </thead>
            <tbody>
              {etaRows.map((r) => (
                <tr key={r.vid} style={{ background: r.bad ? "#ffebee" : undefined }}>
                  <td>V{r.vid}</td>
                  <td>C{r.stop}</td>
                  <td>
                    <span style={{ fontFamily: "ui-monospace, monospace" }}>{formatDayHour(r.plan)}</span>
                    <span style={{ color: "#888", fontSize: 10 }}> ({Number(r.plan).toFixed(2)}h)</span>
                  </td>
                  <td>
                    <span style={{ fontFamily: "ui-monospace, monospace" }}>{formatDayHour(r.eta)}</span>
                    <span style={{ color: "#888", fontSize: 10 }}> ({Number(r.eta).toFixed(2)}h)</span>
                  </td>
                  <td style={{ fontFamily: "ui-monospace, monospace" }}>
                    {r.spd != null && Number.isFinite(r.spd) ? Math.round(r.spd) : "—"}
                  </td>
                </tr>
              ))}
              {etaRows.length === 0 && (
                <tr>
                  <td colSpan={5}>—</td>
                </tr>
              )}
            </tbody>
          </table>
        </section>
      </div>

      <section style={{ marginTop: 16 }}>
        <h4>Bản đồ theo dõi</h4>
        <RouteMap telemetry={state.telemetry} violatedVehicles={state.violatedVehicles} mapContext={mapCtx} trails={state.trails} />
      </section>

      <section style={{ marginTop: 16 }}>
        <h4>Khách (cảnh báo stockout)</h4>
        <div style={{ fontSize: 13, display: "flex", flexWrap: "wrap", gap: 8 }}>
          {Object.keys(atRisk).length === 0 && <span>—</span>}
          {Object.keys(atRisk).map((cid) => (
            <span key={cid} style={{ background: "#fff9c4", padding: "4px 8px", borderRadius: 4 }}>
              C{cid} 🟡
            </span>
          ))}
        </div>
      </section>

      <section style={{ marginTop: 16 }}>
        <h4>Alerts</h4>
        <AlertFeed alerts={state.alerts} />
      </section>
    </div>
  );
}
