import React, { useEffect, useMemo } from "react";
import { MapContainer, TileLayer, Marker, Popup, Polyline, CircleMarker, useMap } from "react-leaflet";
import L from "leaflet";
import { formatDayHour } from "../utils/timeFormat.js";

const ROUTE_COLORS = ["#1565c0", "#2e7d32", "#6a1b9a", "#ef6c00", "#00838f", "#5d4037", "#ad1457"];

function makeVehicleIcon(color) {
  return L.divIcon({
    className: "veh-marker",
    html: `<div style="width:16px;height:16px;background:${color};border-radius:50%;border:3px solid #fff;box-shadow:0 1px 4px rgba(0,0,0,.4)"></div>`,
    iconSize: [16, 16],
  });
}

const iconOk = makeVehicleIcon("#c62828");
const iconBad = makeVehicleIcon("#b71c1c");

function FitBounds({ latLngs }) {
  const map = useMap();
  useEffect(() => {
    if (!latLngs || latLngs.length === 0) return;
    const b = L.latLngBounds(latLngs);
    if (b.isValid()) {
      map.fitBounds(b, { padding: [48, 48], maxZoom: 14 });
    }
  }, [map, latLngs]);
  return null;
}

export function RouteMap({ telemetry, violatedVehicles, mapContext, trails }) {
  const vv = violatedVehicles || {};
  const entries = Object.entries(telemetry || {});

  const depot = mapContext?.depot;
  const customers = mapContext?.customers || [];
  const planned = mapContext?.planned_routes || [];
  const trailEntries = Object.entries(trails || {});

  const fitPoints = useMemo(() => {
    const pts = [];
    const tel = Object.entries(telemetry || {});
    if (depot?.lat != null && depot?.lon != null) pts.push([depot.lat, depot.lon]);
    for (const c of customers) {
      if (c.lat != null && c.lon != null) pts.push([c.lat, c.lon]);
    }
    for (const pr of planned) {
      for (const pair of pr.path || []) {
        if (pair?.length >= 2) pts.push([pair[0], pair[1]]);
      }
    }
    for (const [, path] of Object.entries(trails || {})) {
      for (const pt of path || []) {
        if (pt?.length >= 2) pts.push([pt[0], pt[1]]);
      }
    }
    for (const [, p] of tel) {
      if (p.lat != null && p.lon != null) pts.push([p.lat, p.lon]);
    }
    return pts;
  }, [depot, customers, planned, trails, telemetry]);

  const center = fitPoints.length ? fitPoints[0] : [21.0285, 105.8542];

  return (
    <div style={{ height: 420, width: "100%", borderRadius: 8, overflow: "hidden", border: "1px solid #ddd" }}>
      <MapContainer center={center} zoom={12} style={{ height: "100%", width: "100%" }} scrollWheelZoom>
        <TileLayer url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
        <FitBounds latLngs={fitPoints} />

        {planned.map((pr, idx) => {
          const path = (pr.path || []).map(([lat, lon]) => [lat, lon]);
          if (path.length < 2) return null;
          const color = ROUTE_COLORS[Number(pr.vehicle_id) % ROUTE_COLORS.length];
          return (
            <Polyline
              key={`pl-${pr.vehicle_id}-${idx}`}
              positions={path}
              pathOptions={{
                color,
                weight: 4,
                opacity: 0.55,
                dashArray: "10 8",
              }}
            >
              <Popup>
                Lịch xe V{pr.vehicle_id}: đường đi theo OSRM (public router) giữa các điểm của lộ trình kế hoạch — trùng logic replay.
              </Popup>
            </Polyline>
          );
        })}

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
                opacity: 0.4,
                lineCap: "round",
                lineJoin: "round",
              }}
            />
          );
        })}

        {depot?.lat != null && depot?.lon != null && (
          <CircleMarker center={[depot.lat, depot.lon]} radius={12} pathOptions={{ color: "#0d47a1", fillColor: "#1976d2", fillOpacity: 0.95, weight: 2 }}>
            <Popup>
              <strong>Depot</strong>
              <br />
              Xuất phát / kết thúc tuyến xe
            </Popup>
          </CircleMarker>
        )}

        {customers.map((c) => (
          <CircleMarker key={`c-${c.id}`} center={[c.lat, c.lon]} radius={7} pathOptions={{ color: "#37474f", fillColor: "#78909c", fillOpacity: 0.9, weight: 2 }}>
            <Popup>
              Điểm giao <strong>{c.label}</strong>
            </Popup>
          </CircleMarker>
        ))}

        {entries.map(([vid, p]) => (
          <Marker key={`v-${vid}`} position={[p.lat, p.lon]} icon={vv[vid] ? iconBad : iconOk} zIndexOffset={800}>
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
                  Tốc độ (ước lượng từ bước mô phỏng): ~{Math.round(p.speed_kmh_sim)} km/h
                </>
              )}
            </Popup>
          </Marker>
        ))}
      </MapContainer>
      <p style={{ margin: "6px 0 0", fontSize: 11, color: "#555" }}>
        Nét đứt: lộ trình kế hoạch theo đường (OSRM) · Nét liền mờ cùng màu: quãng xe đã “chạy” trong replay · Depot / khách / vị trí live như trên.
      </p>
    </div>
  );
}
