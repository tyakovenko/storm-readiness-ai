import { useEffect, useMemo, useRef, useState } from "react";
import * as maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
// MapLibre finds its worker relative to its own file, which Vite moves; hand it a bundled worker instead.
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";
import { feature } from "topojson-client";
import { Card, NO_PREDICTION_COLOR, TIERS, TierBadge, pctRange } from "../components/ui.jsx";

// Screen 2: counties colored by risk tier, shelters as points, click a county for the why.
// County shapes are bundled (us-atlas, keyed by 5-digit FIPS like the data contract).
// The street basemap is OpenFreeMap: free, no key, needs internet; offline we fall back to a plain background.

maplibregl.setWorkerUrl(workerUrl);

const BASEMAP = "https://tiles.openfreemap.org/styles/positron";
const BLANK_STYLE = {
  version: 8,
  sources: {},
  layers: [{ id: "background", type: "background", paint: { "background-color": "#e8edf2" } }],
};

const tierColor = ["match", ["get", "tier"], ...Object.entries(TIERS).flatMap(([k, t]) => [k, t.color]), NO_PREDICTION_COLOR];

function bounds(features) {
  const b = new maplibregl.LngLatBounds();
  const walk = (c) => (typeof c[0] === "number" ? b.extend(c) : c.forEach(walk));
  features.forEach((f) => walk(f.geometry.coordinates));
  return b;
}

function useCountyShapes(stateFips) {
  const [shapes, setShapes] = useState(null);
  useEffect(() => {
    // Loaded on demand so the other screens don't pay for the ~800 KB of county shapes.
    import("us-atlas/counties-10m.json").then(({ default: us }) => {
      const all = feature(us, us.objects.counties).features;
      setShapes(all.filter((f) => stateFips.has(f.id.slice(0, 2))));
    });
  }, [stateFips]);
  return shapes;
}

