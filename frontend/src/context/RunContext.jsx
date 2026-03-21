import React, { createContext, useCallback, useContext, useMemo, useReducer } from "react";
import { useWebSocket } from "../hooks/useWebSocket.js";

const API_BASE = import.meta.env.VITE_API_URL || "http://127.0.0.1:8000";

const initialState = {
  runState: "idle",
  currentRunId: null,
  result: null,
  mapHtml: null,
  convergence: [],
  telemetry: {},
  alerts: [],
  errorMessage: null,
};

function _detailToString(detail) {
  if (detail == null) return "";
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail.map((x) => (typeof x === "object" ? JSON.stringify(x) : String(x))).join("; ");
  }
  return String(detail);
}

function reducer(state, action) {
  switch (action.type) {
    case "RESET":
      return { ...initialState };
    case "RUN_STARTED":
      return {
        ...state,
        runState: "running",
        currentRunId: action.runId,
        convergence: [],
        telemetry: {},
        alerts: [],
        errorMessage: null,
        result: null,
        mapHtml: null,
      };
    case "WS_MESSAGE": {
      const m = action.payload;
      const rid = state.currentRunId;
      const scopedTypes = new Set(["convergence", "telemetry", "alert", "phase"]);
      if (rid && scopedTypes.has(m.type) && m.run_id != null && m.run_id !== rid) {
        return state;
      }
      if (m.type === "phase" && m.phase === "simulating") {
        return { ...state, runState: "simulating" };
      }
      if (m.type === "convergence") {
        return {
          ...state,
          convergence: [
            ...state.convergence,
            {
              generation: m.generation,
              best_fitness: m.best_fitness,
              avg_fitness: m.avg_fitness,
            },
          ],
        };
      }
      if (m.type === "telemetry") {
        const vid = m.vehicle_id;
        return {
          ...state,
          telemetry: { ...state.telemetry, [vid]: { lat: m.lat, lon: m.lon, status: m.status, day: m.day } },
        };
      }
      if (m.type === "alert" && m.data) {
        return {
          ...state,
          alerts: [{ ...m.data, _ts: Date.now() }, ...state.alerts].slice(0, 200),
        };
      }
      if (m.type === "run_complete") {
        if (rid && m.run_id && m.run_id !== rid) return state;
        return { ...state, runState: "complete" };
      }
      if (m.type === "run_error") {
        if (rid && m.run_id && m.run_id !== rid) return state;
        return {
          ...state,
          runState: "error",
          errorMessage: m.message || "Run failed",
        };
      }
      return state;
    }
    case "RESULT_LOADED":
      return {
        ...state,
        result: action.result,
        mapHtml: action.mapHtml,
      };
    default:
      return state;
  }
}

const RunCtx = createContext(null);

export function RunProvider({ children }) {
  const [state, dispatch] = useReducer(reducer, initialState);

  const onWsMessage = useCallback((data) => {
    dispatch({ type: "WS_MESSAGE", payload: data });
  }, []);

  const fetchInstances = useCallback(async () => {
    const r = await fetch(`${API_BASE}/instances`);
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  }, []);

  const uploadCsv = useCallback(async (file, depotLon, depotLat, n, m) => {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("depot_lon", String(depotLon));
    fd.append("depot_lat", String(depotLat));
    fd.append("n", String(n));
    fd.append("m", String(m));
    const r = await fetch(`${API_BASE}/upload`, { method: "POST", body: fd });
    const text = await r.text();
    if (!r.ok) {
      let msg = text;
      try {
        const j = JSON.parse(text);
        msg = _detailToString(j.detail) || text;
      } catch {
        /* keep msg */
      }
      throw new Error(msg);
    }
    return JSON.parse(text);
  }, []);

  const uploadJson = useCallback(async (file) => {
    const fd = new FormData();
    fd.append("file", file);
    const r = await fetch(`${API_BASE}/upload`, { method: "POST", body: fd });
    const text = await r.text();
    if (!r.ok) {
      let msg = text;
      try {
        const j = JSON.parse(text);
        msg = _detailToString(j.detail) || text;
      } catch {
        /* keep msg */
      }
      throw new Error(msg);
    }
    return JSON.parse(text);
  }, []);

  const startRun = useCallback(async (body) => {
    const r = await fetch(`${API_BASE}/run`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  }, []);

  const pollResult = useCallback(async (runId) => {
    return fetch(`${API_BASE}/result/${runId}`);
  }, []);

  const value = useMemo(
    () => ({
      state,
      dispatch,
      API_BASE,
      fetchInstances,
      uploadCsv,
      uploadJson,
      startRun,
      pollResult,
    }),
    [state, fetchInstances, uploadCsv, uploadJson, startRun, pollResult]
  );

  const wsBase = API_BASE.replace(/^http/, "ws");
  useWebSocket(`${wsBase}/ws`, onWsMessage);

  return <RunCtx.Provider value={value}>{children}</RunCtx.Provider>;
}

export function useRun() {
  const v = useContext(RunCtx);
  if (!v) throw new Error("useRun outside RunProvider");
  return v;
}
