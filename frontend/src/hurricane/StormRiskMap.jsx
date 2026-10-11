import { useEffect, useMemo, useRef, useState } from "react";
import L from "leaflet";
import { CircleMarker, GeoJSON, MapContainer, Polyline, TileLayer, Tooltip, useMap } from "react-leaflet";
import { feature } from "topojson-client";
import "leaflet/dist/leaflet.css";

import { PAGE, PageStatus, PageTitle } from "../components/Page.jsx";
import SectionHeading from "../components/SectionHeading.jsx";
import RiskBadge from "../components/RiskBadge.jsx";
import { LEGEND, LEGEND_ITEM, LEGEND_SWATCH, MAP_FRAME, MAP_SIZE } from "../components/storm/ForecastMap.jsx";
import { CARD, LABEL, NOTE, fmt } from "../dallas/format.js";
import { RISK_HEX, getRiskLabel, getRiskLevel } from "../utils/riskTier.js";
import { STATUS, addHoursISO, fmtUTC } from "./shared.jsx";

// Storm-wide Risk Map (Phase 1): one existing hurricane pack's own replayed storm, extended to
// its real neighboring counties (backend/hurricane/storm_regions.py), at a real forecast
// horizon -- GET /api/storms/{slug}/overview. Every county shown here either has the agent's own
// trained-model prediction (home county) or the SAME model's prediction via the multi-county
// pipeline (neighbors). Never a multi-county "choropleth" with invented numbers -- a county this
// storm's neighbor list doesn't name is simply not drawn.
//
// Risk-only redesign: this screen shows county risk + the real NHC forecast track only --
// shelters are a Resource Planner concern (HurricaneShelters.jsx, untouched) and are deliberately
// not drawn here. `track` is the home county's own real forecast (alert.forecast from the
// existing GET /api/agents/{slug}/overview, fetched by StormShell) -- the storm-wide endpoint has
// no track field of its own, so this is reused rather than invented; if it's ever missing, no
// track (and no cone -- real cone geometry doesn't exist in this app) is drawn.
//
// Layout (visual redesign only -- same data, same API, same onSelectCounty/onSelectHorizon/
// onOpenCounty contract as before): compact header with the horizon picker top-right, a 60/40
// map + ranked county summary row, then collapsible County details / Sources & trust / replay
// explainer sections below, matching the Storm Overview page's information density.

const NO_PREDICTION_HEX = "#9aa3ae";
const FALLBACK_CENTER = [28.5, -84.0];
const FALLBACK_ZOOM = 6;

const ASK_PROMPTS = [
  "Explain this risk map",
  "Why is my county at risk?",
  "Compare with similar storms",
];

// Native <details>/<summary> -- same pattern as Storm Overview's reference sections.
function Collapsible({ title, subtitle, children }) {
  return (
    <details className="group rounded-md border border-line bg-surface">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-3 py-2.5 marker:content-none">
        <div>
          <span className="text-[0.88rem] font-bold text-navy">{title}</span>
          {subtitle && <span className="ml-2 text-[0.76rem] text-muted">{subtitle}</span>}
        </div>
        <span aria-hidden="true" className="text-[0.75rem] text-muted transition-transform group-open:rotate-180">▾</span>
      </summary>
      <div className="border-t border-line px-3 py-2.5">{children}</div>
    </details>
  );
}

function textEl(text) {
  const el = document.createElement("span");
  el.textContent = text;
  return el;
}

// ~800 KB of county shapes, loaded on demand; only the states this storm's counties are in.
// Surfaces a load failure instead of leaving `shapes` null forever -- a failed chunk fetch used to
// fail silently (no .catch()), leaving the map showing the track with no county polygons and no
// indication anything was wrong.
function useCountyShapes(stateFips) {
  const [shapes, setShapes] = useState(null);
  const [shapesError, setShapesError] = useState(null);
  useEffect(() => {
    let cancelled = false;
    setShapes(null);
    setShapesError(null);
    import("us-atlas/counties-10m.json")
      .then(({ default: us }) => {
        if (cancelled) return;
        const all = feature(us, us.objects.counties).features;
        setShapes({ type: "FeatureCollection", features: all.filter((f) => stateFips.has(f.id.slice(0, 2))) });
      })
      .catch((e) => {
        if (!cancelled) setShapesError(e?.message || "Failed to load county boundaries");
      });
    return () => {
      cancelled = true;
    };
  }, [stateFips]);
  return { shapes, shapesError };
}

