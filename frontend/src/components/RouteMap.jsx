import React, { useEffect, useMemo } from "react";
import { MapContainer, TileLayer, Marker, Popup, Polyline, useMap, Pane } from "react-leaflet";
import L from "leaflet";
import { formatDayHour } from "../utils/timeFormat.js";

const ROUTE_COLORS = ["#1565c0", "#2e7d32", "#6a1b9a", "#ef6c00", "#00838f", "#5d4037", "#ad1457"];

function makeVehicleIcon(color) {
  return L.divIcon({
    className: "irp-map-pin",
    html: `<div style="width:18px;height:18px;background:${color};border-radius:50%;border:3px solid #fff;box-shadow:0 2px 8px rgba(0,0,0,.45)"></div>`,
    iconSize: [18, 18],
    iconAnchor: [9, 9],
  });
}

const iconOk = makeVehicleIcon("#d32f2f");
const iconBad = makeVehicleIcon("#b71c1c");

/** Fit map to depot + all customers + planned polylines only (not live trail / vehicle) so depot & stops stay in view. */
function FitPlanBounds({ latLngs }) {
  const map = useMap();
  useEffect(() => {
    if (!latLngs || latLngs.length === 0) return;
    const b = L.latLngBounds(latLngs);
    if (b.isValid()) {
      map.fitBounds(b, { padding: [56, 56], maxZoom: 15 });
    }
  }, [map, latLngs]);
  return null;
}

function customerMarkerIcon(label, onRouteToday) {
  const border = onRouteToday ? "#e65100" : "#546e7a";
  const bg = onRouteToday ? "#fff3e0" : "#eceff1";
  return L.divIcon({
    className: "irp-map-pin",
    html: `<div style="font-weight:700;font-size:11px;background:${bg};color:#1a237e;padding:4px 7px;border-radius:8px;border:2px solid ${border};box-shadow:0 2px 8px rgba(0,0,0,.35);white-space:nowrap">${label}</div>`,
    iconSize: [44, 24],
    iconAnchor: [22, 12],
  });
}

const depotMarkerIcon = L.divIcon({
  className: "irp-map-pin",
  html: `<div style="font-weight:800;font-size:11px;letter-spacing:0.5px;background:#0d47a1;color:#fff;padding:5px 10px;border-radius:8px;border:2px solid #fff;box-shadow:0 2px 10px rgba(0,0,0,.4)">DEPOT</div>`,
  iconSize: [72, 28],
  iconAnchor: [36, 14],
});

