// Extracted from origin/xgboost-pred commit 30ea26c AgentLanding.jsx.
// Teammate console and scenario components, with explicit data provenance.
import { useEffect, useState } from "react";
import { fmt } from "../dallas/format.js";
import RiskBadge from "../components/RiskBadge.jsx";
import { getRiskLevel } from "../utils/riskTier.js";
import { fetchLiveRisk, fetchLiveStatus, fetchLiveStorms, fetchLiveTrack } from "../api.js";
import AtRiskCounties from "../components/live/AtRiskCounties.jsx";
import LiveStormMap from "../components/live/LiveStormMap.jsx";
import {
  basinLabel, categoryFor, classificationLabel, compass, ktToMph, mphToKt, positionsFor,
} from "../components/live/liveStorms.js";
import "./LiveOperations.css";

function FocusPill({ active, onClick, children }) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={`inline-flex cursor-pointer items-center gap-1.5 rounded-lg px-2.5 py-1 font-semibold transition-all ${
        active ? "bg-accent text-white shadow-xs" : "text-muted hover:text-ink"
      }`}
    >
      {children}
    </button>
  );
}

const hoursFromNow = (ms) => Math.round((ms - Date.now()) / 3.6e6);
const UTC_STAMP = { month: "short", day: "numeric", hour: "numeric", minute: "2-digit", timeZone: "UTC", timeZoneName: "short" };

function StormCard({ storm, track, trackState, risk, riskState, selected, onSelect }) {
  const cat = categoryFor(storm.intensity_kt);
  const points = positionsFor(storm, track);
  const peak = points.reduce((m, p) => Math.max(m, Number(p.vmax_kt) || 0), 0);
  const lastForecast = track && points.length > 1 ? points[points.length - 1] : null;
  const updated = storm.last_update_utc ? new Date(storm.last_update_utc) : null;
  const speedMph = storm.movement_speed_mph;

  return (
    <div
      role="button"
      tabIndex={0}
      aria-pressed={selected}
      onClick={onSelect}
      onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onSelect(); } }}
      className={`flex cursor-pointer flex-col gap-2 rounded-2xl border bg-[#061527] p-3.5 text-left text-white transition-all ${
        selected ? "border-sky-300 ring-2 ring-sky-400/40" : "border-sky-900/40 hover:border-sky-500/50"
      }`}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="truncate font-heading text-base font-bold">{classificationLabel(storm.classification)} {storm.name}</div>
          <div className="text-[0.7rem] text-sky-200/70">{storm.storm_id} · {basinLabel(storm.storm_id)}{storm.advisory_num ? ` · Adv ${storm.advisory_num}` : ""}</div>
        </div>
        <span className="shrink-0 rounded-md px-2 py-0.5 text-[0.68rem] font-extrabold text-[#061527]" style={{ background: cat.color }}>
          {cat.short}
        </span>
      </div>

      <dl className="grid grid-cols-2 gap-x-3 gap-y-1.5 text-xs">
        <div><dt className="text-[0.62rem] uppercase text-sky-300">Max wind</dt><dd className="font-bold">{storm.intensity_kt} kt ({ktToMph(storm.intensity_kt)} mph)</dd></div>
        <div><dt className="text-[0.62rem] uppercase text-sky-300">Pressure</dt><dd className="font-bold">{storm.pressure_mb ? `${storm.pressure_mb} mb` : "—"}</dd></div>
        <div><dt className="text-[0.62rem] uppercase text-sky-300">Moving</dt><dd className="font-bold">{speedMph != null ? `${compass(storm.movement_dir_deg)} at ${speedMph} mph` : "—"}</dd></div>
        <div><dt className="text-[0.62rem] uppercase text-sky-300">Position</dt><dd className="font-bold">{Math.abs(storm.lat).toFixed(1)}°{storm.lat >= 0 ? "N" : "S"}, {Math.abs(storm.lon).toFixed(1)}°{storm.lon <= 0 ? "W" : "E"}</dd></div>
      </dl>

      <div className="border-t border-sky-800/50 pt-2 text-[0.72rem] leading-snug text-sky-100/90">
        {track ? (
          <>
            Forecast peak <strong>{peak} kt ({categoryFor(peak).short})</strong>
            {lastForecast && <> · reaches {lastForecast.lat.toFixed(1)}°N, {Math.abs(lastForecast.lon).toFixed(1)}°W in ~{hoursFromNow(lastForecast.ms)}h</>}
          </>
        ) : trackState === "loading" ? (
          "Loading NHC forecast track…"
        ) : (
          <span className="text-amber-300">NHC forecast track unavailable; map shows current motion only ({speedMph != null ? `${mphToKt(speedMph)} kt` : "—"}).</span>
        )}
        <div className="mt-1">
          {riskState === "loading" && <span className="text-sky-200/70">Scoring counties along the track…</span>}
          {riskState === "error" && <span className="text-amber-300">County risk view unavailable.</span>}
          {risk && (risk.counties.length ? (
            <span className="font-semibold text-amber-300">
              {risk.counties.length} US counties at risk · ~{fmt(risk.counties.reduce((a, c) => a + c.customers_out.median, 0))} customers out
              {risk.staging && <span className="block font-normal text-sky-200/80">Staging: {risk.staging.county}, {risk.staging.state}</span>}
            </span>
          ) : (
            <span className="text-sky-200/70">No US counties at risk on this forecast.</span>
          ))}
        </div>
      </div>

      <div className="flex items-center justify-between text-[0.66rem] text-sky-300/70">
        <span>{updated ? `Updated ${updated.toLocaleString("en-US", UTC_STAMP)}` : ""}</span>
        {storm.public_advisory_url && (
          <a href={storm.public_advisory_url} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()} className="font-semibold text-sky-300 hover:underline">
            NHC advisory ↗
          </a>
        )}
      </div>
    </div>
  );
}

