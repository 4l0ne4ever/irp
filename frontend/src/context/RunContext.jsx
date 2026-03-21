import React, { createContext, useCallback, useContext, useMemo, useReducer } from "react";

const API_BASE = import.meta.env.VITE_API_URL || "http://127.0.0.1:8000";

const initialState = {
  runState: "idle",
  currentRunId: null,
  result: null,
  mapHtml: null,
  convergence: [],
  errorMessage: null,
  trafficModel: "igp",
  solverProgressMessage: null,
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
      return { ...initialState, trafficModel: state.trafficModel };
    case "SET_TRAFFIC_MODEL":
      return { ...state, trafficModel: action.value };
    case "RUN_STARTED":
      return {
        ...initialState,
        trafficModel: action.trafficModel ?? state.trafficModel ?? "igp",
        runState: "running",
        currentRunId: action.runId,
        solverProgressMessage: null,
      };
    case "WS_MESSAGE": {
      const m = action.payload;
      const rid = state.currentRunId;
      if (m.type === "solver_progress") {
        if (rid && m.run_id != null && m.run_id !== rid) return state;
        return { ...state, solverProgressMessage: m.message || null };
      }
      if (m.type === "convergence") {
        if (rid && m.run_id != null && m.run_id !== rid) return state;
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
      if (m.type === "run_complete") {
        if (rid && m.run_id && m.run_id !== rid) return state;
        return { ...state, runState: "complete", solverProgressMessage: null };
      }
      if (m.type === "run_error") {
        if (rid && m.run_id && m.run_id !== rid) return state;
        return {
          ...state,
          runState: "error",
          errorMessage: m.message || "Run failed",
          solverProgressMessage: null,
        };
      }
      return state;
    }
    case "RESULT_LOADED":
      return {
        ...state,
        result: action.result,
        mapHtml: action.mapHtml,
        solverProgressMessage: null,
      };
    default:
      return state;
  }
}

const RunCtx = createContext(null);

export function RunProvider({ children }) {
  const [state, dispatch] = useReducer(reducer, initialState);

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

  return <RunCtx.Provider value={value}>{children}</RunCtx.Provider>;
}

export function useRun() {
  const v = useContext(RunCtx);
  if (!v) throw new Error("useRun outside RunProvider");
  return v;
}