export function RouteMap({
  telemetry,
  violatedVehicles,
  mapContext,
  trails,
  planRevision = 0,
  activeCustomerIds = [],
}) {
  const vv = violatedVehicles || {};
  const entries = Object.entries(telemetry || {});

  const depot = mapContext?.depot;
  const customers = mapContext?.customers || [];
  const planned = mapContext?.planned_routes || [];
  const trailEntries = Object.entries(trails || {});
  const revisedPlan = planRevision > 0;

  const activeSet = useMemo(() => new Set((activeCustomerIds || []).map(Number)), [activeCustomerIds]);

  const fitPointsPlanOnly = useMemo(() => {
    const pts = [];
    if (depot?.lat != null && depot?.lon != null) pts.push([depot.lat, depot.lon]);
    for (const c of customers) {
      if (c.lat != null && c.lon != null) pts.push([c.lat, c.lon]);
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
    () => JSON.stringify(fitPointsPlanOnly.slice(0, 5)) + planned.length + (customers?.length || 0),
    [fitPointsPlanOnly, planned.length, customers.length]
  );

  return (
    <div style={{ height: 420, width: "100%", borderRadius: 8, overflow: "hidden", border: "1px solid #ddd" }}>
      <style>{`
        .irp-map-pin { background: transparent !important; border: none !important; }
      `}</style>
      {!mapContext && (
        <p style={{ margin: "0 0 8px", fontSize: 12, color: "#b71c1c" }}>
          Chưa có dữ liệu /monitor/context — không thể vẽ depot, khách và tuyến kế hoạch. Kiểm tra API và WebSocket.
        </p>
      )}
      <MapContainer center={center} zoom={12} style={{ height: mapContext ? "100%" : "calc(100% - 28px)", width: "100%" }} scrollWheelZoom>
        <TileLayer url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
        <FitPlanBounds key={fitKey} latLngs={fitPointsPlanOnly} />

        <Pane name="planned-routes" style={{ zIndex: 380 }}>
          {planned.map((pr, idx) => {
            const path = (pr.path || []).map(([lat, lon]) => [lat, lon]);
            if (path.length < 2) return null;
            const base = ROUTE_COLORS[Number(pr.vehicle_id) % ROUTE_COLORS.length];
            const color = revisedPlan ? "#e65100" : base;
            return (
              <Polyline
                key={`pl-${pr.vehicle_id}-${idx}`}
                positions={path}
                pathOptions={{
                  color,
                  weight: revisedPlan ? 6 : 5,
                  opacity: revisedPlan ? 0.9 : 0.75,
                  dashArray: revisedPlan ? undefined : "12 10",
                }}
              >
                <Popup>
                  Lịch xe V{pr.vehicle_id}
                  {revisedPlan ? " (sau re-plan)" : ""}: hình học từ OSRM public (từng chặng). Nếu thấy đường gần như thẳng, OSRM có thể từ chối/lỗi — xem log backend.
                </Popup>
              </Polyline>
            );
          })}
        </Pane>

        <Pane name="trails" style={{ zIndex: 400 }}>
          {trailEntries.map(([vid, path]) => {
            const positions = (path || []).filter((pt) => pt?.length >= 2);
            if (positions.length < 2) return null;
            const color = ROUTE_COLORS[Number(vid) % ROUTE_COLORS.length];
            return (
              <Polyline
                key={`trail-${vid}`}
                positions={positions}
                pathOptions={{
                  color,
                  weight: 5,
                  opacity: 0.45,
                  lineCap: "round",
                  lineJoin: "round",
                }}
              />
            );
          })}
        </Pane>

        <Pane name="stops" style={{ zIndex: 480 }}>
          {depot?.lat != null && depot?.lon != null && (
            <Marker position={[depot.lat, depot.lon]} icon={depotMarkerIcon}>
              <Popup>
                <strong>Depot</strong>
                <br />
                Xuất phát / kết thúc tuyến
              </Popup>
            </Marker>
          )}

          {customers.filter((c) => c.lat != null && c.lon != null).map((c) => (
            <Marker
              key={`c-${c.id}`}
              position={[c.lat, c.lon]}
              icon={customerMarkerIcon(c.label || `C${c.id}`, activeSet.has(Number(c.id)))}
            >
              <Popup>
                Điểm <strong>{c.label}</strong>
                {activeSet.has(Number(c.id)) ? <div style={{ marginTop: 6, color: "#e65100" }}>Có giao trong ngày đang xem</div> : null}
              </Popup>
            </Marker>
          ))}
        </Pane>

        <Pane name="vehicles" style={{ zIndex: 650 }}>
          {entries.map(([vid, p]) => (
            <Marker key={`v-${vid}`} position={[p.lat, p.lon]} icon={vv[vid] ? iconBad : iconOk} zIndexOffset={900}>
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
          ))}
        </Pane>
      </MapContainer>
      <p style={{ margin: "6px 0 0", fontSize: 11, color: "#555" }}>
        {revisedPlan ? "Cam đậm: lộ trình sau re-plan · " : "Xanh (nét đứt): lộ trình kế hoạch OSRM · "}
        Nét liền mờ: quãng xe đã đi · DEPOT / nhãn Cx: điểm dừng (viền cam = có giao trong ngày).
      </p>
    </div>
  );
}
