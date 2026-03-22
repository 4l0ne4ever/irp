import React, { useEffect, useMemo } from "react";
import { MapContainer, TileLayer, Marker, Popup, Polyline, CircleMarker, Tooltip, useMap } from "react-leaflet";
import L from "leaflet";
import { formatDayHour } from "../utils/timeFormat.js";

const ROUTE_COLORS = ["#1565c0", "#2e7d32", "#6a1b9a", "#ef6c00", "#00838f", "#5d4037", "#ad1457"];

function distSq(a, b) {
  const dlat = a[0] - b[0];
  const dlon = a[1] - b[1];
  return dlat * dlat + dlon * dlon;
}

/** Cắt polyline kế hoạch tới đỉnh gần vị trí xe nhất (theo tiến độ replay). */
function clipPathToVehicle(path, lat, lon) {
  if (!path || path.length === 0) return [];
  if (path.length === 1) return [[path[0][0], path[0][1]]];
  let bestIdx = 0;
  let bestD = distSq(path[0], [lat, lon]);
  for (let j = 1; j < path.length; j++) {
    const d = distSq(path[j], [lat, lon]);
    if (d < bestD) {
      bestD = d;
      bestIdx = j;
    }
  }
  for (let j = bestIdx + 1; j < path.length; j++) {
    const d = distSq(path[j], [lat, lon]);
    if (d <= bestD * 2) bestIdx = j;
  }
  return path.slice(0, bestIdx + 1).map((p) => [p[0], p[1]]);
}

function vehicleMarkerIcon(vid, violated) {
  const c = ROUTE_COLORS[Number(vid) % ROUTE_COLORS.length];
  const ring = violated ? "#b71c1c" : "#fff";
  const w = violated ? 3 : 2;
  return L.divIcon({
    className: "irp-map-pin",
    html: `<div style="display:flex;align-items:center;justify-content:center;width:22px;height:22px;background:${c};border-radius:50%;border:${w}px solid ${ring};box-shadow:0 2px 8px rgba(0,0,0,.5);font-size:9px;font-weight:800;color:#fff">V${vid}</div>`,
    iconSize: [22, 22],
    iconAnchor: [11, 11],
  });
}

function vehicleWaitingIcon(vid) {
  return L.divIcon({
    className: "irp-map-pin",
    html: `<div style="display:flex;flex-direction:column;align-items:center;justify-content:center;min-width:26px;padding:2px 4px;background:#eceff1;border-radius:8px;border:2px dashed #546e7a;box-shadow:0 1px 4px rgba(0,0,0,.3);font-weight:800;color:#37474f;line-height:1.1"><span style="font-size:9px">V${vid}</span><span style="font-size:7px;opacity:.85">chờ</span></div>`,
    iconSize: [34, 30],
    iconAnchor: [17, 15],
  });
}

function FitPlanBounds({ latLngs }) {
  const map = useMap();
  useEffect(() => {
    if (!latLngs || latLngs.length === 0) return;
    if (latLngs.length === 1) {
      map.setView(latLngs[0], 14);
      return;
    }
    const b = L.latLngBounds(latLngs);
    if (b.isValid()) {
      map.fitBounds(b, { padding: [48, 48], maxZoom: 15 });
    }
  }, [map, latLngs]);
  return null;
}

function customerMarkerIcon(label) {
  return L.divIcon({
    className: "irp-map-pin",
    html: `<div style="font-weight:700;font-size:11px;background:#fff3e0;color:#1a237e;padding:4px 7px;border-radius:8px;border:2px solid #e65100;box-shadow:0 2px 8px rgba(0,0,0,.35);white-space:nowrap">${label}</div>`,
    iconSize: [44, 24],
    iconAnchor: [22, 12],
  });
}

