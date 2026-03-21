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
  onGoMonitoring,
  canGoMonitoring,
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
          <p style={{ fontSize: 11, color: "#555", marginTop: 6 }}>
            Mỗi thư mục built-in đã có đủ <strong>n</strong>, <strong>m</strong>, ma trận khoảng cách… trên đĩa — không cần
            nhập depot hay n/m như khi upload CSV.
          </p>
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
          <h3 style={{ marginTop: 16 }}>GA (HGA — scenario B/C)</h3>
          <p style={{ fontSize: 11, color: "#555", margin: "4px 0 8px" }}>
            Pop size, generations, time limit gửi thẳng tới API <code>/run</code> và dùng trong <code>HGA.run()</code> — có
            tác dụng thật, không phải mock.
          </p>
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
          <p style={{ fontSize: 11, color: "#555", margin: "4px 0 0" }}>
            Là <strong>trần</strong> thời gian chạy GA (giây). Có thể trả kết quả <strong>sớm hơn</strong> khi hội tụ hoặc hết cải thiện — không chờ hết số giây nếu đã xong.
          </p>
          <label style={{ marginTop: 8, display: "block" }}>Seed (GA)</label>
          <input type="number" value={seed} onChange={(e) => onSeed(+e.target.value)} style={{ width: "100%" }} />
          <p style={{ fontSize: 11, color: "#555", margin: "4px 0 0" }}>
            Seed khởi tạo RNG của thuật di truyền — cùng instance + cùng seed → có thể lặp lại kết quả B/C.
          </p>
        </>
      )}

      {!showGa && (
        <>
          <label style={{ marginTop: 12, display: "block" }}>Seed (kết quả)</label>
          <input type="number" value={seed} onChange={(e) => onSeed(+e.target.value)} style={{ width: "100%" }} />
          <p style={{ fontSize: 11, color: "#555", margin: "4px 0 0" }}>
            Scenario P/A không chạy HGA; seed chỉ ghi vào <code>result.json</code> / metadata lần chạy (nhãn thí nghiệm).
          </p>
        </>
      )}

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
      {typeof onGoMonitoring === "function" && (
        <button
          type="button"
          onClick={onGoMonitoring}
          disabled={!canGoMonitoring}
          style={{
            marginTop: 12,
            width: "100%",
            padding: 10,
            borderRadius: 8,
            border: "1px solid #1565c0",
            background: canGoMonitoring ? "#e3f2fd" : "#f5f5f5",
            cursor: canGoMonitoring ? "pointer" : "not-allowed",
          }}
        >
          → Go to Monitoring
        </button>
      )}
      {err && <div style={{ color: "coral", marginTop: 8, fontSize: 13 }}>{err}</div>}
      {errorMessage && <div style={{ color: "coral" }}>{errorMessage}</div>}
    </aside>
  );
}
