import React, { createContext, useCallback, useContext, useMemo, useReducer } from "react";

const API_BASE = import.meta.env.VITE_API_URL || "http://127.0.0.1:8000";

const initialState = {
  monitorRunId: null,
  selectedDay: 0,
  monitoringState: "idle",
  telemetry: {},
  trails: {},
  alerts: [],
  simTimeH: 0,
  violatedVehicles: {},
  monitorError: null,
  planRevision: 0,
  trafficModelLabel: "",
  replanCooldownUntilMs: 0,
  preReplanMonitoringState: null,
  planRevisionUpdatedAt: null,
  replayRestartAfterReplan: false,
  trafficFactor: null,
  trafficSource: null,
  trafficUpdatedAt: null,
  replayStartedAtMs: null,
  replaySpeedX: 60,
};

function reducer(state, action) {
  switch (action.type) {
    case "ARM_MONITOR":
      return {
        ...initialState,
        monitorRunId: action.runId,
        selectedDay: action.selectedDay ?? 0,
      };
    case "CONTEXT_META":
      return {
        ...state,
        planRevision: action.planRevision ?? state.planRevision,
        trafficModelLabel: action.trafficModelLabel ?? state.trafficModelLabel,
        planRevisionUpdatedAt: action.planRevisionUpdatedAt ?? state.planRevisionUpdatedAt,
      };
    case "CLEAR_REPLAY_RESTART":
      return { ...state, replayRestartAfterReplan: false };
    case "SET_DAY":
      if (action.day === state.selectedDay) return state;
      return {
        ...state,
        selectedDay: action.day,
        telemetry: {},
        trails: {},
        alerts: [],
        violatedVehicles: {},
        simTimeH: 0,
        monitoringState: "idle",
        monitorError: null,
        preReplanMonitoringState: null,
        replayRestartAfterReplan: false,
        trafficFactor: null,
        trafficSource: null,
        trafficUpdatedAt: null,
        replayStartedAtMs: null,
        replaySpeedX: 60,
      };
    case "MONITOR_STOP_LOCAL":
      return {
        ...state,
        monitoringState: "idle",
        replayStartedAtMs: null,
      };
    case "MON_API_STARTED":
      return {
        ...state,
        monitoringState: "simulating",
        monitorError: null,
        telemetry: {},
        trails: {},
        alerts: [],
        violatedVehicles: {},
        simTimeH: 0,
        preReplanMonitoringState: null,
        replayStartedAtMs: typeof action.startedAtMs === "number" ? action.startedAtMs : null,
        replaySpeedX: typeof action.speedX === "number" && action.speedX > 0 ? action.speedX : 60,
      };
    case "WS_MESSAGE": {
      const m = action.payload;
      const rid = state.monitorRunId;
      if (!rid || m.run_id !== rid) return state;
      if (m.type === "telemetry") {
        if (m.day !== state.selectedDay) return state;
        const vid = m.vehicle_id;
        const st = m.sim_time_h;
        const prevTrail = state.trails[vid] || [];
        const trails = { ...state.trails, [vid]: [...prevTrail, [m.lat, m.lon]].slice(-150) };
        return {
          ...state,
          simTimeH:
            typeof st === "number" ? Math.max(state.simTimeH, st) : state.simTimeH,
          telemetry: {
            ...state.telemetry,
            [vid]: {
              lat: m.lat,
              lon: m.lon,
              status: m.status,
              day: m.day,
              next_customer_id: m.next_customer_id,
              eta_h: m.eta_h,
              planned_arrival_h: m.planned_arrival_h,
              speed_kmh_sim: m.speed_kmh_sim,
            },
          },
          trails,
        };
      }
      if (m.type === "alert" && m.data) {
        const d = m.data;
        if (d.day !== undefined && d.day !== state.selectedDay) return state;
        let vv = { ...state.violatedVehicles };
        if (d.type === "tw_violation" && d.vehicle_id != null) {
          vv[d.vehicle_id] = true;
        }
        return {
          ...state,
          violatedVehicles: vv,
          alerts: [{ ...d, _ts: Date.now() }, ...state.alerts].slice(0, 200),
        };
      }
      if (m.type === "sim_complete" && m.day === state.selectedDay) {
        return {
          ...state,
          monitoringState: m.cancelled ? "idle" : "complete",
          replayStartedAtMs: null,
        };
      }
      if (m.type === "monitor_error" && m.day === state.selectedDay) {
        return {
          ...state,
          monitoringState: "idle",
          monitorError: m.message || "Monitor error",
          replayStartedAtMs: null,
        };
      }
      if (m.type === "replan_started" && m.day === state.selectedDay) {
        return {
          ...state,
          preReplanMonitoringState: state.monitoringState,
          monitoringState: "replanning",
          monitorError: null,
        };
      }
      if (m.type === "replan_complete" && m.day === state.selectedDay) {
        const pr = typeof m.plan_revision === "number" ? m.plan_revision : state.planRevision + 1;
        const back = state.preReplanMonitoringState;
        const nextMon =
          back === "simulating" ? "simulating" : back === "complete" ? "complete" : "idle";
        return {
          ...state,
          monitoringState: nextMon,
          preReplanMonitoringState: null,
          planRevision: pr,
          planRevisionUpdatedAt: m.plan_revision_updated_at ?? state.planRevisionUpdatedAt,
          replanCooldownUntilMs: Date.now() + 120000,
          monitorError: null,
          replayRestartAfterReplan: back === "simulating",
        };
      }
      if (m.type === "replan_error" && m.day === state.selectedDay) {
        const back = state.preReplanMonitoringState;
        const nextMon =
          back === "simulating" ? "simulating" : back === "complete" ? "complete" : "idle";
        return {
          ...state,
          monitoringState: state.monitoringState === "replanning" ? nextMon : state.monitoringState,
          preReplanMonitoringState: null,
          monitorError: m.message || "Re-plan failed",
        };
      }
      if (m.type === "traffic_update") {
        if (m.run_id != null && m.run_id !== rid) return state;
        return {
          ...state,
          trafficFactor: typeof m.factor === "number" ? m.factor : state.trafficFactor,
          trafficSource: m.source != null ? String(m.source) : state.trafficSource,
          trafficUpdatedAt: m.ts != null ? String(m.ts) : new Date().toISOString(),
        };
      }
      return state;
    }
    default:
      return state;
  }
}

