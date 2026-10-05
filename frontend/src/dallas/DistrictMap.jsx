import { useEffect, useMemo } from "react";
import L from "leaflet";
import { GeoJSON, MapContainer, TileLayer, useMap } from "react-leaflet";
import "leaflet/dist/leaflet.css";
import { RISK_HEX } from "../utils/riskTier.js";
import { LEGEND, LEGEND_ITEM, LEGEND_SWATCH, MAP_FRAME } from "../components/storm/ForecastMap.jsx";

// Dallas council districts shaded by one value per district (expected requests,
// trucks assigned...). Four bands from the data's own spread, reusing the app's
// risk colors so "darker = more" reads the same as on the hurricane screens.
const BANDS = ["low", "moderate", "high", "severe"];
const NO_DATA_HEX = "#9aa3ae";

function bandOf(value, cuts) {
  if (value == null) return null;
  return BANDS[cuts.filter((c) => value > c).length];
}

function FitToDistricts({ geojson }) {
  const map = useMap();
  useEffect(() => {
    const b = L.geoJSON(geojson).getBounds();
    if (b.isValid()) map.fitBounds(b, { padding: [12, 12] });
  }, [geojson, map]);
  return null;
}

// Plain text for Leaflet tooltips (a string would be parsed as HTML).
function textEl(text) {
  const el = document.createElement("span");
  el.textContent = text;
  return el;
}

export default function DistrictMap({ geojson, values, format, legendTitle, selected, onSelect }) {
  const nums = Object.values(values).filter((v) => v != null).sort((a, b) => a - b);
  // Quartile cuts; with ties (e.g. many districts at 2 trucks) bands just merge.
  const cuts = useMemo(
    () => (nums.length ? [0.25, 0.5, 0.75].map((q) => nums[Math.floor(q * (nums.length - 1))]) : []),
    [nums.join(",")], // eslint-disable-line react-hooks/exhaustive-deps
  );

  function style(f) {
    const d = f.properties.district;
    const band = bandOf(values[d], cuts);
    return {
      color: d === selected ? "#0f2744" : "#ffffff",
      weight: d === selected ? 3 : 1.2,
      fillColor: band ? RISK_HEX[band] : NO_DATA_HEX,
      fillOpacity: 0.55,
    };
  }

  function onEach(f, layer) {
    const d = f.properties.district;
    layer.bindTooltip(textEl(`District ${d}: ${values[d] == null ? "no data" : format(values[d])}`), { sticky: true });
    layer.on("click", () => onSelect?.(d));
  }

  return (
    <div>
      <div className={`${MAP_FRAME} h-[380px]`}>
        <MapContainer center={[32.78, -96.8]} zoom={10} scrollWheelZoom={false} className="h-full w-full">
          <TileLayer url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" attribution="&copy; OpenStreetMap contributors" />
          {/* key forces a restyle when values or selection change (GeoJSON styles once). */}
          <GeoJSON key={`${nums.join(",")}-${selected}`} data={geojson} style={style} onEachFeature={onEach} />
          <FitToDistricts geojson={geojson} />
        </MapContainer>
      </div>
      <div className={LEGEND}>
        <span className="font-semibold">{legendTitle}:</span>
        {BANDS.map((b, i) => (
          <span key={b} className={LEGEND_ITEM}>
            <span className={LEGEND_SWATCH} style={{ background: RISK_HEX[b] }} />
            {i === 0 ? `≤ ${format(cuts[0] ?? 0)}` : i === 3 ? `> ${format(cuts[2] ?? 0)}` : `${format(cuts[i - 1])}–${format(cuts[i])}`}
          </span>
        ))}
      </div>
    </div>
  );
}
