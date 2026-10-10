import L from "leaflet";
import { MapContainer, TileLayer, CircleMarker, LayerGroup, LayersControl, Marker, Polyline, Tooltip, useMap } from "react-leaflet";
import { useEffect, useMemo } from "react";
import "leaflet/dist/leaflet.css";
import { categoryFor, escapeHtml, positionsFor } from "./liveStorms.js";
import { getRiskLabel, getRiskLevel, RISK_HEX } from "../../utils/riskTier.js";

const STAGING_COLOR = "#38bdf8";
const SHELTER_COLOR = "#a7f3d0";
const fmtN = (n) => Math.round(Number(n) || 0).toLocaleString("en-US");

// Esri basemaps: keyless, and dark/satellite suit the console.
const ESRI = "https://server.arcgisonline.com/ArcGIS/rest/services";
const ESRI_ATTRIBUTION = "Tiles &copy; Esri, HERE, Garmin, &copy; OpenStreetMap contributors";

const FALLBACK_CENTER = [24, -100];
const FALLBACK_ZOOM = 4;

const prefersReducedMotion = () =>
  typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

// Counter-clockwise spinning cyclone glyph (Northern Hemisphere rotation) with a pulse ring,
// colored and sized by Saffir-Simpson category. Name label sits beside it.
function stormIcon(storm, selected) {
  const cat = categoryFor(storm.intensity_kt);
  const size = 22 + Math.min(cat.level, 5) * 3 + (selected ? 6 : 0);
  return L.divIcon({
    className: "",
    html: `<div class="live-storm-icon${selected ? " is-selected" : ""}" style="--c:${cat.color};--s:${size}px">
      <span class="live-storm-icon__pulse"></span>
      <svg class="live-storm-icon__spin" viewBox="0 0 24 24" aria-hidden="true">
        <circle cx="12" cy="12" r="3.2" fill="${cat.level >= 1 ? cat.color : "none"}" stroke="${cat.color}" stroke-width="2"/>
        <path d="M12 8.8 Q12 3.5 18.5 2.5 M12 15.2 Q12 20.5 5.5 21.5" fill="none" stroke="${cat.color}" stroke-width="2.4" stroke-linecap="round"/>
      </svg>
      <span class="live-storm-icon__label">${escapeHtml(storm.name)}</span>
    </div>`,
    iconSize: [size, size],
    iconAnchor: [size / 2, size / 2],
  });
}

function stagingIcon(name) {
  return L.divIcon({
    className: "",
    html: `<div class="live-staging-icon"><span class="live-staging-icon__box"></span><span class="live-staging-icon__label">${escapeHtml(name)}</span></div>`,
    iconSize: [18, 18],
    iconAnchor: [9, 9],
  });
}

// Fit to everything once data arrives; afterwards, fly to the focused storm (or back to all).
function FocusController({ allBounds, focusBounds }) {
  const map = useMap();
  useEffect(() => {
    const target = focusBounds ?? allBounds;
    if (!target || target.length === 0) return;
    const bounds = L.latLngBounds(target);
    const opts = { paddingTopLeft: [40, 40], paddingBottomRight: [60, 70], maxZoom: 7 };  // clear of the legend
    if (prefersReducedMotion()) map.fitBounds(bounds, opts);
    else map.flyToBounds(bounds, { ...opts, duration: 1.1 });
  }, [map, allBounds, focusBounds]);
  return null;
}

// A dot that repeatedly travels the forecast track, so "where it's headed" reads at a glance.
function TrackRunner({ positions, color }) {
  const map = useMap();
  useEffect(() => {
    if (positions.length < 2 || prefersReducedMotion()) return;
    const lengths = [0];
    for (let i = 1; i < positions.length; i++) {
      const [a, b] = [positions[i - 1], positions[i]];
      lengths.push(lengths[i - 1] + Math.hypot(b[0] - a[0], b[1] - a[1]));
    }
    const total = lengths[lengths.length - 1];
    if (total === 0) return;
    const at = (f) => {
      const d = f * total;
      let i = 1;
      while (i < lengths.length - 1 && lengths[i] < d) i++;
      const t = (d - lengths[i - 1]) / (lengths[i] - lengths[i - 1] || 1);
      const [a, b] = [positions[i - 1], positions[i]];
      return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t];
    };
    const dot = L.circleMarker(positions[0], {
      radius: 5, weight: 2, color: "#ffffff", fillColor: color, fillOpacity: 1, interactive: false,
    }).addTo(map);
    const DURATION = 5000;
    const start = performance.now();
    let raf;
    const tick = (now) => {
      const f = ((now - start) % DURATION) / DURATION;
      dot.setLatLng(at(f));
      dot.setStyle({ opacity: 1 - f * 0.7, fillOpacity: 1 - f * 0.7 });
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => { cancelAnimationFrame(raf); dot.remove(); };
  }, [map, positions, color]);
  return null;
}

