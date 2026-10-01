import L from "leaflet";
import { MapContainer, TileLayer, CircleMarker, Marker, Polyline, Tooltip, useMap } from "react-leaflet";
import { useEffect, useMemo } from "react";
import { getStormSeverityHex } from "../../utils/stormSeverity.js";
import "leaflet/dist/leaflet.css";
import "./ForecastMap.css";

// Matches --accent in App.css. Leaflet's SVG renderer needs a literal
// color string, not a CSS custom property.
const TRACK_COLOR = "#2878b5";

const FALLBACK_CENTER = [27, -84];
const FALLBACK_ZOOM = 5;

const landfallIcon = L.divIcon({
  className: "forecast-marker forecast-marker--landfall",
  html: '<span></span>',
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
    <div className="forecast-point-tooltip">
      <strong>{point.forecastTime}</strong>
      <span>{point.windKt} kt &bull; Category {point.category}</span>
    </div>
  );
}

export default function ForecastMap({ track }) {
  const polylinePositions = useMemo(() => track.map((p) => [p.latitude, p.longitude]), [track]);

  return (
    <div className="forecast-map">
      <MapContainer
        center={FALLBACK_CENTER}
        zoom={FALLBACK_ZOOM}
        scrollWheelZoom={false}
        className="forecast-map__container"
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

      <div className="forecast-map__legend" aria-hidden="true">
        <span className="forecast-map__legend-item">
          <span className="forecast-map__legend-swatch forecast-map__legend-swatch--current" />
          Current Position
        </span>
        <span className="forecast-map__legend-item">
          <span className="forecast-map__legend-swatch forecast-map__legend-swatch--forecast" />
          Forecast Position
        </span>
        <span className="forecast-map__legend-item">
          <span className="forecast-map__legend-swatch forecast-map__legend-swatch--landfall" />
          Expected Landfall
        </span>
      </div>
    </div>
  );
}
