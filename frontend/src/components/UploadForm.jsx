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
  const name = (uploadFile?.name || "").toLowerCase();
  const isCsv = name.endsWith(".csv");
  const isJson = name.endsWith(".json");
  const needCsvMeta = isCsv;

  return (
    <div style={{ marginTop: 12 }}>
      <input type="file" accept=".json,.csv" onChange={onFileChange} />
      <div style={{ marginTop: 8, fontSize: 12, color: "#444", lineHeight: 1.4 }}>
        {!uploadFile && (
          <>
            <strong>JSON:</strong> n, m, depot và dữ liệu khách nằm trong file — không cần nhập thêm.
            <br />
            <strong>CSV:</strong> mỗi dòng là một khách; cần nhập depot, <strong>n</strong> (đúng số dòng dữ liệu) và{" "}
            <strong>m</strong> vì định dạng CSV không bắt buộc chứa đủ metadata như JSON.
          </>
        )}
        {uploadFile && isJson && (
          <>
            File JSON: backend đọc <code>metadata</code> + <code>depot</code> + <code>customers</code> — không dùng các
            ô bên dưới.
          </>
        )}
        {uploadFile && isCsv && (
          <>
            File CSV: nhập depot và <strong>n</strong> (bằng số dòng sau dòng <code>#</code> nếu có), <strong>m</strong>{" "}
            (số xe).
          </>
        )}
        {uploadFile && !isJson && !isCsv && (
          <>Đuôi file không phải .csv/.json — server sẽ thử parse như JSON.</>
        )}
      </div>
      {needCsvMeta && (
        <>
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
        </>
      )}
      <button
        type="button"
        onClick={onUpload}
        disabled={busy || !uploadFile || (isCsv && (csvN < 1 || csvM < 1))}
        style={{ marginTop: 8 }}
      >
        Upload
      </button>
      {uploadToken && <div style={{ fontSize: 11, marginTop: 4 }}>Token ready</div>}
    </div>
  );
}