function LiveFeedConsole({ onOpenScenario, agents }) {
  const [liveStatus, setLiveStatus] = useState(null);
  const [liveStorms, setLiveStorms] = useState(null);
  const [risks, setRisks] = useState({});
  const [riskState, setRiskState] = useState({});
  const [tracks, setTracks] = useState({});
  const [trackState, setTrackState] = useState({});
  const [focus, setFocus] = useState(null); // null = all, a storm_id, or "resources"
  const [loading, setLoading] = useState(true);
  const storms = liveStorms ?? [];

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      fetchLiveStatus().catch(() => null),
      fetchLiveStorms().catch(() => null),
    ]).then(([status, storms]) => {
      if (cancelled) return;
      setLiveStatus(status);
      setLiveStorms(storms);
      setLoading(false);
    });
    return () => { cancelled = true; };
  }, []);

  // One official-track request per live storm; a failure only affects that storm.
  useEffect(() => {
    if (!liveStorms?.length) return;
    let cancelled = false;
    setTrackState(Object.fromEntries(liveStorms.map((s) => [s.storm_id, "loading"])));
    for (const s of liveStorms) {
      fetchLiveTrack(s.storm_id)
        .then((t) => {
          if (cancelled) return;
          setTracks((m) => ({ ...m, [s.storm_id]: t }));
          setTrackState((m) => ({ ...m, [s.storm_id]: "ok" }));
        })
        .catch(() => { if (!cancelled) setTrackState((m) => ({ ...m, [s.storm_id]: "error" })); });
    }
    return () => { cancelled = true; };
  }, [liveStorms]);

  // Each storm's at-risk counties and its own staging site (slow on the backend's first run).
  useEffect(() => {
    if (!liveStorms?.length) return;
    let cancelled = false;
    setRiskState(Object.fromEntries(liveStorms.map((s) => [s.storm_id, "loading"])));
    for (const s of liveStorms) {
      fetchLiveRisk(s.storm_id)
        .then((r) => {
          if (cancelled) return;
          setRisks((m) => ({ ...m, [s.storm_id]: r }));
          setRiskState((m) => ({ ...m, [s.storm_id]: "ok" }));
        })
        .catch(() => { if (!cancelled) setRiskState((m) => ({ ...m, [s.storm_id]: "error" })); });
    }
    return () => { cancelled = true; };
  }, [liveStorms]);

  // The storm whose plan the side panel and county section show: the focused one, else the one
  // needing the most trucks, else the first.
  const focusedStorm = storms.find((s) => s.storm_id === focus);
  const neediest = [...storms].sort((a, b) =>
    (risks[b.storm_id]?.trucks_needed_total?.median ?? -1) - (risks[a.storm_id]?.trucks_needed_total?.median ?? -1))[0];
  const planStorm = focusedStorm ?? neediest;
  const plan = planStorm ? risks[planStorm.storm_id] : null;

  return (
    <>
    <div className="mt-12 overflow-hidden rounded-3xl border border-sky-100 dark:border-sky-500/20 bg-surface ocean-card-shadow">
      {/* Header Bar */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line bg-gradient-to-r from-sky-950 via-[#0a2342] to-teal-950 px-6 py-4 text-white">
        <div className="flex items-center gap-3">
          <span className="relative flex size-3">
            <span className={`relative inline-flex size-3 rounded-full ${liveStatus?.status === "online" ? "bg-sky-400" : "bg-slate-400"}`} />
          </span>
          <div>
            <div className="flex items-center gap-2">
              <h3 className="font-heading text-base font-bold text-white">NOAA Live Satellite &amp; Resource Console</h3>
              <span className="rounded-full bg-emerald-500/20 border border-emerald-400/40 px-2 py-0.5 text-[0.68rem] font-semibold text-emerald-300">
                {loading ? "Loading feeds…" : liveStatus?.status === "online" ? "NOAA/NWS cached feed" : "Live feed unavailable"}
              </span>
            </div>
            <p className="text-[0.75rem] text-sky-200/70">
              {liveStatus?.source ?? "NOAA NHC Active Storms & NWS Tropical Alerts Feed"} &bull; Live storm positions, NHC forecast tracks &amp; per-storm county risk
            </p>
          </div>
        </div>

        {/* Live Metrics Counter */}
        <div className="flex items-center gap-4 text-xs font-semibold">
          <div className="flex items-center gap-1.5 rounded-lg bg-white/10 px-3 py-1.5 backdrop-blur-xs">
            <span className="text-sky-300">Active Tropical Cyclones:</span>
            <span className="text-white font-extrabold">{liveStorms?.length ?? "—"}</span>
          </div>
          <div className="hidden sm:flex items-center gap-1.5 rounded-lg bg-white/10 px-3 py-1.5 backdrop-blur-xs">
            <span className="text-teal-300">Active NWS Alerts:</span>
            <span className="text-white font-extrabold">{liveStatus?.active_tropical_alerts_count ?? "—"}</span>
          </div>
        </div>
      </div>

      <p className="px-6 py-3 text-xs text-muted" role="status">
        {loading ? "Loading NOAA/NWS feeds and demo staging…" : "Storms, tracks and counts use the backend’s five-minute cache; refresh this page to request an update."}
        {!loading && (!liveStatus || liveStatus.status !== "online" || !liveStorms) && " Some live feeds are unavailable; missing counts are not replaced with sample values."}
        {liveStatus?.last_polled_utc && " Last poll attempt: " + liveStatus.last_polled_utc + ". Cached data may be stale."}
      </p>
      {/* Full-width live map: every active storm, its forecast track, and staged resources */}
      <div className="border-b border-line px-6 pb-6">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <span className="text-[0.72rem] font-bold uppercase tracking-wider text-accent">Active Storms &amp; Resources · NOAA NHC</span>
          <div className="flex flex-wrap items-center gap-1.5 rounded-xl border border-line bg-surface-subtle p-1 text-xs" role="group" aria-label="Map focus">
            <FocusPill active={focus === null} onClick={() => setFocus(null)}>All ({storms.length})</FocusPill>
            {storms.map((s) => (
              <FocusPill key={s.storm_id} active={focus === s.storm_id} onClick={() => setFocus(s.storm_id)}>
                <span className="size-2 rounded-full" style={{ background: categoryFor(s.intensity_kt).color }} />
                {s.name}
              </FocusPill>
            ))}
            <FocusPill active={focus === "resources"} onClick={() => setFocus("resources")}>Resources</FocusPill>
          </div>
        </div>

        <LiveStormMap
          storms={storms}
          tracks={tracks}
          risks={risks}
          focus={focus}
          onFocus={setFocus}
          emptyMessage={loading ? "Loading NOAA NHC storms…" : !liveStorms ? "Live storm feed unavailable" : storms.length === 0 ? "No active tropical cyclones reported by NHC" : null}
        />
        <p className="mt-2 text-[0.72rem] text-muted">
          Storm positions and forecast tracks come from NHC (CurrentStorms.json and the latest ATCF official forecast). At-risk counties come from the trained outage model; each storm's staging site and truck routes are a planning estimate.
        </p>
      </div>

      {/* Main Console Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-[1.4fr_1fr] divide-y lg:divide-y-0 lg:divide-x divide-line">
        {/* Left: one card per active storm */}
        <div className="relative flex min-w-0 flex-col p-6">
          <span className="mb-3 text-[0.72rem] font-bold uppercase tracking-wider text-accent">Active Systems · {storms.length}</span>
          {!loading && storms.length === 0 && (
            <p className="text-sm text-muted">{liveStorms ? "NHC reports no active tropical cyclones." : "Live storm feed unavailable. No sample storms substituted."}</p>
          )}
          {storms.length > 0 && (
            <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
              {storms.map((s) => (
                <StormCard
                  key={s.storm_id}
                  storm={s}
                  track={tracks[s.storm_id]}
                  trackState={trackState[s.storm_id]}
                  risk={risks[s.storm_id]}
                  riskState={riskState[s.storm_id]}
                  selected={focus === s.storm_id}
                  onSelect={() => setFocus(focus === s.storm_id ? null : s.storm_id)}
                />
              ))}
            </div>
          )}

          <div className="mt-4 flex items-center justify-between text-xs text-muted">
            <span>Historical replay: Hurricane Idalia, Taylor County</span>
            <button
              type="button"
              disabled={!agents?.some((a) => a.id === "taylor-hurricane" && !String(a.status ?? "").startsWith("error"))}
              onClick={() => onOpenScenario("taylor-hurricane")}
              className="flex items-center gap-1 font-bold text-accent hover:underline disabled:cursor-not-allowed disabled:opacity-50 disabled:no-underline"
            >
              Launch Taylor County Dashboard &rarr;
            </button>
          </div>
        </div>

        {/* Right: the selected storm's own staging plan */}
        <div className="flex min-w-0 flex-col p-6 bg-[#f8fafc]/50">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <span className="text-[0.72rem] font-bold uppercase tracking-wider text-accent">Resource Staging Plan</span>
            <span className="rounded-md border border-teal-200 bg-teal-50 px-2 py-0.5 text-[0.68rem] font-bold text-teal-800 dark:border-teal-800 dark:bg-teal-950 dark:text-teal-300">
              Per storm · planning estimate
            </span>
          </div>

          {planStorm && (
            <div className="mb-3 flex flex-wrap gap-1.5 text-xs" role="group" aria-label="Plan for storm">
              {storms.map((s) => (
                <FocusPill key={s.storm_id} active={s.storm_id === planStorm.storm_id} onClick={() => setFocus(s.storm_id)}>
                  <span className="size-2 rounded-full" style={{ background: categoryFor(s.intensity_kt).color }} />
                  {s.name}
                </FocusPill>
              ))}
            </div>
          )}

          {!planStorm && !loading && <p className="text-sm text-muted">No active storms, so no staging plan.</p>}
          {planStorm && riskState[planStorm.storm_id] === "loading" && <p role="status" className="text-sm text-muted">Building {planStorm.name}&apos;s plan from the outage model…</p>}
          {planStorm && riskState[planStorm.storm_id] === "error" && <p role="alert" className="text-sm text-bad-text">{planStorm.name}&apos;s plan is unavailable. No sample plan substituted.</p>}
          {plan && !plan.staging && <p className="text-sm text-muted">{plan.note ?? `No staging site needed for ${planStorm.name}.`}</p>}

          {plan?.staging && (
            <>
              <h4 className="font-heading text-lg font-bold text-navy">{plan.staging.name}</h4>
              <p className="mt-0.5 text-xs text-muted">
                For {classificationLabel(planStorm.classification)} {planStorm.name}: {plan.staging.clearance_from_track_nm} nm clear of the forecast track,
                avg {plan.staging.avg_distance_to_counties_nm} nm to the counties it serves.
              </p>

              <div className="mt-4 grid grid-cols-2 gap-3">
                <div className="rounded-2xl border border-line bg-surface p-3.5 shadow-2xs">
                  <span className="text-[0.68rem] font-bold uppercase text-muted">Utility trucks (est.)</span>
                  <div className="mt-1 font-heading text-2xl font-extrabold text-navy">{fmt(plan.trucks_needed_total.median)}</div>
                  <span className="text-[0.72rem] font-medium text-accent">range {fmt(plan.trucks_needed_total.low)}–{fmt(plan.trucks_needed_total.high)}</span>
                </div>
                <div className="rounded-2xl border border-line bg-surface p-3.5 shadow-2xs">
                  <span className="text-[0.68rem] font-bold uppercase text-muted">Shelter beds</span>
                  <div className="mt-1 font-heading text-2xl font-extrabold text-navy">{fmt(plan.counties.reduce((a, c) => a + c.shelters.evacuation_capacity, 0))}</div>
                  <span className="text-[0.72rem] font-medium text-emerald-600">in {plan.counties.length} at-risk counties</span>
                </div>
              </div>

              <div className="mt-4">
                <span className="text-[0.7rem] font-bold uppercase text-muted">Trucks by county</span>
                <div className="mt-2 space-y-1.5">
                  {plan.counties.map((c) => (
                    <div key={c.fips} className="flex items-center justify-between gap-2 rounded-xl border border-line bg-surface px-3 py-2 text-xs">
                      <span className="min-w-0 truncate font-semibold text-ink">{c.name}, {c.state}</span>
                      <span className="flex shrink-0 items-center gap-2">
                        <span className="text-muted">~{fmt(c.customers_out.median)} out</span>
                        <span className="font-extrabold text-navy">{fmt(c.trucks_needed.median)} trucks</span>
                        <RiskBadge level={getRiskLevel(c.risk_tier)}>{c.risk_tier === "red" ? "Severe" : c.risk_tier === "orange" ? "High" : c.risk_tier === "yellow" ? "Mod." : "Low"}</RiskBadge>
                      </span>
                    </div>
                  ))}
                </div>
              </div>

              <p className="mt-4 border-t border-line pt-3 text-[0.7rem] text-muted">
                Site: {plan.staging.method}. {plan.assumptions.join(" ")}
              </p>
            </>
          )}
        </div>
      </div>
    </div>

    <AtRiskCounties
      storms={storms}
      risks={risks}
      riskState={riskState}
      selectedId={planStorm?.storm_id}
      onSelect={setFocus}
      agents={agents}
      onOpenAgent={onOpenScenario}
    />
    </>
  );
}


export default function LiveOperations({ agents, error, onOpen, onBack }) {
  useEffect(() => { window.scrollTo({ top: 0, behavior: "instant" }); }, []);
  return <section className="live-operations mx-auto max-w-[1420px] px-6 py-6 lg:px-10">
    <button type="button" onClick={onBack} className="text-sm font-semibold text-accent hover:underline">← Back to Overview</button>
    <h1 className="mt-4 text-2xl font-bold text-navy">Live Operations</h1>
    <LiveFeedConsole onOpenScenario={onOpen} agents={agents} />
    {error && <p role="alert" className="mt-4 text-bad-text">{error}</p>}
    {!agents && !error && <p role="status">Loading county scenarios…</p>}
  </section>;
}