export function RouteMap({
  telemetry,
  violatedVehicles,
  mapContext,
  trails,
  planRevision = 0,
  activeCustomerIds = [],
  replayMode = false,
}) {
  const vv = violatedVehicles || {};
  const entries = Object.entries(telemetry || {});

  const depot = mapContext?.depot;
  const customersAll = mapContext?.customers || [];
  const planned = mapContext?.planned_routes || [];
  const trailEntries = Object.entries(trails || {});
  const revisedPlan = planRevision > 0;

  const activeSet = useMemo(() => new Set((activeCustomerIds || []).map(Number)), [activeCustomerIds]);

  const customers = useMemo(() => {
    if (!activeSet.size) return [];
    return customersAll.filter((c) => c.lat != null && c.lon != null && activeSet.has(Number(c.id)));
  }, [customersAll, activeSet]);

  const plannedVehicleIds = useMemo(() => {
    const s = new Set();
    for (const pr of planned) {
      if (pr?.vehicle_id != null) s.add(String(pr.vehicle_id));
    }
    return s;
  }, [planned]);

  const telemetryVidSet = useMemo(() => new Set(entries.map(([k]) => String(k))), [entries]);

  const depotIcon = useMemo(
    () =>
      L.divIcon({
        className: "irp-map-pin",
        html: `<div style="font-weight:800;font-size:11px;letter-spacing:0.5px;background:#0d47a1;color:#fff;padding:5px 10px;border-radius:8px;border:2px solid #fff;box-shadow:0 2px 10px rgba(0,0,0,.4)">DEPOT</div>`,
        iconSize: [72, 28],
        iconAnchor: [36, 14],
      }),
    []
  );

  const fitPointsPlanOnly = useMemo(() => {
    const pts = [];
    if (depot?.lat != null && depot?.lon != null) pts.push([depot.lat, depot.lon]);
    for (const c of customers) {
      pts.push([c.lat, c.lon]);
    }
    for (const pr of planned) {
      for (const pair of pr.path || []) {
        if (pair?.length >= 2) pts.push([pair[0], pair[1]]);
      }
    }
    return pts;
  }, [depot, customers, planned]);

  const center = fitPointsPlanOnly.length ? fitPointsPlanOnly[0] : [21.0285, 105.8542];

  const fitKey = useMemo(
    () => JSON.stringify(fitPointsPlanOnly.slice(0, 8)) + planned.length + customers.length + (replayMode ? "r1" : "r0"),
    [fitPointsPlanOnly, planned.length, customers.length, replayMode]
  );

  const resolvePlannedPositions = (pr) => {
    const path = (pr.path || []).map(([lat, lon]) => [lat, lon]);
    if (path.length < 2) return null;
    const vid = String(pr.vehicle_id);
    const p = telemetry?.[vid];
    if (!replayMode) return path;
    if (!p) return null;
    if (p.status === "done") return path;
    let clipped = clipPathToVehicle(path, p.lat, p.lon);
    if (clipped.length < 2 && path.length >= 2) {
      clipped = [
        [path[0][0], path[0][1]],
        [p.lat, p.lon],
      ];
    }
    return clipped.length >= 2 ? clipped : null;
  };

  return (
    <div style={{ height: 420, width: "100%", borderRadius: 8, overflow: "hidden", border: "1px solid #ddd" }}>
      <style>{`
        .irp-map-pin { background: transparent !important; border: none !important; }
        .leaflet-marker-icon.irp-map-pin { margin-left: 0 !important; margin-top: 0 !important; }
        .irp-speed-tip {
          padding: 2px 8px !important;
          font-size: 11px !important;
          font-weight: 700 !important;
          border-radius: 6px !important;
          box-shadow: 0 2px 6px rgba(0,0,0,.25) !important;
        }
      `}</style>
      {!mapContext && (
        <p style={{ margin: "0 0 8px", fontSize: 12, color: "#b71c1c" }}>
          Chưa có dữ liệu /monitor/context — chỉ thấy vệt telemetry, không có depot/khách/tuyến kế hoạch. Kiểm tra API (VITE_API_URL) và lỗi mạng.
        </p>
      )}
      <MapContainer center={center} zoom={12} style={{ height: mapContext ? "100%" : "calc(100% - 28px)", width: "100%" }} scrollWheelZoom>
        <TileLayer attribution="&copy; OpenStreetMap" url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
        <FitPlanBounds key={fitKey} latLngs={fitPointsPlanOnly} />

        {planned.map((pr, idx) => {
          const positions = resolvePlannedPositions(pr);
          if (!positions || positions.length < 2) return null;
          const vid = Number(pr.vehicle_id);
          const base = ROUTE_COLORS[vid % ROUTE_COLORS.length];
          const dash = revisedPlan ? undefined : `${10 + (idx % 4) * 3}, ${8 + (idx % 2) * 2}`;
          return (
            <Polyline
              key={`pl-${pr.vehicle_id}-${idx}`}
              positions={positions}
              pathOptions={{
                color: base,
                weight: revisedPlan ? 7 : 5,
                opacity: revisedPlan ? 0.92 : 0.78,
                lineCap: "round",
                lineJoin: "round",
                dashArray: dash,
              }}
            >
              <Popup>
                Xe <strong>V{pr.vehicle_id}</strong> — lịch kế hoạch
                {replayMode ? " (chỉ hiện đoạn đã tới theo vị trí xe)" : ""}
                {revisedPlan ? " · sau re-plan" : ""}
              </Popup>
            </Polyline>
          );
        })}

        {trailEntries.map(([vid, path]) => {
          const positions = (path || []).filter((pt) => pt?.length >= 2);
          if (positions.length < 2) return null;
          const c = ROUTE_COLORS[Number(vid) % ROUTE_COLORS.length];
          return (
            <Polyline
              key={`trail-${vid}`}
              positions={positions}
              pathOptions={{
                color: c,
                weight: 4,
                opacity: replayMode ? 0.55 : 0.4,
                lineCap: "round",
                lineJoin: "round",
              }}
            />
          );
        })}

        {depot?.lat != null && depot?.lon != null && (
          <>
            <CircleMarker
              center={[depot.lat, depot.lon]}
              radius={16}
              pathOptions={{ color: "#0d47a1", fillColor: "#1976d2", fillOpacity: 0.25, weight: 2 }}
            />
            <Marker position={[depot.lat, depot.lon]} icon={depotIcon} zIndexOffset={800}>
              <Popup>
                <strong>Depot</strong>
                <br />
                Xuất phát / kết thúc tuyến
              </Popup>
            </Marker>
          </>
        )}

        {replayMode &&
          depot?.lat != null &&
          depot?.lon != null &&
          [...plannedVehicleIds].filter((vid) => !telemetryVidSet.has(vid)).map((vid, i) => {
            const j = 0.0001 * (i + 1);
            return (
            <Marker key={`vw-${vid}`} position={[depot.lat + j, depot.lon + j]} icon={vehicleWaitingIcon(vid)} zIndexOffset={750}>
              <Popup>
                Xe <strong>V{vid}</strong> — chờ replay (phát tuần tự sau xe khác)
              </Popup>
            </Marker>
            );
          })}

        {customers.map((c) => (
          <Marker key={`c-${c.id}`} position={[c.lat, c.lon]} icon={customerMarkerIcon(c.label || `C${c.id}`)} zIndexOffset={600}>
            <Popup>
              Điểm <strong>{c.label}</strong>
              <div style={{ marginTop: 6, color: "#e65100" }}>Có giao trong ngày đang xem</div>
            </Popup>
          </Marker>
        ))}

        {entries.map(([vid, p]) => {
          const spd =
            p.speed_kmh_sim != null && Number.isFinite(p.speed_kmh_sim) ? `${Math.round(p.speed_kmh_sim)} km/h` : "— km/h";
          return (
            <Marker key={`v-${vid}`} position={[p.lat, p.lon]} icon={vehicleMarkerIcon(vid, !!vv[vid])} zIndexOffset={900 + Number(vid)}>
              <Tooltip permanent direction="top" offset={[0, -26]} opacity={0.95} className="irp-speed-tip">
                ~{spd}
              </Tooltip>
              <Popup>
                Xe <strong>V{vid}</strong> — {p.status}
                <br />
                Ngày {p.day}
                {p.next_customer_id > 0 && (
                  <>
                    <br />
                    Đang hướng tới <strong>C{p.next_customer_id}</strong>
                    <br />
                    Kế hoạch đến {formatDayHour(p.planned_arrival_h)} · ETA mô phỏng {formatDayHour(p.eta_h)}
                  </>
                )}
                {p.next_customer_id === 0 && p.status !== "done" && (
                  <>
                    <br />
                    Về depot
                  </>
                )}
                {p.speed_kmh_sim != null && Number.isFinite(p.speed_kmh_sim) && (
                  <>
                    <br />
                    Tốc độ ~{Math.round(p.speed_kmh_sim)} km/h
                  </>
                )}
              </Popup>
            </Marker>
          );
        })}
      </MapContainer>
      <p style={{ margin: "6px 0 0", fontSize: 11, color: "#555" }}>
        Khách chỉ trong ngày (có giao). Replay: tuyến kế hoạch và vệt chỉ kéo dài theo vị trí xe; xe chưa tới lượt đứng depot (viền nét đứt). Tooltip trên xe: tốc độ ước lượng.
      </p>
    </div>
  );
}
