import { useEffect, useMemo, useRef, useState } from "react";
import L from "leaflet";
import { CircleMarker, GeoJSON, MapContainer, Pane, TileLayer, Tooltip, useMap } from "react-leaflet";
import { feature } from "topojson-client";
import "leaflet/dist/leaflet.css";
import RiskBadge from "../RiskBadge.jsx";
import SectionHeading from "../SectionHeading.jsx";
import { LEGEND, LEGEND_ITEM, LEGEND_SWATCH, MAP_FRAME, MAP_SIZE } from "./ForecastMap.jsx";
import { DETAIL_ITEM, DETAIL_LABEL, DETAIL_PANEL, DETAIL_VALUE } from "./ForecastDetailsPanel.jsx";
import { LEVEL_LABEL, RISK_HEX, getRiskLabel, getRiskLevel } from "../../utils/riskTier.js";

// Counties colored by predicted outage risk, shelters as dots; click a county
// (or pick it from the list) to see why it's at risk. County shapes are
// bundled (us-atlas, keyed by the same 5-digit FIPS strings as the data
// contract), so real predictions drop in with no frontend change.

const NO_PREDICTION_HEX = "#9aa3ae";
const SHELTER_HEX = "#0f2744"; // navy: distinct from the risk colors and the blue staging markers
const FALLBACK_CENTER = [29.3, -83.0];
const FALLBACK_ZOOM = 7;
const LEVELS = ["severe", "high", "moderate", "low"];

// Plain text for Leaflet tooltips (strings would be parsed as HTML).
function textEl(text) {
  const el = document.createElement("span");
  el.textContent = text;
  return el;
}

// ~800 KB of shapes, so loaded on demand; only the states we have predictions for are kept.
function useCountyShapes(stateFips) {
  const [shapes, setShapes] = useState(null);
  useEffect(() => {
    let cancelled = false;
    import("us-atlas/counties-10m.json").then(({ default: us }) => {
      if (cancelled) return;
      const all = feature(us, us.objects.counties).features;
      setShapes({ type: "FeatureCollection", features: all.filter((f) => stateFips.has(f.id.slice(0, 2))) });
    });
    return () => {
      cancelled = true;
    };
  }, [stateFips]);
  return shapes;
}

function CountyLayer({ shapes, byFips, selectedFips, onSelect }) {
  const map = useMap();
  const layerRef = useRef(null);
  const impactedBounds = useMemo(() => {
    const impacted = shapes.features.filter((f) => byFips[f.id]);
    return impacted.length ? L.geoJSON({ type: "FeatureCollection", features: impacted }).getBounds() : null;
  }, [shapes, byFips]);

  const style = useMemo(
    () => (f) => {
      const c = byFips[f.id];
      const selected = f.id === selectedFips;
      return {
        color: selected ? "#0f2744" : "#5b6472",
        weight: selected ? 3 : 0.6,
        fillColor: c ? RISK_HEX[getRiskLevel(c.risk_tier)] : NO_PREDICTION_HEX,
        fillOpacity: c ? 0.55 : 0.08,
      };
    },
    [byFips, selectedFips],
  );

  // Zoom to the selected county, or back out to every county with a prediction.
  useEffect(() => {
    let target = null;
    layerRef.current?.eachLayer((l) => {
      if (l.feature.id === selectedFips) target = l;
    });
    if (target) {
      target.bringToFront();
      map.flyToBounds(target.getBounds(), { padding: [60, 60], maxZoom: 9, duration: 0.6 });
    } else if (impactedBounds) {
      map.fitBounds(impactedBounds, { padding: [24, 24] });
    }
  }, [map, selectedFips, impactedBounds]);

  function onEachFeature(f, layer) {
    const c = byFips[f.id];
    const label = c ? `${c.name} · ${getRiskLabel(c.risk_tier)}` : `${f.properties.name} County · no prediction`;
    layer.bindTooltip(textEl(label), { sticky: true, direction: "top" });
    layer.on("click", () => onSelect(f.id));
  }

  return <GeoJSON ref={layerRef} data={shapes} style={style} onEachFeature={onEachFeature} />;
}

