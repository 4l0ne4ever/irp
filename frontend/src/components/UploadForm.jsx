import React from "react";

export function UploadForm({
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
  busy,
  uploadToken,
}) {
  return (
    <div style={{ marginTop: 12 }}>
      <input type="file" accept=".json,.csv" onChange={onFileChange} />
      <div style={{ marginTop: 8, fontSize: 12 }}>
        CSV: n must equal data row count (after optional # line); set depot and m below.
      </div>
      <div style={{ marginTop: 8 }}>
        <label>Depot lon</label>
        <input
          type="number"
          step="any"
          value={csvDepotLon}
          onChange={(e) => onDepotLon(Number(e.target.value))}
          style={{ width: "100%" }}
        />
      </div>
      <div>
        <label>Depot lat</label>
        <input
          type="number"
          step="any"
          value={csvDepotLat}
          onChange={(e) => onDepotLat(Number(e.target.value))}
          style={{ width: "100%" }}
        />
      </div>
      <div>
        <label>n (rows)</label>
        <input type="number" value={csvN} onChange={(e) => onN(+e.target.value)} style={{ width: "100%" }} />
      </div>
      <div>
        <label>m</label>
        <input type="number" value={csvM} onChange={(e) => onM(+e.target.value)} style={{ width: "100%" }} />
      </div>
      <button type="button" onClick={onUpload} disabled={busy || !uploadFile} style={{ marginTop: 8 }}>
        Upload
      </button>
      {uploadToken && <div style={{ fontSize: 11, marginTop: 4 }}>Token ready</div>}
    </div>
  );
}
