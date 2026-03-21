import React, { useEffect, useState, useMemo, useRef } from "react";
import { useMonitoring } from "../context/MonitoringContext.jsx";
import { RouteMap } from "./RouteMap.jsx";
import { AlertFeed } from "./AlertFeed.jsx";
import { formatDayHour, formatSimClock24, clamp01 } from "../utils/timeFormat.js";

export function MonitoringView() {
  const { state, dispatch, startMonitor, stopMonitor, requestReplan, injectTraffic, API_BASE } =
    useMonitoring();
  const [speedX, setSpeedX] = useState(60);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [mapCtx, setMapCtx] = useState(null);
  const [ctxErr, setCtxErr] = useState(null);
  const [wallNow, setWallNow] = useState(() => Date.now());
  const [ctxRefresh, setCtxRefresh] = useState(0);
  const [clockH, setClockH] = useState(0);
  const anchorSimHRef = useRef(0);
  const anchorWallRef = useRef(Date.now());

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
        if (!cancelled) {
          setMapCtx(j);
          dispatch({
            type: "CONTEXT_META",
            planRevision: j.plan_revision,
            trafficModelLabel: j.traffic_model,
            planRevisionUpdatedAt: j.plan_revision_updated_at,
            trafficFactor: j.traffic_factor,
            trafficSource: j.traffic_source,
            trafficUpdatedAt: j.traffic_updated_at,
          });
        }
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
  }, [rid, state.selectedDay, API_BASE, dispatch, state.planRevision, ctxRefresh]);

  useEffect(() => {
    if (state.monitoringState !== "simulating" || state.replayStartedAtMs == null) return undefined;
    const id = setInterval(() => setWallNow(Date.now()), 300);
    return () => clearInterval(id);
  }, [state.monitoringState, state.replayStartedAtMs]);

  useEffect(() => {
    const h = Number(state.simTimeH);
    anchorSimHRef.current = Number.isFinite(h) ? h : 0;
    anchorWallRef.current = Date.now();
  }, [state.simTimeH]);

  useEffect(() => {
    if (state.monitoringState !== "simulating") {
      const h = Number(state.simTimeH);
      setClockH(Number.isFinite(h) ? h : 0);
      return undefined;
    }
    let rafId = 0;
    const tick = () => {
      const dtSec = (Date.now() - anchorWallRef.current) / 1000;
      const h = anchorSimHRef.current + dtSec * (speedX / 60);
      setClockH(Math.min(23.9999, Math.max(0, h)));
      rafId = requestAnimationFrame(tick);
    };
    rafId = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(rafId);
  }, [state.monitoringState, speedX, state.simTimeH]);

  const wallElapsedSec = useMemo(() => {
    if (state.replayStartedAtMs == null) return 0;
    return Math.max(0, Math.floor((wallNow - state.replayStartedAtMs) / 1000));
  }, [wallNow, state.replayStartedAtMs]);

  const wallClockLabel = useMemo(() => {
    const t = wallElapsedSec;
    const h = Math.floor(t / 3600);
    const m = Math.floor((t % 3600) / 60);
    const s = t % 60;
    const mmss = `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
    return h > 0 ? `${h}h ${mmss}` : mmss;
  }, [wallElapsedSec]);

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
  const dayPct = clamp01(clockH / 24) * 100;

  const onStart = async () => {
    if (!rid) return;
    setErr(null);
    setBusy(true);
    try {
      await startMonitor(rid, state.selectedDay, speedX);
      setCtxRefresh((n) => n + 1);
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
      dispatch({ type: "MONITOR_STOP_LOCAL" });
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
  const cooldownOn = Date.now() < state.replanCooldownUntilMs;
  const replanBusy = state.monitoringState === "replanning";
  const trafficLbl = state.trafficModelLabel || mapCtx?.traffic_model || "—";
  const tf = state.trafficFactor;
  const ts = state.trafficSource;
  const tu = state.trafficUpdatedAt;
  const tfColor =
    tf == null || Number.isNaN(+tf) ? "#555" : +tf >= 0.8 ? "#2e7d32" : +tf >= 0.5 ? "#f9a825" : "#c62828";

  const onInjectPreset = async (preset) => {
    if (!preset) return;
    setErr(null);
    try {
      await injectTraffic(preset);
    } catch (e) {
      setErr(String(e.message || e));
    }
  };

  return (
    <div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 12, alignItems: "center", marginBottom: 12 }}>
        <span style={{ fontWeight: 600 }}>Ngày (horizon):</span>
        {[0, 1, 2, 3, 4, 5, 6].map((d) => (
          <button
            key={d}
            type="button"
            onClick={() => dispatch({ type: "SET_DAY", day: d })}
            disabled={state.monitoringState === "simulating" || state.monitoringState === "replanning"}
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
        <button type="button" onClick={onStop} disabled={state.monitoringState !== "simulating"} title="Gửi lệnh dừng tới backend (hủy chờ OSRM nếu đang tải tuyến)">
          ■ Stop
        </button>
        <span style={{ fontSize: 13, marginLeft: 8 }}>
          Plan revision: <strong>v{state.planRevision}</strong>
          {state.planRevisionUpdatedAt && (
            <span style={{ color: "#555", fontWeight: 400 }}>
              {" "}
              (cập nhật {new Date(state.planRevisionUpdatedAt).toLocaleString()})
            </span>
          )}
          {" · "}
          Traffic: <strong>{trafficLbl}</strong>
          {tf != null && (
            <span style={{ color: tfColor, marginLeft: 6 }}>
              factor≈{typeof tf === "number" ? tf.toFixed(2) : tf}
              {ts ? ` · ${ts}` : ""}
              {tu ? ` · ${new Date(tu).toLocaleTimeString()}` : ""}
            </span>
          )}
        </span>
        <label style={{ marginLeft: 8, fontSize: 13 }}>
          Inject
          <select
            defaultValue=""
            onChange={(e) => {
              const v = e.target.value;
              e.target.value = "";
              if (!v) return;
              if (v === "custom") {
                const raw = window.prompt("from_h,to_h,factor (0.3–1), label");
                if (!raw) return;
                const parts = raw.split(",");
                if (parts.length < 3) return;
                onInjectPreset({
                  from_h: parseFloat(parts[0]),
                  to_h: parseFloat(parts[1]),
                  factor: parseFloat(parts[2]),
                  label: parts.slice(3).join(",").trim() || "custom",
                });
                return;
              }
              const presets = {
                a: { from_h: 8.0, to_h: 9.5, factor: 0.35, label: "Accident bridge" },
                b: { from_h: 17.0, to_h: 19.0, factor: 0.42, label: "Evening corridor" },
                c: { from_h: 6.5, to_h: 8.5, factor: 0.4, label: "Morning peak" },
              };
              onInjectPreset(presets[v]);
            }}
            style={{ marginLeft: 6 }}
            disabled={state.monitoringState !== "simulating"}
          >
            <option value="">—</option>
            <option value="c">Morning peak</option>
            <option value="a">Accident bridge</option>
            <option value="b">Evening (wrap)</option>
            <option value="custom">Custom…</option>
          </select>
        </label>
        <span style={{ fontSize: 13 }}>
          Trạng thái: <strong>{state.monitoringState}</strong>
          {state.monitoringState === "simulating" && (
            <span style={{ color: "#666", marginLeft: 8 }}>
              (60× = 1 giờ mô phỏng / 1 giây thực; đồng hồ 24h nội suy giữa các bước telemetry theo tốc độ này)
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
        {state.monitoringState === "simulating" && state.replayStartedAtMs != null && (
          <div style={{ fontSize: 14, marginBottom: 8, color: "#333" }}>
            <strong>Đồng hồ replay (thực):</strong>{" "}
            <span style={{ fontFamily: "ui-monospace, monospace", fontSize: 17 }}>{wallClockLabel}</span>
            <span style={{ color: "#666", marginLeft: 10, fontSize: 12 }}>
              (thời gian trôi kể từ lúc bấm Start — độc lập với “giờ trong ngày” mô phỏng)
            </span>
          </div>
        )}
        <div
          style={{
            marginBottom: 12,
            padding: "10px 12px",
            background: "#fff",
            borderRadius: 8,
            border: "1px solid #90caf9",
            display: "flex",
            flexWrap: "wrap",
            alignItems: "center",
            gap: 12,
          }}
        >
          <div>
            <div style={{ fontSize: 12, color: "#555", marginBottom: 4 }}>Đồng hồ ngày mô phỏng (00:00 – 23:59)</div>
            <div style={{ fontFamily: "ui-monospace, monospace", fontSize: 28, fontWeight: 700, letterSpacing: 2, color: "#0d47a1" }}>
              {formatSimClock24(clockH)}
            </div>
            <div style={{ fontSize: 11, color: "#888", marginTop: 4 }}>
              Đồng bộ với <code>simTimeH</code> từ backend; chạy mượt giữa hai bước theo tốc độ × đã chọn.
            </div>
          </div>
          <div style={{ flex: "1 1 220px", minWidth: 200 }}>
            <div style={{ fontSize: 11, color: "#666", marginBottom: 4 }}>Tiến độ cả ngày (0h → 24h)</div>
            <div style={{ position: "relative", height: 8, background: "#eceff1", borderRadius: 4 }}>
              <div
                style={{
                  position: "absolute",
                  left: 0,
                  top: 0,
                  bottom: 0,
                  width: `${dayPct}%`,
                  background: "linear-gradient(90deg,#283593,#5c6bc0)",
                  borderRadius: 4,
                  transition: "width 0.05s linear",
                }}
              />
            </div>
            <div style={{ display: "flex", justifyContent: "space-between", fontSize: 10, color: "#777", marginTop: 4 }}>
              <span>00:00</span>
              <span>12:00</span>
              <span>24:00</span>
            </div>
          </div>
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
        <div
          style={{
            fontSize: 13,
            color: "#333",
            marginTop: 0,
            marginBottom: 12,
            padding: "10px 12px",
            background: "#fafafa",
            borderRadius: 8,
            border: "1px solid #e0e0e0",
          }}
        >
          <strong>Chú thích bản đồ</strong> — Ngày {state.selectedDay}: <strong>{nCust}</strong> điểm khách (nhãn Cx; viền cam = có giao trong ngày),{" "}
          depot nhãn <strong>DEPOT</strong>, <strong>{nRoutes}</strong> tuyến kế hoạch (nét đứt / OSRM nếu API trả hình học), xe đỏ
          theo replay; vệt mờ = đã đi. Nếu đường vẫn gần như thẳng, OSRM có thể lỗi hoặc bị giới hạn — xem log server.
        </div>
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
        <RouteMap
          telemetry={state.telemetry}
          violatedVehicles={state.violatedVehicles}
          mapContext={mapCtx}
          trails={state.trails}
          planRevision={state.planRevision}
          activeCustomerIds={mapCtx?.customer_ids_on_day ?? []}
        />
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
        <AlertFeed
          alerts={state.alerts}
          onReplanTw={
            rid
              ? () => requestReplan(rid, state.selectedDay, Math.max(0.01, state.simTimeH || 0.01))
              : undefined
          }
          replanDisabled={cooldownOn || replanBusy || !rid}
        />
        {state.planRevision > 0 && (
          <p style={{ fontSize: 12, color: "#555", marginTop: 8 }}>
            Nếu replay đang chạy, hệ thống tự khởi động lại để áp dụng lịch mới; bản đồ tuyến cam = lộ trình sau re-plan.
          </p>
        )}
      </section>
    </div>
  );
}