const fmtTime = (ms) =>
  new Date(ms).toLocaleString("en-US", { weekday: "short", hour: "numeric", timeZone: "UTC", timeZoneName: "short" });

function StormLayer({ storm, track, selected, onSelect }) {
  const pts = useMemo(() => positionsFor(storm, track), [storm, track]);
  const positions = useMemo(() => pts.map((p) => [p.lat, p.lon]), [pts]);
  const cat = categoryFor(storm.intensity_kt);
  const forecast = pts.slice(1);
  const dim = selected === false;

  return (
    <>
      {/* Track colored segment-by-segment by forecast intensity */}
      {forecast.map((p, i) => (
        <Polyline
          key={`seg-${i}`}
          positions={[[pts[i].lat, pts[i].lon], [p.lat, p.lon]]}
          pathOptions={{
            color: categoryFor(pts[i].vmax_kt).color,
            weight: 4,
            opacity: dim ? 0.25 : 0.75,
            dashArray: p.extrapolated ? "2 8" : null,
          }}
        />
      ))}
      {positions.length > 1 && (
        <Polyline
          positions={positions}
          pathOptions={{ color: "#ffffff", weight: 2, opacity: dim ? 0.2 : 0.7, dashArray: "6 18", className: "live-track-flow" }}
          interactive={false}
        />
      )}
      {!dim && <TrackRunner positions={positions} color={cat.color} />}

      {forecast.filter((p) => !p.extrapolated).map((p) => {
        const pc = categoryFor(p.vmax_kt);
        return (
          <CircleMarker
            key={`fp-${p.tau_h}`}
            center={[p.lat, p.lon]}
            radius={4.5}
            pathOptions={{ color: pc.color, weight: 2, fillColor: "#061527", fillOpacity: 1, opacity: dim ? 0.35 : 1 }}
          >
            <Tooltip direction="top" offset={[0, -5]}>
              <div className="text-[0.76rem]">
                <strong>{storm.name} · {fmtTime(p.ms)}</strong>
                <div>{p.vmax_kt} kt ({pc.short}) · {p.lat.toFixed(1)}°, {p.lon.toFixed(1)}°</div>
              </div>
            </Tooltip>
          </CircleMarker>
        );
      })}

      <Marker
        position={[storm.lat, storm.lon]}
        icon={stormIcon(storm, selected === true)}
        zIndexOffset={1000}
        eventHandlers={{ click: () => onSelect(storm.storm_id) }}
      >
        <Tooltip direction="top" offset={[0, -14]}>
          <div className="text-[0.76rem]">
            <strong>{cat.label} {storm.name}</strong>
            <div>{storm.intensity_kt} kt · {storm.pressure_mb || "—"} mb</div>
            {!track && <div className="text-amber-700">Official track unavailable; dashed line is current motion only.</div>}
          </div>
        </Tooltip>
      </Marker>
    </>
  );
}