function CountyLayer({ shapes, byFips, selectedFips, onSelect }) {
  const map = useMap();
  const layerRef = useRef(null);
  const shownBounds = useMemo(() => {
    const shown = shapes.features.filter((f) => byFips[f.id]);
    return shown.length ? L.geoJSON({ type: "FeatureCollection", features: shown }).getBounds() : null;
  }, [shapes, byFips]);

  const style = useMemo(
    () => (f) => {
      const c = byFips[f.id];
      const selected = f.id === selectedFips;
      return {
        color: selected ? "#0f2744" : "#5b6472",
        weight: selected ? 3 : c ? 1 : 0.4,
        fillColor: c ? RISK_HEX[getRiskLevel(c.risk_tier)] : NO_PREDICTION_HEX,
        fillOpacity: c ? 0.55 : 0,
      };
    },
    [byFips, selectedFips],
  );

  useEffect(() => {
    let target = null;
    layerRef.current?.eachLayer((l) => {
      if (l.feature.id === selectedFips) target = l;
    });
    if (target) {
      target.bringToFront();
      map.flyToBounds(target.getBounds(), { padding: [60, 60], maxZoom: 9, duration: 0.6 });
    } else if (shownBounds) {
      map.fitBounds(shownBounds, { padding: [24, 24] });
    }
  }, [map, selectedFips, shownBounds]);

  function onEachFeature(f, layer) {
    const c = byFips[f.id];
    if (!c) return; // only this storm's own counties are interactive/labeled
    layer.bindTooltip(textEl(`${c.name}, ${c.state} · ${getRiskLabel(c.risk_tier)}`), { sticky: true, direction: "top" });
    layer.on("click", () => onSelect(c.fips));
  }

  const shapesKey = `${shapes.features.length}:${shapes.features[0]?.id ?? ""}`;
  return <GeoJSON key={shapesKey} ref={layerRef} data={shapes} style={style} onEachFeature={onEachFeature} />;
}

// Compact horizontal-bar row for the county summary list -- same risk colors/labels the map
// itself uses (RISK_HEX / getRiskLevel on risk_tier), so the two never disagree.
function CountyRow({ county, selected, homeFips, maxMedian, onSelect }) {
  const level = getRiskLevel(county.risk_tier);
  const widthPct = Math.max(4, (county.pct_customers_out.median / maxMedian) * 100);
  return (
    <li>
      <button type="button" onClick={() => onSelect(county.fips)}
        className={`flex w-full cursor-pointer items-center gap-2.5 rounded px-2 py-1.5 text-left hover:bg-canvas ${selected ? "bg-[#e8f0f8]" : ""}`}>
        <span className="w-28 shrink-0 truncate text-[0.82rem] font-semibold text-navy">
          {county.name}
          {selected && <span className="ml-1 text-[0.7rem] font-normal text-accent">(selected)</span>}
          {county.fips === homeFips && !selected && <span className="ml-1 text-[0.68rem] font-normal text-muted">(home)</span>}
        </span>
        <span className="relative h-2.5 flex-1 rounded-full bg-[#eef1f5]">
          <span className="absolute inset-y-0 left-0 rounded-full" style={{ width: `${widthPct}%`, backgroundColor: RISK_HEX[level] }} />
        </span>
        <span className="w-11 shrink-0 text-right text-[0.8rem] font-bold text-navy">{fmt(county.pct_customers_out.median)}%</span>
        {/* Fixed width even when empty: the bar track is flex-1, so a label in only some rows
            would shorten those tracks and make the bars incomparable across rows. */}
        <span className="w-[4.75rem] shrink-0 whitespace-nowrap text-[0.65rem] font-normal text-muted">
          {county.has_local_pack ? "" : "no plan data"}
        </span>
        <RiskBadge level={level} />
      </button>
    </li>
  );
}

function CountySummary({ counties, homeFips, selectedFips, onSelect }) {
  const sorted = useMemo(() => [...counties].sort((a, b) => b.pct_customers_out.median - a.pct_customers_out.median), [counties]);
  const maxMedian = Math.max(...sorted.map((c) => c.pct_customers_out.median), 1);
  return (
    <div className={CARD}>
      <div className={LABEL}>Counties in this storm&rsquo;s view</div>
      <ul className="mt-2 flex flex-col gap-1">
        {sorted.map((c) => (
          <CountyRow key={c.fips} county={c} selected={c.fips === selectedFips} homeFips={homeFips}
            maxMedian={maxMedian} onSelect={onSelect} />
        ))}
      </ul>
    </div>
  );
}

