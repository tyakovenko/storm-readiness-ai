import { useEffect } from "react";
import L from "leaflet";
import { CircleMarker, GeoJSON, MapContainer, Polyline, TileLayer, Tooltip, useMap } from "react-leaflet";
import "leaflet/dist/leaflet.css";
import { RISK_HEX } from "../utils/riskTier.js";
import { LEGEND, LEGEND_ITEM, LEGEND_SWATCH, MAP_FRAME } from "../components/storm/ForecastMap.jsx";

// County outline + the forecast/replay track + FEMA shelters.
// Shelter dots: navy = outside surge zone/floodplain, orange = in one, grey = closed in the what-if.
const NAVY = "#0f2744";
const GREY = "#9aa3ae";
const TRACK_LABEL = { replay: "Forecast track (replay)", live: "Forecast track (live)", scenario: "Forecast track (scenario)" };

function fmtTrackTime(iso) {
  return `${new Date(iso).toLocaleString("en-US", {
    month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "UTC",
  })}Z`;
}

function FitBounds({ geo, track }) {
  const map = useMap();
  useEffect(() => {
    const b = L.geoJSON(geo).getBounds();
    if (track?.length) track.forEach((p) => b.extend([p.lat, p.lon]));
    if (b.isValid()) map.fitBounds(b, { padding: [16, 16] });
  }, [geo, track, map]);
  return null;
}

// fillColor/fillOpacity/riskLegend let the Risk Map page tint the county polygon itself by its
// real risk tier (or neutral grey when no prediction exists) without changing the default look
// used by Storm Overview and Shelter Planning. onShelterClick is the drill-down hook: selected
// county -> shelter detail, the only level this app's real data supports.
export default function CountyMap({ geo, track, shelters, closed = [], height = "h-[420px]", trackLabel = "replay",
  fillColor = "#2878b5", fillOpacity = 0.08, riskLegend = null, onShelterClick = null, selectedShelterId = null }) {
  const shown = (shelters ?? []).filter((s) => s.lat != null && s.lon != null);
  return (
    <div>
      <div className={`${MAP_FRAME} ${height}`}>
        <MapContainer center={[27, -82]} zoom={7} scrollWheelZoom={false} className="h-full w-full">
          <TileLayer url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" attribution="&copy; OpenStreetMap contributors" />
          <GeoJSON key={JSON.stringify(geo).length} data={geo} style={{ color: NAVY, weight: 2, fillColor, fillOpacity }} />
          {track?.length > 0 && (
            <Polyline positions={track.map((p) => [p.lat, p.lon])} pathOptions={{ color: RISK_HEX.severe, weight: 3, dashArray: "6 6" }} />
          )}
          {track?.map((p) => (
            <CircleMarker key={p.tau_h} center={[p.lat, p.lon]} radius={4} pathOptions={{ color: RISK_HEX.severe, fillOpacity: 1 }}>
              <Tooltip>{`+${p.tau_h} h (${fmtTrackTime(p.valid_utc)}): ${p.vmax_kt} kt`}</Tooltip>
            </CircleMarker>
          ))}
          {shown.map((s) => {
            const isClosed = closed.includes(s.name);
            const risky = s.in_surge_zone || s.in_100yr_floodplain;
            const selected = s.id === selectedShelterId;
            return (
              <CircleMarker key={s.id} center={[s.lat, s.lon]}
                radius={selected ? 11 : Math.max(3, Math.min(9, Math.sqrt(s.evacuation_capacity || 0) / 6))}
                pathOptions={{ color: selected ? "#0f2744" : isClosed ? GREY : risky ? RISK_HEX.high : NAVY,
                  weight: selected ? 3 : 1, fillOpacity: isClosed ? 0.3 : 0.75 }}
                eventHandlers={onShelterClick ? { click: () => onShelterClick(s) } : undefined}>
                <Tooltip>{`${s.name}: ${s.evacuation_capacity ?? "?"} beds${risky ? " (surge/floodplain)" : ""}${isClosed ? " - closed" : ""}`}</Tooltip>
              </CircleMarker>
            );
          })}
          <FitBounds geo={geo} track={track} />
        </MapContainer>
      </div>
      <div className={LEGEND}>
        {riskLegend && (
          <span className={LEGEND_ITEM}>
            <span className={LEGEND_SWATCH} style={{ background: riskLegend.color }} />
            {riskLegend.label}
          </span>
        )}
        {track?.length > 0 && (
          <span className={LEGEND_ITEM}>
            <span className={LEGEND_SWATCH} style={{ background: RISK_HEX.severe }} />
            {TRACK_LABEL[trackLabel] ?? TRACK_LABEL.replay}
          </span>
        )}
        <span className={LEGEND_ITEM}><span className={LEGEND_SWATCH} style={{ background: NAVY }} />Shelter</span>
        <span className={LEGEND_ITEM}><span className={LEGEND_SWATCH} style={{ background: RISK_HEX.high }} />Shelter in surge zone / floodplain</span>
        {closed.length > 0 && (
          <span className={LEGEND_ITEM}><span className={LEGEND_SWATCH} style={{ background: GREY }} />Closed (what-if)</span>
        )}
      </div>
    </div>
  );
}