// One storm's plan: its own staging site, truck routes to its at-risk counties (width = trucks),
// county circles colored by risk tier, and -- when the storm is focused -- those counties' shelters.
function PlanLayer({ storm, risk, dim, showShelters }) {
  const st = risk?.staging;
  const counties = risk?.counties ?? [];
  const op = dim ? 0.2 : 1;
  return (
    <>
      {st && counties.map((c) => (
        <Polyline
          key={`route-${c.fips}-${dim}`}
          positions={[[st.lat, st.lon], [c.lat, c.lon]]}
          pathOptions={{
            color: STAGING_COLOR, weight: 1.2 + Math.min(c.trucks_needed.median, 40) / 8, opacity: 0.75 * op,
            dashArray: "4 8", className: dim ? undefined : "live-route-flow",
          }}
        >
          <Tooltip sticky>
            <span className="text-[0.76rem]">{c.trucks_needed.median} trucks (est.) from {st.county} → {c.name}, {c.state}</span>
          </Tooltip>
        </Polyline>
      ))}
      {counties.map((c) => {
        const color = RISK_HEX[getRiskLevel(c.risk_tier)];
        return (
          <CircleMarker
            key={`county-${c.fips}`}
            center={[c.lat, c.lon]}
            radius={Math.min(6 + Math.sqrt(c.customers_out.median) / 20, 18)}
            pathOptions={{ color, weight: 2, fillColor: color, fillOpacity: 0.35 * op, opacity: op }}
          >
            <Tooltip direction="top" offset={[0, -6]}>
              <div className="text-[0.76rem]">
                <strong>{c.name}, {c.state}</strong> · {getRiskLabel(c.risk_tier)}
                <div>~{fmtN(c.customers_out.median)} customers out ({fmtN(c.customers_out.low)}–{fmtN(c.customers_out.high)})</div>
                <div>{c.distance_to_track_nm} nm from {storm.name}&apos;s forecast track</div>
              </div>
            </Tooltip>
          </CircleMarker>
        );
      })}
      {showShelters && counties.flatMap((c) => (c.shelters?.top ?? []).filter((x) => x.lat != null).map((x, i) => (
        <CircleMarker
          key={`shelter-${c.fips}-${i}`}
          center={[x.lat, x.lon]}
          radius={3.5}
          pathOptions={{ color: SHELTER_COLOR, weight: 1.5, fillColor: SHELTER_COLOR, fillOpacity: 0.9 }}
        >
          <Tooltip direction="top" offset={[0, -4]}>
            <div className="text-[0.76rem]">
              <strong>{x.name}</strong>
              <div>{x.city} · {fmtN(x.evacuation_capacity)} beds{x.generator ? " · generator" : ""}{x.in_surge_zone ? " · in surge zone" : ""}</div>
            </div>
          </Tooltip>
        </CircleMarker>
      )))}
      {st && (
        <Marker position={[st.lat, st.lon]} icon={stagingIcon(`${st.county}, ${st.state} · ${storm.name}`)} zIndexOffset={900} opacity={dim ? 0.4 : 1}>
          <Tooltip direction="top" offset={[0, -10]}>
            <div className="max-w-[240px] text-[0.76rem]">
              <strong>{st.name}</strong>
              <div>For {storm.name}: ~{fmtN(risk.trucks_needed_total?.median)} trucks (est.) to {counties.length} counties</div>
              <div>{st.clearance_from_track_nm} nm clear of the forecast track</div>
            </div>
          </Tooltip>
        </Marker>
      )}
    </>
  );
}