const MonCtx = createContext(null);

export function MonitoringProvider({ children }) {
  const [state, dispatch] = useReducer(reducer, initialState);

  const startMonitor = useCallback(async (runId, day, speedX) => {
    const r = await fetch(`${API_BASE}/monitor/start`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ run_id: runId, day, speed_x: speedX }),
    });
    if (!r.ok) throw new Error(await r.text());
    const sx = typeof speedX === "number" && speedX > 0 ? speedX : 60;
    dispatch({ type: "MON_API_STARTED", startedAtMs: Date.now(), speedX: sx });
    return r.json();
  }, []);

  const stopMonitor = useCallback(async (runId) => {
    const r = await fetch(`${API_BASE}/monitor/stop`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ run_id: runId }),
    });
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  }, []);

  const injectTraffic = useCallback(async (body) => {
    const r = await fetch(`${API_BASE}/monitor/traffic/inject`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const text = await r.text();
    if (!r.ok) throw new Error(text || r.statusText);
    if (!text.trim()) return {};
    return JSON.parse(text);
  }, []);

  const requestReplan = useCallback(async (runId, day, simTimeH) => {
    const r = await fetch(`${API_BASE}/monitor/replan`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ run_id: runId, day, sim_time_h: simTimeH }),
    });
    const text = await r.text();
    if (!r.ok) throw new Error(text || r.statusText);
    if (!text.trim()) return {};
    return JSON.parse(text);
  }, []);

  const value = useMemo(
    () => ({
      state,
      dispatch,
      startMonitor,
      stopMonitor,
      requestReplan,
      injectTraffic,
      API_BASE,
    }),
    [state, startMonitor, stopMonitor, requestReplan, injectTraffic]
  );

  return <MonCtx.Provider value={value}>{children}</MonCtx.Provider>;
}

export function useMonitoring() {
  const v = useContext(MonCtx);
  if (!v) throw new Error("useMonitoring outside MonitoringProvider");
  return v;
}