function ShelterList({ shelters }) {
  if (!shelters.length) return <dd className="text-[0.85rem] text-muted">None in the shelter data.</dd>;
  return (
    <dd>
      <ul className="flex flex-col gap-1 text-[0.85rem] text-ink">
        {shelters.map((s) => (
          <li key={s.id}>
            <strong className="text-navy">{s.id}</strong> · {s.name}, {s.evacuation_capacity} beds ({s.status})
          </li>
        ))}
      </ul>
    </dd>
  );
}

function CountyDetails({ county, unpredictedName, counties, shelters, onSelect }) {
  if (county) {
    const q = county.pct_customers_out;
    return (
      <dl className={`${DETAIL_PANEL} overflow-y-auto`} aria-label="Selected county details">
        <div className={DETAIL_ITEM}>
          <div className="flex items-start justify-between gap-2">
            <dt className={DETAIL_LABEL}>Selected County</dt>
            <button
              type="button"
              className="cursor-pointer whitespace-nowrap bg-transparent p-0 text-[0.78rem] font-semibold text-accent hover:text-accent-dark hover:underline"
              onClick={() => onSelect(null)}
            >
              &larr; All counties
            </button>
          </div>
          <dd className={DETAIL_VALUE}>
            {county.name}, {county.state}
          </dd>
          <dd className="mt-1">
            <RiskBadge level={getRiskLevel(county.risk_tier)} />
          </dd>
        </div>
        <div className={DETAIL_ITEM}>
          <dt className={DETAIL_LABEL}>Predicted Customer Outage</dt>
          <dd className={DETAIL_VALUE}>{q.median}%</dd>
          <dd className="text-[0.78rem] text-muted">Range {q.low}–{q.high}%</dd>
        </div>
        <div className={DETAIL_ITEM}>
          <dt className={DETAIL_LABEL}>Customers Served</dt>
          <dd className={DETAIL_VALUE}>{county.customers_served.toLocaleString("en-US")}</dd>
        </div>
        <div className={DETAIL_ITEM}>
          <dt className={DETAIL_LABEL}>Why It&rsquo;s at Risk</dt>
          <dd>
            <ul className="flex list-disc flex-col gap-0.5 pl-[18px] text-[0.85rem] text-ink">
              {county.why.map((w) => (
                <li key={w}>{w}</li>
              ))}
            </ul>
          </dd>
        </div>
        <div className={DETAIL_ITEM}>
          <dt className={DETAIL_LABEL}>Shelters Here</dt>
          <ShelterList shelters={shelters} />
        </div>
      </dl>
    );
  }

  return (
    <div className={`${DETAIL_PANEL} overflow-y-auto`}>
      <p className="text-[0.85rem] text-muted">
        {unpredictedName
          ? `No impact prediction for ${unpredictedName} County.`
          : "Click a county on the map, or pick one below."}
      </p>
      <div>
        <h4 className={DETAIL_LABEL}>Counties with a prediction</h4>
        <ul className="mt-2 flex flex-col gap-1">
          {counties.map((c) => (
            <li key={c.fips}>
              <button
                type="button"
                onClick={() => onSelect(c.fips)}
                className="flex w-full cursor-pointer items-center justify-between gap-2 rounded px-2 py-1.5 text-left text-[0.88rem] font-semibold text-navy hover:bg-canvas"
              >
                {c.name}
                <RiskBadge level={getRiskLevel(c.risk_tier)} />
              </button>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

export default function RiskMapSection({ sectionRef, impact, shelters, selectedFips, onSelect }) {
  const byFips = useMemo(() => Object.fromEntries(impact.counties.map((c) => [c.fips, c])), [impact]);
  const stateFips = useMemo(() => new Set(impact.counties.map((c) => c.fips.slice(0, 2))), [impact]);
  const shapes = useCountyShapes(stateFips);
  const [showShelters, setShowShelters] = useState(true);

  const county = selectedFips ? byFips[selectedFips] : null;
  const unpredictedName =
    selectedFips && !county ? shapes?.features.find((f) => f.id === selectedFips)?.properties.name : null;
  const counties = useMemo(
    () => [...impact.counties].sort((a, b) => b.pct_customers_out.median - a.pct_customers_out.median),
    [impact],
  );
  const mappedShelters = shelters.filter((s) => s.lat != null && s.lon != null);

  return (
    // scroll-mt clears the fixed header + sub-nav when "View details" scrolls here.
    <section ref={sectionRef} className="mt-6 scroll-mt-[118px]" aria-labelledby="risk-map-heading">
      <SectionHeading
        id="risk-map-heading"
        title="Risk Map"
        subtitle="Predicted outage risk by county. Click a county to see why it's at risk."
      />

      <div className="mt-3.5 flex items-stretch gap-4 max-[900px]:flex-col">
        <div className="min-w-0 flex-[7_1_0] max-[900px]:w-full max-[900px]:flex-auto">
          <div className={MAP_FRAME}>
            <MapContainer
              center={FALLBACK_CENTER}
              zoom={FALLBACK_ZOOM}
              scrollWheelZoom={false}
              className={MAP_SIZE}
              aria-label="County risk map"
            >
              <TileLayer
                url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
                attribution="&copy; OpenStreetMap contributors"
              />
              {shapes && (
                <CountyLayer shapes={shapes} byFips={byFips} selectedFips={selectedFips} onSelect={onSelect} />
              )}
              {/* Own pane above the counties, so a selected county never covers its shelters. */}
              <Pane name="shelters" style={{ zIndex: 450 }}>
                {showShelters &&
                  mappedShelters.map((s) => (
                    <CircleMarker
                      key={s.id}
                      center={[s.lat, s.lon]}
                      radius={6}
                      pathOptions={{ color: "#ffffff", weight: 2, fillColor: SHELTER_HEX, fillOpacity: 1 }}
                    >
                      <Tooltip direction="top" offset={[0, -6]}>
                        <div className="flex flex-col gap-0.5 text-[0.78rem] text-ink">
                          <strong className="text-navy">
                            {s.id} · {s.name}
                          </strong>
                          <span>
                            {s.evacuation_capacity} evacuation beds · {s.status}
                          </span>
                        </div>
                      </Tooltip>
                    </CircleMarker>
                  ))}
              </Pane>
            </MapContainer>

            {!shapes && (
              <p className="absolute left-3 top-3 z-500 rounded bg-white/92 px-3 py-1 text-[0.78rem] text-muted">
                Loading counties…
              </p>
            )}
            <div className={LEGEND} aria-hidden="true">
              {LEVELS.map((level) => (
                <span key={level} className={LEGEND_ITEM}>
                  <span className={LEGEND_SWATCH} style={{ background: RISK_HEX[level], borderColor: RISK_HEX[level] }} />
                  {LEVEL_LABEL[level]}
                </span>
              ))}
              <span className={LEGEND_ITEM}>
                <span
                  className={LEGEND_SWATCH}
                  style={{ background: NO_PREDICTION_HEX, borderColor: NO_PREDICTION_HEX }}
                />
                No prediction
              </span>
              {showShelters && (
                <span className={LEGEND_ITEM}>
                  <span className={`${LEGEND_SWATCH} border-white bg-navy`} />
                  Shelter
                </span>
              )}
            </div>
          </div>
        </div>

        <div className="min-w-[220px] flex-[3_1_0] max-[900px]:w-full max-[900px]:flex-auto">
          <CountyDetails
            county={county}
            unpredictedName={unpredictedName}
            counties={counties}
            shelters={shelters.filter((s) => s.county_fips === selectedFips)}
            onSelect={onSelect}
          />
        </div>
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-x-6 gap-y-2 rounded-md border border-line bg-surface px-4 py-2.5 text-[0.82rem]">
        <span className={DETAIL_LABEL}>Layers</span>
        <label className="inline-flex cursor-pointer items-center gap-1.5 font-semibold text-ink">
          <input type="checkbox" checked={showShelters} onChange={(e) => setShowShelters(e.target.checked)} />
          Shelters
        </label>
        <span className="text-muted">Roads: shown on the basemap</span>
        <span className="text-muted">
          Hospitals, critical infrastructure, population: <em>waiting on data</em>
        </span>
      </div>

      <p className="mt-2.5 text-xs italic text-muted">
        County risk and shelters come from the backend (stub data until the real impact model and FEMA shelter
        data are plugged in).
      </p>
    </section>
  );
}