export default function LiveStormMap({ storms, tracks, risks, focus, onFocus, emptyMessage }) {
  const allBounds = useMemo(() => {
    return (storms ?? []).flatMap((s) => positionsFor(s, tracks[s.storm_id]).map((p) => [p.lat, p.lon]));
  }, [storms, tracks]);

  const focusBounds = useMemo(() => {
    if (!focus) return null;
    const planPoints = (r) => [r?.staging, ...(r?.counties ?? [])].filter((p) => p?.lat != null).map((p) => [p.lat, p.lon]);
    if (focus === "resources") {
      const pts = Object.values(risks ?? {}).flatMap(planPoints);
      return pts.length ? pts : null;
    }
    const s = storms?.find((x) => x.storm_id === focus);
    return s ? [...positionsFor(s, tracks[s.storm_id]).map((p) => [p.lat, p.lon]), ...planPoints(risks?.[s.storm_id])] : null;
  }, [focus, storms, tracks, risks]);

  const tiersPresent = useMemo(() => {
    const levels = new Set(Object.values(risks ?? {}).flatMap((r) => (r?.counties ?? []).map((c) => getRiskLevel(c.risk_tier))));
    return ["severe", "high", "moderate", "low"].filter((l) => levels.has(l));
  }, [risks]);

  const levelsPresent = useMemo(() => {
    const seen = new Map();
    for (const s of storms ?? []) {
      for (const p of positionsFor(s, tracks[s.storm_id])) {
        const c = categoryFor(p.vmax_kt);
        seen.set(c.level, c);
      }
    }
    return [...seen.values()].sort((a, b) => a.level - b.level);
  }, [storms, tracks]);

  return (
    <div className="relative isolate overflow-hidden rounded-2xl border border-sky-900/40 bg-[#061527]">
      <MapContainer
        center={FALLBACK_CENTER}
        zoom={FALLBACK_ZOOM}
        scrollWheelZoom={false}
        worldCopyJump
        className="h-[540px] w-full max-[760px]:h-[380px]"
        aria-label="Map of active tropical cyclones, forecast tracks, and staged resources"
      >
        <LayersControl position="topright">
          <LayersControl.BaseLayer checked name="Dark">
            <LayerGroup>
              <TileLayer url={`${ESRI}/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}`} attribution={ESRI_ATTRIBUTION} maxZoom={16} />
              <TileLayer url={`${ESRI}/Canvas/World_Dark_Gray_Reference/MapServer/tile/{z}/{y}/{x}`} maxZoom={16} />
            </LayerGroup>
          </LayersControl.BaseLayer>
          <LayersControl.BaseLayer name="Satellite">
            <LayerGroup>
              <TileLayer url={`${ESRI}/World_Imagery/MapServer/tile/{z}/{y}/{x}`} attribution={`${ESRI_ATTRIBUTION}, Maxar, Earthstar Geographics`} maxZoom={16} />
              <TileLayer url={`${ESRI}/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}`} maxZoom={16} />
            </LayerGroup>
          </LayersControl.BaseLayer>
        </LayersControl>
        <FocusController allBounds={allBounds} focusBounds={focusBounds} />
        {(storms ?? []).map((s) => (
          <PlanLayer
            key={`plan-${s.storm_id}`}
            storm={s}
            risk={risks?.[s.storm_id]}
            dim={!!focus && focus !== "resources" && focus !== s.storm_id}
            showShelters={focus === s.storm_id}
          />
        ))}
        {(storms ?? []).map((s) => (
          <StormLayer
            key={s.storm_id}
            storm={s}
            track={tracks[s.storm_id]}
            selected={focus && focus !== "resources" ? focus === s.storm_id : undefined}
            onSelect={onFocus}
          />
        ))}
      </MapContainer>

      {emptyMessage && (
        <div className="pointer-events-none absolute inset-x-0 top-4 z-[500] mx-auto w-fit rounded-lg border border-sky-400/30 bg-sky-950/85 px-3 py-1.5 text-xs font-semibold text-sky-100">
          {emptyMessage}
        </div>
      )}

      <div className="absolute bottom-2.5 left-2.5 z-[500] hidden max-w-[calc(100%-1.25rem)] flex-wrap gap-x-3 gap-y-1 rounded-lg border border-white/10 bg-[#061527]/85 px-2.5 py-1.5 text-[0.7rem] text-sky-100 backdrop-blur-xs sm:flex" aria-hidden="true">
        {levelsPresent.map((c) => (
          <span key={c.level} className="inline-flex items-center gap-1.5">
            <span className="size-2.5 rounded-full" style={{ background: c.color }} />{c.short}
          </span>
        ))}
        <span className="inline-flex items-center gap-1.5">
          <span className="h-0.5 w-4 border-t-2 border-dashed border-white/80" />Forecast track
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="size-2.5 rounded-[2px] border-2 border-white" style={{ background: STAGING_COLOR }} />Staging (per storm)
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="h-0.5 w-4 border-t-2 border-dashed" style={{ borderColor: STAGING_COLOR }} />Truck route
        </span>
        {tiersPresent.map((l) => (
          <span key={l} className="inline-flex items-center gap-1.5">
            <span className="size-2.5 rounded-full border-2" style={{ borderColor: RISK_HEX[l], background: `${RISK_HEX[l]}66` }} />
            {getRiskLabel({ low: "green", moderate: "yellow", high: "orange", severe: "red" }[l])} county
          </span>
        ))}
        {focus && focus !== "resources" && (
          <span className="inline-flex items-center gap-1.5">
            <span className="size-2 rounded-full" style={{ background: SHELTER_COLOR }} />Shelter
          </span>
        )}
      </div>
    </div>
  );
}