export default function RiskMap({ data, selected, onSelect }) {
  const { impact, assets, staging } = data;
  const byFips = useMemo(() => Object.fromEntries(impact.counties.map((c) => [c.fips, c])), [impact]);
  const stateFips = useMemo(() => new Set(impact.counties.map((c) => c.fips.slice(0, 2))), [impact]);
  const shapes = useCountyShapes(stateFips);

  const containerRef = useRef(null);
  const mapRef = useRef(null);
  const [basemapFailed, setBasemapFailed] = useState(false);
  const [showShelters, setShowShelters] = useState(true);

  useEffect(() => {
    if (!shapes) return;
    const counties = {
      type: "FeatureCollection",
      features: shapes.map((f) => ({
        ...f,
        properties: { fips: f.id, name: f.properties.name, tier: byFips[f.id]?.risk_tier ?? "none" },
      })),
    };
    const shelters = {
      type: "FeatureCollection",
      features: assets.shelters
        .filter((s) => s.lat != null && s.lon != null)
        .map((s) => ({
          type: "Feature",
          geometry: { type: "Point", coordinates: [s.lon, s.lat] },
          properties: { id: s.id, name: s.name, capacity: s.evacuation_capacity, status: s.status },
        })),
    };

    const map = new maplibregl.Map({ container: containerRef.current, style: BASEMAP, attributionControl: { compact: true } });
    mapRef.current = map;
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");

    let styleLoaded = false;
    let removed = false;
    map.on("error", (e) => {
      // Only a failed basemap download before first load means "offline". Ignore tile hiccups
      // after load, and aborted requests when React unmounts the map (dev StrictMode does this).
      if (styleLoaded || removed || e.error?.name === "AbortError") return;
      console.warn("Basemap failed, falling back to plain background:", e.error);
      styleLoaded = true;
      setBasemapFailed(true);
      map.setStyle(BLANK_STYLE);
    });

    map.on("style.load", () => {
      styleLoaded = true;
      map.addSource("counties", { type: "geojson", data: counties });
      map.addLayer({
        id: "counties-fill", type: "fill", source: "counties",
        paint: { "fill-color": tierColor, "fill-opacity": ["case", ["==", ["get", "tier"], "none"], 0.12, 0.6] },
      });
      map.addLayer({ id: "counties-line", type: "line", source: "counties", paint: { "line-color": "#475569", "line-width": 0.6 } });
      map.addLayer({
        id: "county-selected", type: "line", source: "counties",
        filter: ["==", ["get", "fips"], ""], paint: { "line-color": "#0f172a", "line-width": 3 },
      });
      map.addSource("shelters", { type: "geojson", data: shelters });
      map.addLayer({
        id: "shelters", type: "circle", source: "shelters",
        paint: { "circle-radius": 6, "circle-color": "#1d4ed8", "circle-stroke-color": "#fff", "circle-stroke-width": 2 },
      });

      const impacted = counties.features.filter((f) => byFips[f.properties.fips]);
      map.fitBounds(bounds(impacted.length ? impacted : counties.features), { padding: 40, duration: 0 });
    });

    map.on("click", "counties-fill", (e) => onSelect(e.features[0].properties.fips));
    map.on("click", "shelters", (e) => {
      const p = e.features[0].properties;
      // Text, not HTML: real FEMA shelter names shouldn't be able to inject markup.
      const el = document.createElement("div");
      el.style.whiteSpace = "pre-line";
      el.textContent = `${p.id}\n${p.name}\n${p.capacity} beds · ${p.status}`;
      new maplibregl.Popup({ offset: 10 }).setLngLat(e.lngLat).setDOMContent(el).addTo(map);
    });
    for (const layer of ["counties-fill", "shelters"]) {
      map.on("mouseenter", layer, () => (map.getCanvas().style.cursor = "pointer"));
      map.on("mouseleave", layer, () => (map.getCanvas().style.cursor = ""));
    }
    return () => {
      removed = true;
      map.remove();
    };
  }, [shapes, byFips, assets, onSelect]);

  // Keep the highlight and shelter visibility in sync without rebuilding the map.
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const apply = () => {
      if (!map.getLayer("county-selected")) return;
      map.setFilter("county-selected", ["==", ["get", "fips"], selected ?? ""]);
      map.setLayoutProperty("shelters", "visibility", showShelters ? "visible" : "none");
    };
    apply();
    map.on("style.load", apply);
    return () => map.off("style.load", apply);
  }, [selected, showShelters, shapes]);

  const county = selected ? byFips[selected] : null;
  const countyShelters = assets.shelters.filter((s) => s.county_fips === selected);
  const allocation = staging.allocations.find((x) => x.fips === selected);
  const clickedName = selected && !county ? shapes?.find((f) => f.id === selected)?.properties.name : null;

  return (
    <div className="grid gap-4 lg:grid-cols-[1fr_340px]">
      <div className="relative min-h-[420px] overflow-hidden rounded-xl border border-slate-200 bg-slate-100 lg:min-h-[620px]">
        {/* Inline style, not Tailwind: maplibre-gl.css sets position:relative on the container and would win. */}
        <div ref={containerRef} style={{ position: "absolute", inset: 0 }} role="region" aria-label="Risk map of counties and shelters" />
        {!shapes && <p className="absolute left-4 top-4 rounded bg-white/90 px-3 py-1 text-sm">Loading counties…</p>}
        {basemapFailed && (
          <p className="absolute bottom-3 left-3 rounded bg-white/90 px-3 py-1 text-xs text-slate-600">
            Couldn't load the street basemap (offline?). Showing counties only.
          </p>
        )}
      </div>

      <div className="space-y-4">
        <Card title={county ? county.name : clickedName ? `${clickedName} County` : "Select a county"}>
          {county ? (
            <div className="space-y-3 text-sm text-slate-700">
              <TierBadge tier={county.risk_tier} />
              <p>Peak customers without power: <strong>{pctRange(county.pct_customers_out)}</strong></p>
              <p>Customers served: <strong>{county.customers_served.toLocaleString()}</strong></p>
              <div>
                <h3 className="font-semibold text-slate-900">Why it's at risk</h3>
                <ul className="mt-1 list-disc space-y-1 pl-5">{county.why.map((w) => <li key={w}>{w}</li>)}</ul>
              </div>
              {allocation && (
                <p>Staging plan: <strong>{allocation.truckloads_assigned} of {allocation.truckloads_needed}</strong> truckloads assigned</p>
              )}
              <div>
                <h3 className="font-semibold text-slate-900">Shelters here</h3>
                {countyShelters.length ? (
                  <ul className="mt-1 space-y-1">
                    {countyShelters.map((s) => (
                      <li key={s.id}>{s.id}: {s.name}, {s.evacuation_capacity} beds ({s.status})</li>
                    ))}
                  </ul>
                ) : (
                  <p className="mt-1 text-slate-500">None in the shelter data.</p>
                )}
              </div>
            </div>
          ) : clickedName ? (
            <p className="text-sm text-slate-600">No impact prediction for this county.</p>
          ) : (
            <p className="text-sm text-slate-600">Click a county on the map, or pick one below.</p>
          )}
        </Card>

        <Card title="Counties with a prediction">
          <ul className="space-y-1">
            {impact.counties.map((c) => (
              <li key={c.fips}>
                <button
                  type="button"
                  onClick={() => onSelect(c.fips)}
                  aria-pressed={selected === c.fips}
                  className={`flex w-full items-center justify-between rounded-lg px-2 py-1.5 text-left text-sm hover:bg-slate-100 ${selected === c.fips ? "bg-slate-100 font-semibold" : ""}`}
                >
                  {c.name} <TierBadge tier={c.risk_tier} />
                </button>
              </li>
            ))}
          </ul>
        </Card>

        <Card title="Layers">
          <ul className="space-y-2 text-sm">
            <li className="flex items-center gap-2"><input type="checkbox" checked disabled id="l-risk" /><label htmlFor="l-risk">County risk tiers</label></li>
            <li className="flex items-center gap-2">
              <input type="checkbox" id="l-shelters" checked={showShelters} onChange={(e) => setShowShelters(e.target.checked)} />
              <label htmlFor="l-shelters">Shelters <span className="inline-block size-2.5 rounded-full bg-blue-700 align-middle" aria-hidden="true" /></label>
            </li>
            <li className="text-slate-600">Roads: shown on the street basemap. Road closures: <em>waiting on data</em></li>
            <li className="text-slate-600">Hospitals: <em>waiting on data</em></li>
            <li className="text-slate-600">Other critical infrastructure: <em>waiting on data</em></li>
            <li className="text-slate-600">Population: customers served is shown per county; a population layer is <em>waiting on data</em></li>
          </ul>
          <div className="mt-3 flex flex-wrap gap-2 border-t border-slate-100 pt-3">
            {Object.keys(TIERS).map((t) => <TierBadge key={t} tier={t} />)}
            <span className="inline-flex items-center gap-1.5 text-xs text-slate-600">
              <span className="size-2 rounded-full" style={{ background: NO_PREDICTION_COLOR }} aria-hidden="true" /> No prediction
            </span>
          </div>
        </Card>
      </div>
    </div>
  );
}