// Reference detail for the selected county (unchanged content, now a collapsible section instead
// of replacing the summary list) -- only fields already on this county's overview entry.
function CountyDetails({ county, onOpenCounty }) {
  if (!county) {
    return <p className={NOTE}>Select a county on the map or in the list above to see its details.</p>;
  }
  const level = getRiskLevel(county.risk_tier);
  const q = county.pct_customers_out;
  return (
    <div>
      <div className="flex items-start justify-between gap-2">
        <div className="text-[1.05rem] font-bold text-navy">{county.name}, {county.state}</div>
        <RiskBadge level={level} />
      </div>
      <div className="mt-2 text-[0.95rem] font-semibold text-navy">
        {fmt(q.low)}&ndash;{fmt(q.high)}% customers out <span className="text-muted font-normal">(median {fmt(q.median)}%)</span>
      </div>
      <div className={NOTE}>of {fmt(county.customers_served)} customers served</div>
      <ul className="mt-2 list-disc pl-4 text-[0.82rem]">{county.why.slice(0, 3).map((w) => <li key={w}>{w}</li>)}</ul>
      {county.has_local_pack ? (
        <button type="button" onClick={() => onOpenCounty(county.fips)}
          className="mt-3 cursor-pointer rounded border border-line px-3 py-1.5 text-[0.8rem] font-semibold text-accent hover:border-accent">
          Open Storm Overview &amp; Resource Planner for {county.name} &rarr;
        </button>
      ) : (
        <p className="mt-3 rounded bg-warn-bg px-2.5 py-2 text-[0.8rem] text-warn-text">
          {county.name} has this real model prediction, but no published shelter or
          resource-planning data yet. Storm Overview and Resource Planner aren&rsquo;t available for it.
        </p>
      )}
    </div>
  );
}

// Top-right horizon picker -- same options/handler as before (overview.available_horizons_h /
// onSelectHorizon), styled as its own compact card to match Storm Overview's HorizonCard.
function HorizonCard({ overview, onSelectHorizon }) {
  const validTime = overview.advisory_init_utc ? fmtUTC(addHoursISO(overview.advisory_init_utc, overview.horizon_h)) : null;
  return (
    <div className="shrink-0 rounded-md border border-line bg-surface px-3 py-2.5">
      <div className={LABEL}>Forecast valid time <span className="font-normal normal-case text-muted">(after advisory)</span></div>
      <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
        {overview.available_horizons_h.map((h) => (
          <button key={h} type="button" onClick={() => onSelectHorizon(h)}
            className={`cursor-pointer rounded-full px-3 py-1 text-[0.8rem] font-semibold ${
              h === overview.horizon_h ? "bg-accent text-white" : "border border-line text-muted hover:text-ink"
            }`}>
            +{h}h
          </button>
        ))}
        {validTime && <span className="ml-1 border-l border-line pl-2.5 text-[0.8rem] font-semibold text-navy">{validTime}</span>}
      </div>
    </div>
  );
}

