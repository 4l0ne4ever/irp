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
};

function reducer(state, action) {
  switch (action.type) {
    case "ARM_MONITOR":
      return {
        ...initialState,
        monitorRunId: action.runId,
        selectedDay: action.selectedDay ?? 0,
      };
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
          simTimeH: typeof st === "number" ? Math.max(state.simTimeH, st) : state.simTimeH,
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
        return { ...state, monitoringState: "complete" };
      }
      if (m.type === "monitor_error" && m.day === state.selectedDay) {
        return { ...state, monitoringState: "idle", monitorError: m.message || "Monitor error" };
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
    dispatch({ type: "MON_API_STARTED" });
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

  const value = useMemo(
    () => ({
      state,
      dispatch,
      startMonitor,
      stopMonitor,
      API_BASE,
    }),
    [state, startMonitor, stopMonitor]
  );

  return <MonCtx.Provider value={value}>{children}</MonCtx.Provider>;
}

export function useMonitoring() {
  const v = useContext(MonCtx);
  if (!v) throw new Error("useMonitoring outside MonitoringProvider");
  return v;
}
