import React, { useCallback } from "react";
import { useRun } from "../context/RunContext.jsx";
import { useMonitoring } from "../context/MonitoringContext.jsx";
import { useWebSocket } from "../hooks/useWebSocket.js";

const PLANNING_TYPES = new Set(["convergence", "run_complete", "run_error", "solver_progress"]);
const MONITORING_TYPES = new Set([
  "telemetry",
  "alert",
  "sim_complete",
  "monitor_error",
  "monitor_stopped",
  "replan_started",
  "replan_complete",
  "replan_error",
  "traffic_update",
]);

/**
 * Single WS connection; route messages to Planning vs Monitoring reducers.
 */
export function WebSocketBridge() {
  const { dispatch: dPlan } = useRun();
  const { dispatch: dMon } = useMonitoring();

  const onMsg = useCallback(
    (m) => {
      if (PLANNING_TYPES.has(m.type)) {
        dPlan({ type: "WS_MESSAGE", payload: m });
      }
      if (MONITORING_TYPES.has(m.type)) {
        dMon({ type: "WS_MESSAGE", payload: m });
      }
    },
    [dPlan, dMon]
  );

  const api = import.meta.env.VITE_API_URL || "http://127.0.0.1:8000";
  const wsBase = api.replace(/^http/, "ws");
  useWebSocket(`${wsBase}/ws`, onMsg);
  return null;
}
