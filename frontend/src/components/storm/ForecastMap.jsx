import L from "leaflet";
import { MapContainer, TileLayer, CircleMarker, Marker, Polyline, Tooltip, useMap } from "react-leaflet";
import { useEffect, useMemo } from "react";
import { getStormSeverityHex } from "../../utils/stormSeverity.js";
import "leaflet/dist/leaflet.css";

// Matches the accent theme color. Leaflet's SVG renderer needs a literal
// color string, not a CSS custom property.
const TRACK_COLOR = "#2878b5";

const FALLBACK_CENTER = [27, -84];
const FALLBACK_ZOOM = 5;

// className "" drops Leaflet's default white box; the span carries the look.
const landfallIcon = L.divIcon({
  className: "",
  html: '<span class="block size-full rotate-45 border-2 border-white bg-[#c62828] shadow-[0_0_0_1px_rgba(15,39,68,0.35)]"></span>',
  iconSize: [14, 14],
  iconAnchor: [7, 7],
});

function FitTrackBounds({ track }) {
  const map = useMap();
  useEffect(() => {
    if (track.length === 0) return;
    const bounds = L.latLngBounds(track.map((p) => [p.latitude, p.longitude]));
    map.fitBounds(bounds, { padding: [32, 32] });
  }, [map, track]);
  return null;
}

function ForecastPointTooltip({ point }) {
  return (
    <div className="flex flex-col gap-0.5 text-[0.78rem] text-ink">
      <strong className="text-navy">{point.forecastTime}</strong>
      <span>{point.windKt} kt &bull; Category {point.category}</span>
    </div>
  );
}

// Map legend, shared look with the staging and risk maps.
export const LEGEND = "absolute bottom-3 left-3 z-500 flex flex-col gap-1.5 rounded-xl border border-sky-100 bg-white/95 backdrop-blur-md px-3.5 py-2.5 text-[0.75rem] font-medium leading-tight text-ink shadow-lg";
export const LEGEND_ITEM = "inline-flex items-center gap-1.5 whitespace-nowrap";
export const LEGEND_SWATCH = "size-2.5 shrink-0 rounded-full border-2";
// isolate: Leaflet's internal z-indexes (up to 1000) stay inside the map box
// instead of painting over the fixed header, sub-nav and Ask AI panel.
export const MAP_FRAME = "relative isolate overflow-hidden rounded-2xl border border-line bg-surface ocean-card-shadow";
export const MAP_SIZE = "h-[420px] w-full max-[760px]:h-80";

export default function ForecastMap({ track }) {
  const polylinePositions = useMemo(() => track.map((p) => [p.latitude, p.longitude]), [track]);

  return (
    <div className={MAP_FRAME}>
      <MapContainer
        center={FALLBACK_CENTER}
        zoom={FALLBACK_ZOOM}
        scrollWheelZoom={false}
        className={MAP_SIZE}
        aria-label="Forecast track map"
      >
        <TileLayer
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          attribution="&copy; OpenStreetMap contributors"
        />
        <FitTrackBounds track={track} />
        <Polyline positions={polylinePositions} pathOptions={{ color: TRACK_COLOR, weight: 2.5, opacity: 0.8 }} />
        {track.map((point) => {
          if (point.pointType === "landfall") {
            return (
              <Marker key={point.id} position={[point.latitude, point.longitude]} icon={landfallIcon}>
                <Tooltip direction="top" offset={[0, -8]}>
                  <ForecastPointTooltip point={point} />
                </Tooltip>
              </Marker>
            );
          }
          const isCurrent = point.pointType === "current";
          return (
            <CircleMarker
              key={point.id}
              center={[point.latitude, point.longitude]}
              radius={isCurrent ? 8 : 6}
              pathOptions={{
                color: isCurrent ? TRACK_COLOR : getStormSeverityHex(point.category),
                weight: 2,
                fillColor: isCurrent ? TRACK_COLOR : "#ffffff",
                fillOpacity: isCurrent ? 1 : 0.9,
              }}
            >
              <Tooltip direction="top" offset={[0, -6]}>
                <ForecastPointTooltip point={point} />
              </Tooltip>
            </CircleMarker>
          );
        })}
      </MapContainer>

      <div className={LEGEND} aria-hidden="true">
        <span className={LEGEND_ITEM}>
          <span className={`${LEGEND_SWATCH} border-[#2878b5] bg-[#2878b5]`} />
          Current Position
        </span>
        <span className={LEGEND_ITEM}>
          <span className={`${LEGEND_SWATCH} border-[#2878b5] bg-white`} />
          Forecast Position
        </span>
        <span className={LEGEND_ITEM}>
          <span className="size-2.5 shrink-0 rotate-45 rounded-[2px] border-2 border-[#c62828] bg-[#c62828]" />
          Expected Landfall
        </span>
      </div>
    </div>
  );
}

