import React from "react";
import { UploadForm } from "./UploadForm.jsx";

export function RunControls({
  source,
  onSourceBuiltin,
  onSourceUpload,
  instances,
  instanceKey,
  onInstanceKey,
  uploadFile,
  onFileChange,
  csvDepotLon,
  csvDepotLat,
  csvN,
  csvM,
  onDepotLon,
  onDepotLat,
  onN,
  onM,
  onUpload,
  uploadToken,
  scenario,
  onScenario,
  showGa,
  preset,
  onPreset,
  popSize,
  generations,
  timeLimit,
  onPopSize,
  onGenerations,
  onTimeLimit,
  seed,
  onSeed,
  onRun,
  idle,
  busy,
  runState,
  err,
  errorMessage,
}) {
  return (
    <aside style={{ borderRight: "1px solid #eee", paddingRight: 16 }}>
      <h3>Source</h3>
      <label>
        <input type="radio" checked={source === "builtin"} onChange={onSourceBuiltin} /> Built-in
      </label>
      <br />
      <label>
        <input type="radio" checked={source === "upload"} onChange={onSourceUpload} /> Upload
      </label>

      {source === "builtin" && (
        <div style={{ marginTop: 12 }}>
          <label>Instance</label>
          <select value={instanceKey} onChange={(e) => onInstanceKey(e.target.value)} style={{ width: "100%", marginTop: 4 }}>
            {instances.map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
        </div>
      )}

      {source === "upload" && (
        <UploadForm
          uploadFile={uploadFile}
          onFileChange={onFileChange}
          csvDepotLon={csvDepotLon}
          csvDepotLat={csvDepotLat}
          csvN={csvN}
          csvM={csvM}
          onDepotLon={onDepotLon}
          onDepotLat={onDepotLat}
          onN={onN}
          onM={onM}
          onUpload={onUpload}
          busy={busy}
          uploadToken={uploadToken}
        />
      )}

      <h3 style={{ marginTop: 20 }}>Scenario</h3>
      <select value={scenario} onChange={(e) => onScenario(e.target.value)} style={{ width: "100%" }}>
        <option value="P">P — Periodic</option>
        <option value="A">A — RMI</option>
        <option value="B">B — HGA static</option>
        <option value="C">C — HGA dynamic</option>
      </select>

      {showGa && (
        <>
          <h3 style={{ marginTop: 16 }}>GA</h3>
          <label>Preset</label>
          <select value={preset} onChange={(e) => onPreset(e.target.value)} style={{ width: "100%" }}>
            <option value="full">Full defaults</option>
            <option value="fast">Fast demo</option>
          </select>
          <label>Pop size</label>
          <input type="number" value={popSize} onChange={(e) => onPopSize(+e.target.value)} style={{ width: "100%" }} />
          <label>Generations</label>
          <input type="number" value={generations} onChange={(e) => onGenerations(+e.target.value)} style={{ width: "100%" }} />
          <label>Time limit (s)</label>
          <input type="number" value={timeLimit} onChange={(e) => onTimeLimit(+e.target.value)} style={{ width: "100%" }} />
        </>
      )}

      <label style={{ marginTop: 12, display: "block" }}>Seed</label>
      <input type="number" value={seed} onChange={(e) => onSeed(+e.target.value)} style={{ width: "100%" }} />

      <button
        type="button"
        onClick={onRun}
        disabled={!idle || busy}
        style={{
          marginTop: 20,
          width: "100%",
          padding: 12,
          background: "#c62828",
          color: "#fff",
          border: "none",
          borderRadius: 8,
          cursor: idle && !busy ? "pointer" : "not-allowed",
        }}
      >
        Run experiment
      </button>

      <div style={{ marginTop: 12, fontSize: 13 }}>
        Status: <strong>{runState}</strong>
      </div>
      {err && <div style={{ color: "coral", marginTop: 8, fontSize: 13 }}>{err}</div>}
      {errorMessage && <div style={{ color: "coral" }}>{errorMessage}</div>}
    </aside>
  );
}
