import React from "react";
import { MapContainer, TileLayer, Marker, Popup } from "react-leaflet";
import L from "leaflet";

const icon = L.divIcon({
  className: "veh-marker",
  html: '<div style="width:14px;height:14px;background:#c62828;border-radius:50%;border:2px solid #fff"></div>',
  iconSize: [14, 14],
});

export function RouteMap({ telemetry }) {
  const entries = Object.entries(telemetry || {});
  const center = entries.length
    ? [entries[0][1].lat, entries[0][1].lon]
    : [21.0285, 105.8542];
  return (
    <div style={{ height: 320, width: "100%", borderRadius: 8, overflow: "hidden" }}>
      <MapContainer center={center} zoom={12} style={{ height: "100%", width: "100%" }}>
        <TileLayer url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
        {entries.map(([vid, p]) => (
          <Marker key={vid} position={[p.lat, p.lon]} icon={icon}>
            <Popup>
              Vehicle {vid} — {p.status} (day {p.day})
            </Popup>
          </Marker>
        ))}
      </MapContainer>
    </div>
  );
}
