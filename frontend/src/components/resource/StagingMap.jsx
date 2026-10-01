import L from "leaflet";
import { MapContainer, TileLayer, CircleMarker, Marker, Polyline, Tooltip, useMap } from "react-leaflet";
import { useEffect, useMemo } from "react";
import { RESOURCE_TYPE_LABELS } from "../../data/resourcePlannerMock.js";
import "leaflet/dist/leaflet.css";
import "./StagingMap.css";

// Matches --accent in App.css. Leaflet's SVG renderer needs a literal
// color string, not a CSS custom property.
const STAGING_COLOR = "#2878b5";

// Mirrors --risk-* tokens in App.css for the same reason.
const RISK_HEX = { low: "#2e7d32", moderate: "#c98a00", high: "#d9641e", severe: "#c62828" };
const RISK_LABELS = {
  low: "Low-Risk Impact Area",
  moderate: "Moderate-Risk Impact Area",
  high: "High-Risk Impact Area",
  severe: "Severe-Risk Impact Area",
};

const FALLBACK_CENTER = [28.9, -83.0];
const FALLBACK_ZOOM = 7;

// A small square divIcon (not a circle or hurricane-style marker) so a
// staging location reads unmistakably as "resources here", distinct from
// the round impact-area markers and from the Forecast Track map's storm
// icons.
function createStagingIcon(selected) {
  return L.divIcon({
    className: `staging-marker${selected ? " staging-marker--selected" : ""}`,
    html: "<span></span>",
    iconSize: selected ? [18, 18] : [14, 14],
    iconAnchor: selected ? [9, 9] : [7, 7],
  });
}

function FitStagingBounds({ points }) {
  const map = useMap();
  useEffect(() => {
    if (points.length === 0) return;
    map.fitBounds(L.latLngBounds(points), { padding: [32, 32] });
  }, [map, points]);
  return null;
}

function PanToSelected({ position }) {
  const map = useMap();
  useEffect(() => {
    if (!position) return;
    map.panTo(position, { animate: true });
  }, [map, position]);
  return null;
}

function StagingTooltip({ deployment }) {
  return (
    <div className="staging-point-tooltip">
      <strong>{deployment.stagingLocation.name}</strong>
      <ul>
        {deployment.resources.map((r) => (
          <li key={r.type}>
            {r.quantity} {RESOURCE_TYPE_LABELS[r.type] ?? r.type}
          </li>
        ))}
      </ul>
      <span>Serves: {deployment.targetAreas.join(", ")}</span>
    </div>
  );
}

function ImpactTooltip({ deployment }) {
  return (
    <div className="staging-point-tooltip">
      <strong>
        {deployment.county}, {deployment.state}
      </strong>
      <span>{RISK_LABELS[deployment.riskTier] ?? "Impact Area"}</span>
      <span>{deployment.predictedOutagePct}% predicted customer outage</span>
    </div>
  );
}

export default function StagingMap({ deployments, selectedId, onSelect }) {
  const allPoints = useMemo(
    () =>
      deployments.flatMap((d) => [
        d.stagingLocation ? [d.stagingLocation.latitude, d.stagingLocation.longitude] : null,
        d.impactAreaLocation ? [d.impactAreaLocation.latitude, d.impactAreaLocation.longitude] : null,
      ]).filter(Boolean),
    [deployments],
  );

  const selectedDeployment = deployments.find((d) => d.id === selectedId);
  const selectedPosition = selectedDeployment?.stagingLocation
    ? [selectedDeployment.stagingLocation.latitude, selectedDeployment.stagingLocation.longitude]
    : null;

  const riskLevelsPresent = useMemo(() => [...new Set(deployments.map((d) => d.riskTier))], [deployments]);

  return (
    <div className="staging-map">
      <MapContainer
        center={FALLBACK_CENTER}
        zoom={FALLBACK_ZOOM}
        scrollWheelZoom={false}
        className="staging-map__container"
        aria-label="Resource staging map"
      >
        <TileLayer
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          attribution="&copy; OpenStreetMap contributors"
        />
        <FitStagingBounds points={allPoints} />
        <PanToSelected position={selectedPosition} />

        {deployments.map((d) =>
          d.stagingLocation && d.impactAreaLocation ? (
            <Polyline
              key={`line-${d.id}`}
              positions={[
                [d.stagingLocation.latitude, d.stagingLocation.longitude],
                [d.impactAreaLocation.latitude, d.impactAreaLocation.longitude],
              ]}
              pathOptions={{ color: STAGING_COLOR, weight: 1.5, opacity: 0.5, dashArray: "4 6" }}
            />
          ) : null,
        )}

        {deployments.map((d) => {
          if (!d.impactAreaLocation) return null;
          const color = RISK_HEX[d.riskTier] ?? STAGING_COLOR;
          return (
            <CircleMarker
              key={`impact-${d.id}`}
              center={[d.impactAreaLocation.latitude, d.impactAreaLocation.longitude]}
              radius={12}
              pathOptions={{ color, weight: 1.5, fillColor: color, fillOpacity: 0.25 }}
            >
              <Tooltip direction="top" offset={[0, -8]}>
                <ImpactTooltip deployment={d} />
              </Tooltip>
            </CircleMarker>
          );
        })}

        {deployments.map((d) => {
          if (!d.stagingLocation) return null;
          const selected = d.id === selectedId;
          return (
            <Marker
              key={`staging-${d.id}`}
              position={[d.stagingLocation.latitude, d.stagingLocation.longitude]}
              icon={createStagingIcon(selected)}
              eventHandlers={{ click: () => onSelect?.(d.id) }}
            >
              <Tooltip direction="top" offset={[0, -8]}>
                <StagingTooltip deployment={d} />
              </Tooltip>
            </Marker>
          );
        })}
      </MapContainer>

      <div className="staging-map__legend" aria-hidden="true">
        <span className="staging-map__legend-item">
          <span className="staging-map__legend-swatch staging-map__legend-swatch--staging" />
          Staging Location
        </span>
        {riskLevelsPresent.map((level) => (
          <span className="staging-map__legend-item" key={level}>
            <span
              className="staging-map__legend-swatch"
              style={{ background: RISK_HEX[level], borderColor: RISK_HEX[level] }}
            />
            {RISK_LABELS[level] ?? `${level} Impact Area`}
          </span>
        ))}
      </div>
    </div>
  );
}
