import { useEffect } from "react";
import L from "leaflet";
import { CircleMarker, GeoJSON, MapContainer, Polyline, TileLayer, Tooltip, useMap } from "react-leaflet";
import "leaflet/dist/leaflet.css";
import { RISK_HEX } from "../utils/riskTier.js";
import { LEGEND, LEGEND_ITEM, LEGEND_SWATCH, MAP_FRAME } from "../components/storm/ForecastMap.jsx";

// County outline + the replayed NHC forecast track + FEMA shelters.
// Shelter dots: navy = outside surge zone/floodplain, orange = in one, grey = closed in the what-if.
const NAVY = "#0f2744";
const GREY = "#9aa3ae";

function FitBounds({ geo, track }) {
  const map = useMap();
  useEffect(() => {
    const b = L.geoJSON(geo).getBounds();
    if (track?.length) track.forEach((p) => b.extend([p.lat, p.lon]));
    if (b.isValid()) map.fitBounds(b, { padding: [16, 16] });
  }, [geo, track, map]);
  return null;
}

export default function CountyMap({ geo, track, shelters, closed = [], height = "h-[420px]" }) {
  const shown = (shelters ?? []).filter((s) => s.lat != null && s.lon != null);
  return (
    <div>
      <div className={`${MAP_FRAME} ${height}`}>
        <MapContainer center={[27, -82]} zoom={7} scrollWheelZoom={false} className="h-full w-full">
          <TileLayer url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" attribution="&copy; OpenStreetMap contributors" />
          <GeoJSON key={JSON.stringify(geo).length} data={geo} style={{ color: NAVY, weight: 2, fillColor: "#2878b5", fillOpacity: 0.08 }} />
          {track?.length > 0 && (
            <Polyline positions={track.map((p) => [p.lat, p.lon])} pathOptions={{ color: RISK_HEX.severe, weight: 3, dashArray: "6 6" }} />
          )}
          {track?.map((p) => (
            <CircleMarker key={p.tau_h} center={[p.lat, p.lon]} radius={4} pathOptions={{ color: RISK_HEX.severe, fillOpacity: 1 }}>
              <Tooltip>{`+${p.tau_h} h: ${p.vmax_kt} kt`}</Tooltip>
            </CircleMarker>
          ))}
          {shown.map((s) => {
            const isClosed = closed.includes(s.name);
            const risky = s.in_surge_zone || s.in_100yr_floodplain;
            return (
              <CircleMarker key={s.id} center={[s.lat, s.lon]} radius={Math.max(3, Math.min(9, Math.sqrt(s.evacuation_capacity || 0) / 6))}
                pathOptions={{ color: isClosed ? GREY : risky ? RISK_HEX.high : NAVY, weight: 1, fillOpacity: isClosed ? 0.3 : 0.75 }}>
                <Tooltip>{`${s.name}: ${s.evacuation_capacity ?? "?"} beds${risky ? " (surge/floodplain)" : ""}${isClosed ? " - closed" : ""}`}</Tooltip>
              </CircleMarker>
            );
          })}
          <FitBounds geo={geo} track={track} />
        </MapContainer>
      </div>
      <div className={LEGEND}>
        <span className={LEGEND_ITEM}><span className={LEGEND_SWATCH} style={{ background: RISK_HEX.severe }} />Forecast track (replay)</span>
        <span className={LEGEND_ITEM}><span className={LEGEND_SWATCH} style={{ background: NAVY }} />Shelter</span>
        <span className={LEGEND_ITEM}><span className={LEGEND_SWATCH} style={{ background: RISK_HEX.high }} />Shelter in surge zone / floodplain</span>
        <span className={LEGEND_ITEM}><span className={LEGEND_SWATCH} style={{ background: GREY }} />Closed (what-if)</span>
      </div>
    </div>
  );
}
