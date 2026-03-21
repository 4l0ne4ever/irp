import React, { useEffect, useState, useCallback } from "react";
import { useRun } from "./context/RunContext.jsx";
import { RunControls } from "./components/RunControls.jsx";
import { KpiCards } from "./components/KpiCards.jsx";
import { ConvergenceChart } from "./components/ConvergenceChart.jsx";
import { RouteMap } from "./components/RouteMap.jsx";
import { AlertFeed } from "./components/AlertFeed.jsx";

export default function App() {
  const { state, dispatch, fetchInstances, startRun, pollResult, uploadCsv, uploadJson } = useRun();
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
    dispatch({ type: "RESET" });
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
      };
      const { run_id } = await startRun(body);
      dispatch({ type: "RUN_STARTED", runId: run_id });
    } catch (e) {
      setErr(String(e.message || e));
      dispatch({ type: "RESET" });
    } finally {
      setBusy(false);
    }
  };

  const showGa = scenario === "B" || scenario === "C";
  const idle = state.runState === "idle" || state.runState === "complete" || state.runState === "error";

  return (
    <div style={{ fontFamily: "system-ui,sans-serif", maxWidth: 1200, margin: "0 auto", padding: 16 }}>
      <header style={{ marginBottom: 24 }}>
        <h1 style={{ margin: 0 }}>IRP-TW-DT</h1>
        <p style={{ color: "#666", marginTop: 4 }}>React + FastAPI + Kafka</p>
      </header>

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
        />

        <main>
          {state.runState === "complete" && state.result && <KpiCards result={state.result} />}

          {showGa && (
            <section style={{ marginTop: 24 }}>
              <h3>Convergence (live)</h3>
              <ConvergenceChart data={state.convergence} />
            </section>
          )}

          <section style={{ marginTop: 24 }}>
            <h3>Vehicle map (simulation)</h3>
            <RouteMap telemetry={state.telemetry} />
          </section>

          {state.mapHtml && (
            <section style={{ marginTop: 24 }}>
              <h3>Solution map (Folium)</h3>
              <iframe title="map" srcDoc={state.mapHtml} style={{ width: "100%", height: 480, border: "1px solid #ccc" }} />
            </section>
          )}

          <section style={{ marginTop: 24 }}>
            <h3>Alerts</h3>
            <AlertFeed alerts={state.alerts} />
          </section>
        </main>
      </div>
    </div>
  );
}