export default function StormRiskMap({ overview, error, selectedFips, track, onSelectCounty, onSelectHorizon, onOpenCounty, onAsk }) {
  // Hooks must run on every render regardless of loading/error state, so they're declared
  // before any early return, guarded against a null overview.
  const byFips = useMemo(() => Object.fromEntries((overview?.counties ?? []).map((c) => [c.fips, c])), [overview]);
  const stateFips = useMemo(() => new Set((overview?.counties ?? []).map((c) => c.fips.slice(0, 2))), [overview]);
  const { shapes, shapesError } = useCountyShapes(stateFips);

  if (!overview && !error) return <PageStatus title="Risk Map" />;
  if (error || !overview) return <PageStatus title="Risk Map" error={error || "No data"} />;

  const status = STATUS[overview.kind] ?? STATUS.replay;
  // selectedFips may legitimately name a county this storm's view has no entry for (e.g. a
  // stale/garbage URL param) -- never silently fall back to the home county for that either.
  const selected = selectedFips ? byFips[selectedFips] : null;
  const unknownSelection = selectedFips && !selected;
  const hasTrack = Boolean(track?.length);

  return (
    <section className={PAGE}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <PageTitle>Risk Map &mdash; {overview.storm_name}</PageTitle>
          <div className="mt-1 flex flex-wrap items-center gap-2.5">
            <span className={`rounded px-2 py-[3px] text-[0.72rem] font-bold uppercase tracking-[0.3px] ${status.className}`}>
              {status.label}
            </span>
            <span className="text-[0.85rem] text-muted">
              Advisory issued {fmtUTC(overview.advisory_init_utc)} &bull; {fmt(overview.counties.length)} counties in view
            </span>
          </div>
        </div>
        <HorizonCard overview={overview} onSelectHorizon={onSelectHorizon} />
      </div>

      <p className="mt-3 text-[0.85rem] text-muted">
        Every county&rsquo;s prediction is the same trained model the home county&rsquo;s agent uses, run on this
        storm&rsquo;s own real forecast. Click a county for detail.
      </p>

      <div className="mt-4 grid grid-cols-[3fr_2fr] gap-4 max-[900px]:grid-cols-1">
        <section>
          <SectionHeading title="County risk map" subtitle="Predicted outage risk at this horizon &bull; click a county to see details" />
          <div className={`${MAP_FRAME} mt-2.5`}>
            <MapContainer center={FALLBACK_CENTER} zoom={FALLBACK_ZOOM} scrollWheelZoom={false} className={`${MAP_SIZE} h-[460px]`}
              aria-label="Storm-wide county risk map">
              <TileLayer url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" attribution="&copy; OpenStreetMap contributors" />
              {shapes && <CountyLayer shapes={shapes} byFips={byFips} selectedFips={selectedFips} onSelect={onSelectCounty} />}
              {hasTrack && (
                <>
                  <Polyline positions={track.map((p) => [p.lat, p.lon])}
                    pathOptions={{ color: RISK_HEX.severe, weight: 3, dashArray: "6 6" }} />
                  {track.map((p) => (
                    <CircleMarker key={p.tau_h} center={[p.lat, p.lon]} radius={4}
                      pathOptions={{ color: RISK_HEX.severe, fillOpacity: 1 }}>
                      <Tooltip>{`+${p.tau_h} h: ${p.vmax_kt} kt`}</Tooltip>
                    </CircleMarker>
                  ))}
                </>
              )}
            </MapContainer>
            {shapesError ? (
              <p className="absolute left-3 top-3 z-500 rounded bg-bad-bg px-3 py-1.5 text-[0.78rem] font-semibold text-bad-text" role="alert">
                County boundaries failed to load ({shapesError}) &mdash; risk map unavailable. The forecast track below is still real.
              </p>
            ) : !shapes ? (
              <p className="absolute left-3 top-3 z-500 rounded bg-white/92 px-3 py-1 text-[0.78rem] text-muted">Loading counties&hellip;</p>
            ) : null}
            <div className={LEGEND} aria-hidden="true">
              <span className={LEGEND_ITEM}><span className={LEGEND_SWATCH} style={{ background: RISK_HEX.severe, borderColor: RISK_HEX.severe }} />Severe</span>
              <span className={LEGEND_ITEM}><span className={LEGEND_SWATCH} style={{ background: RISK_HEX.high, borderColor: RISK_HEX.high }} />High</span>
              <span className={LEGEND_ITEM}><span className={LEGEND_SWATCH} style={{ background: RISK_HEX.moderate, borderColor: RISK_HEX.moderate }} />Moderate</span>
              <span className={LEGEND_ITEM}><span className={LEGEND_SWATCH} style={{ background: RISK_HEX.low, borderColor: RISK_HEX.low }} />Low</span>
              {hasTrack && <span className={LEGEND_ITEM}><span className={LEGEND_SWATCH} style={{ background: RISK_HEX.severe }} />Forecast track</span>}
            </div>
          </div>
        </section>

        <section>
          <SectionHeading title="County risk summary" subtitle="Sorted by predicted outage, highest first" />
          <div className="mt-2.5">
            {unknownSelection && (
              <p className={`${NOTE} mb-2`}>{selectedFips} isn&rsquo;t a county in this storm&rsquo;s view.</p>
            )}
            <CountySummary counties={overview.counties} homeFips={overview.home_county_fips}
              selectedFips={selectedFips} onSelect={onSelectCounty} />
          </div>
        </section>
      </div>

      <section className="mt-4">
        <SectionHeading title="Quick actions" subtitle="Get insights about this map or the impacted counties" />
        <div className="mt-2.5 flex flex-wrap gap-1.5">
          {ASK_PROMPTS.map((q) => (
            <button key={q} type="button" onClick={() => onAsk?.(q)}
              className="cursor-pointer rounded-full border border-line bg-surface px-3 py-1.5 text-[0.8rem] text-accent hover:border-accent">
              {q}
            </button>
          ))}
        </div>
      </section>

      <div className="mt-4 flex flex-col gap-2.5">
        <Collapsible title="County details" subtitle="Predicted outage, key drivers and model inputs">
          <CountyDetails county={selected} onOpenCounty={onOpenCounty} />
        </Collapsible>

        <Collapsible title="Sources & trust" subtitle="Where this page's numbers come from and training data information">
          <ul className="list-disc pl-5 text-[0.82rem] text-muted">
            <li>Outage model: {overview.source} (model {overview.model_version})</li>
            {hasTrack && <li>Forecast track: home county&rsquo;s own advisory data</li>}
          </ul>
          {overview.caveat && <p className={`${NOTE} mt-2.5`}>{overview.caveat}</p>}
        </Collapsible>
      </div>

      <div className="mt-4 rounded-md border border-line bg-surface px-4 py-3 text-[0.82rem] text-muted">
        <strong className="text-navy">About this replay.</strong>{" "}
        This uses a real NHC forecast for {overview.storm_name} (issued {fmtUTC(overview.advisory_init_utc)}),
        replayed for planning practice &mdash; no live storm.
      </div>
    </section>
  );
}
