import React, { useEffect, useState, useCallback } from "react";
import { useRun } from "./context/RunContext.jsx";
import { useMonitoring } from "./context/MonitoringContext.jsx";
import { RunControls } from "./components/RunControls.jsx";
import { KpiCards } from "./components/KpiCards.jsx";
import { ResultDetailPanel } from "./components/ResultDetailPanel.jsx";
import { ConvergenceChart } from "./components/ConvergenceChart.jsx";
import { MonitoringView } from "./components/MonitoringView.jsx";

export default function App() {
  const { state, dispatch, fetchInstances, startRun, pollResult, uploadCsv, uploadJson } = useRun();
  const { dispatch: dispatchMon } = useMonitoring();
  const [tab, setTab] = useState("planning");
  const [instances, setInstances] = useState([]);
  const [source, setSource] = useState("builtin");
  const [instanceKey, setInstanceKey] = useState("");
  const [scenario, setScenario] = useState("C");
  const [seed, setSeed] = useState(42);
  const [popSize, setPopSize] = useState(50);
  const [generations, setGenerations] = useState(200);
  const [timeLimit, setTimeLimit] = useState(300);
  const [preset, setPreset] = useState("full");
  const [uploadToken, setUploadToken] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  const [csvDepotLon, setCsvDepotLon] = useState(105.864567);
  const [csvDepotLat, setCsvDepotLat] = useState(20.996789);
  const [csvN, setCsvN] = useState(20);
  const [csvM, setCsvM] = useState(2);
  const [uploadFile, setUploadFile] = useState(null);
  const [lastRunParams, setLastRunParams] = useState(null);

  useEffect(() => {
    fetchInstances()
      .then((d) => {
        setInstances(d.instances || []);
        if (d.instances?.length) setInstanceKey(d.instances[0]);
      })
      .catch(() => {});
  }, [fetchInstances]);

  useEffect(() => {
    if (state.runState !== "complete" || !state.currentRunId) return;
    let cancelled = false;
    (async () => {
      const r = await pollResult(state.currentRunId);
      if (cancelled) return;
      if (r.status === 200) {
        const j = await r.json();
        dispatch({
          type: "RESULT_LOADED",
          result: j.result,
          mapHtml: j.map_html,
        });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [state.runState, state.currentRunId, pollResult, dispatch]);

  const applyPreset = useCallback((p) => {
    setPreset(p);
    if (p === "fast") {
      setPopSize(20);
      setGenerations(40);
      setTimeLimit(45);
    } else {
      setPopSize(50);
      setGenerations(200);
      setTimeLimit(300);
    }
  }, []);

  const onUpload = async () => {
    setErr(null);
    if (!uploadFile) {
      setErr("Choose a file");
      return;
    }
    setBusy(true);
    try {
      const name = uploadFile.name.toLowerCase();
      const res = name.endsWith(".csv")
        ? await uploadCsv(uploadFile, csvDepotLon, csvDepotLat, csvN, csvM)
        : await uploadJson(uploadFile);
      setUploadToken(res.upload_token);
      setSource("upload");
    } catch (e) {
      setErr(String(e.message || e));
    } finally {
      setBusy(false);
    }
  };

  const onRun = async () => {
    setErr(null);
    if (state.runState !== "idle" && state.runState !== "complete" && state.runState !== "error") {
      setErr("Wait for current run to finish");
      return;
    }
    if (source === "upload" && !uploadToken) {
      setErr("Upload an instance first");
      return;
    }
    if (source === "builtin" && !instanceKey) {
      setErr("Select a built-in instance");
      return;
    }
    setBusy(true);
    const trafficModel = state.trafficModel;
    try {
      const body = {
        scenario,
        seed,
        pop_size: popSize,
        generations,
        time_limit: timeLimit,
        source,
        instance_key: source === "builtin" ? instanceKey : undefined,
        upload_token: source === "upload" ? uploadToken : undefined,
        traffic_model: trafficModel,
      };
      const { run_id } = await startRun(body);
      setLastRunParams({
        scenario,
        seed,
        popSize,
        generations,
        timeLimit,
        source,
        instanceKey: source === "builtin" ? instanceKey : null,
        showGa: scenario === "B" || scenario === "C",
      });
      dispatch({ type: "RUN_STARTED", runId: run_id, trafficModel });
    } catch (e) {
      setErr(String(e.message || e));
      dispatch({ type: "RESET" });
    } finally {
      setBusy(false);
    }
  };

  const goMonitoring = useCallback(() => {
    if (!state.currentRunId) return;
    dispatchMon({ type: "ARM_MONITOR", runId: state.currentRunId, selectedDay: 0 });
    setTab("monitoring");
  }, [state.currentRunId, dispatchMon]);

  const showGa = scenario === "B" || scenario === "C";
  const idle = state.runState === "idle" || state.runState === "complete" || state.runState === "error";
  const canGoMonitoring = state.runState === "complete" && !!state.currentRunId && !!state.result;

  return (
    <div style={{ fontFamily: "system-ui,sans-serif", maxWidth: 1200, margin: "0 auto", padding: 16 }}>
      <header style={{ marginBottom: 16 }}>
        <h1 style={{ margin: 0 }}>IRP-TW-DT</h1>
        <p style={{ color: "#666", marginTop: 4 }}>Planning + Monitoring · FastAPI + Kafka</p>
        <nav style={{ marginTop: 12, display: "flex", gap: 8 }}>
          <button
            type="button"
            onClick={() => setTab("planning")}
            style={{
              padding: "8px 16px",
              borderRadius: 8,
              border: "1px solid #ccc",
              background: tab === "planning" ? "#263238" : "#fff",
              color: tab === "planning" ? "#fff" : "#333",
              cursor: "pointer",
            }}
          >
            Planning
          </button>
          <button
            type="button"
            onClick={() => setTab("monitoring")}
            style={{
              padding: "8px 16px",
              borderRadius: 8,
              border: "1px solid #ccc",
              background: tab === "monitoring" ? "#263238" : "#fff",
              color: tab === "monitoring" ? "#fff" : "#333",
              cursor: "pointer",
            }}
          >
            Monitoring
          </button>
        </nav>
      </header>

      {tab === "planning" && (
        <div style={{ display: "grid", gridTemplateColumns: "280px 1fr", gap: 24 }}>
          <RunControls
            source={source}
            onSourceBuiltin={() => setSource("builtin")}
            onSourceUpload={() => setSource("upload")}
            instances={instances}
            instanceKey={instanceKey}
            onInstanceKey={setInstanceKey}
            uploadFile={uploadFile}
            onFileChange={(e) => setUploadFile(e.target.files?.[0] || null)}
            csvDepotLon={csvDepotLon}
            csvDepotLat={csvDepotLat}
            csvN={csvN}
            csvM={csvM}
            onDepotLon={setCsvDepotLon}
            onDepotLat={setCsvDepotLat}
            onN={setCsvN}
            onM={setCsvM}
            onUpload={onUpload}
            uploadToken={uploadToken}
            scenario={scenario}
            onScenario={setScenario}
            showGa={showGa}
            trafficModel={state.trafficModel}
            onTrafficModel={(v) => dispatch({ type: "SET_TRAFFIC_MODEL", value: v })}
            preset={preset}
            onPreset={applyPreset}
            popSize={popSize}
            generations={generations}
            timeLimit={timeLimit}
            onPopSize={setPopSize}
            onGenerations={setGenerations}
            onTimeLimit={setTimeLimit}
            seed={seed}
            onSeed={setSeed}
            onRun={onRun}
            idle={idle}
            busy={busy}
            runState={state.runState}
            err={err}
            errorMessage={state.errorMessage}
            onGoMonitoring={goMonitoring}
            canGoMonitoring={canGoMonitoring}
          />

          <main>
            {state.runState === "running" && state.solverProgressMessage && (
              <div
                role="status"
                style={{
                  marginBottom: 16,
                  padding: "12px 14px",
                  background: "#fff8e1",
                  border: "1px solid #ffb74d",
                  borderRadius: 8,
                  fontSize: 14,
                  color: "#4e342e",
                  lineHeight: 1.45,
                }}
              >
                <strong style={{ display: "block", marginBottom: 6 }}>Solver vẫn đang chạy (không phải treo)</strong>
                {state.solverProgressMessage}
              </div>
            )}

            {state.runState === "complete" && state.result && <KpiCards result={state.result} />}

            {state.runState === "complete" && state.result && (
              <ResultDetailPanel result={state.result} runParams={lastRunParams} />
            )}

            {showGa && (
              <section style={{ marginTop: 24 }}>
                <h3>Convergence (live)</h3>
                <ConvergenceChart data={state.convergence} configuredGenerations={lastRunParams?.generations} />
              </section>
            )}

            {state.mapHtml && (
              <section style={{ marginTop: 24 }}>
                <h3>Solution map (Folium)</h3>
                <iframe title="map" srcDoc={state.mapHtml} style={{ width: "100%", height: 480, border: "1px solid #ccc" }} />
              </section>
            )}
          </main>
        </div>
      )}

      {tab === "monitoring" && <MonitoringView />}
    </div>
  );
}
