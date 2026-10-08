// Extracted from origin/xgboost-pred commit 30ea26c AgentLanding.jsx.
// Teammate console and scenario components, with explicit data provenance.
import { useEffect, useState } from "react";
import { fmt } from "../dallas/format.js";
import { fetchLiveStatus, fetchLiveStorms, fetchStaging } from "../api.js";
import "./LiveOperations.css";
function LiveFeedConsole({ onOpenScenario, agents }) {
  const [liveStatus, setLiveStatus] = useState(null);
  const [liveStorms, setLiveStorms] = useState(null);
  const [stagingData, setStagingData] = useState(null);
  const [activeTab, setActiveTab] = useState("isaias"); // or 'staging'
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      fetchLiveStatus().catch(() => null),
      fetchLiveStorms().catch(() => null),
      fetchStaging(14).catch(() => null),
    ]).then(([status, storms, staging]) => {
      if (cancelled) return;
      setLiveStatus(status);
      setLiveStorms(storms);
      setStagingData(staging);
      setLoading(false);
    });
    return () => { cancelled = true; };
  }, []);

  return (
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
              {liveStatus?.source ?? "NOAA NHC Active Storms & NWS Tropical Alerts Feed"} &bull; Feed counts only • telemetry below is demo data
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
        {loading ? "Loading NOAA/NWS feeds and demo staging…" : "Feed counts use the backend’s five-minute cache; refresh this page to request an update."}
        {!loading && (!liveStatus || liveStatus.status !== "online" || !liveStorms) && " Some live feeds are unavailable; missing counts are not replaced with sample values."}
        {liveStatus?.last_polled_utc && " Last poll attempt: " + liveStatus.last_polled_utc + ". Cached data may be stale."}
      </p>
      {/* Main Console Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-[1.4fr_1fr] divide-y lg:divide-y-0 lg:divide-x divide-line">
        {/* Left: Clickable Map / Radar Simulation */}
        <div className="relative flex flex-col p-6">
          <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
            <span className="text-[0.72rem] font-bold uppercase tracking-wider text-accent">Active System Telemetry · Demo</span>
            {/* Storm Switcher Pills */}
            <div className="flex items-center gap-1.5 rounded-xl border border-line bg-surface-subtle p-1 text-xs">
              <button
                type="button"
                onClick={() => setActiveTab("isaias")}
                className={`cursor-pointer rounded-lg px-2.5 py-1 font-semibold transition-all ${
                  activeTab === "isaias" ? "bg-accent text-white shadow-xs" : "text-muted hover:text-ink"
                }`}
              >
                TS Isaias (Demo)
              </button>
              <button
                type="button"
                onClick={() => setActiveTab("rachel")}
                className={`cursor-pointer rounded-lg px-2.5 py-1 font-semibold transition-all ${
                  activeTab === "rachel" ? "bg-accent text-white shadow-xs" : "text-muted hover:text-ink"
                }`}
              >
                HU Rachel (Demo)
              </button>
              <button
                type="button"
                onClick={() => setActiveTab("taylor")}
                className={`cursor-pointer rounded-lg px-2.5 py-1 font-semibold transition-all ${
                  activeTab === "taylor" ? "bg-accent text-white shadow-xs" : "text-muted hover:text-ink"
                }`}
              >
                Taylor County (Replay)
              </button>
            </div>
          </div>

          <p className="mb-3 text-xs text-muted">Hardcoded illustrative telemetry and animated radar, not live satellite imagery. Tabs do not change the staging plan.</p>
          {/* Radar Screen Area */}
          <div className="relative flex min-h-[340px] w-full flex-col justify-between gap-4 overflow-hidden rounded-2xl border border-sky-900/30 bg-[#061527] p-5 text-white shadow-inner">
            {/* Radar Grid & Concentric Rings */}
            <div className="pointer-events-none absolute inset-0 [background-image:radial-gradient(circle_at_center,rgba(56,189,248,0.12)_1px,transparent_1px)] [background-size:24px_24px]" />
            <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
              <div className="size-64 rounded-full border border-sky-500/20" />
              <div className="size-44 rounded-full border border-teal-500/25" />
              <div className="size-24 rounded-full border border-sky-400/30" />
              {/* Radar sweep beam */}
              <div className="animate-radar absolute size-64 rounded-full bg-[conic-gradient(from_0deg,transparent_0deg,transparent_300deg,rgba(56,189,248,0.25)_360deg)]" />
            </div>

            {/* Storm Coordinates Node */}
            <div className="relative z-10 flex items-start justify-between">
              <div>
                <div className="flex items-center gap-2">
                  <span className="font-heading text-lg font-bold text-white">
                    {activeTab === "isaias" ? "Tropical Storm Isaias (AL092026)" : activeTab === "rachel" ? "Hurricane Rachel (EP182026)" : "Hurricane Idalia (Taylor County)"}
                  </span>
                  <span className="rounded bg-sky-500/30 border border-sky-400 px-2 py-0.5 text-[0.65rem] font-bold text-sky-200">
                    {activeTab === "isaias" ? "55 KT • 994 MB" : activeTab === "rachel" ? "CAT 1 • 70 KT" : "CAT 3 • 110 KT"}
                  </span>
                </div>
                <p className="text-xs text-sky-200/70">
                  {activeTab === "isaias" ? "Gulf of Mexico • Lat 22.7°N, Lon 92.9°W" : activeTab === "rachel" ? "East Pacific • Lat 21.2°N, Lon 122.3°W" : "Florida Big Bend • Lat 29.8°N, Lon 83.6°W"}
                </p>
              </div>

              {/* Pulsing Target Indicator */}
              <div className="flex items-center gap-2 rounded-xl bg-sky-950/80 border border-sky-400/30 px-3 py-1.5 backdrop-blur-xs text-xs font-semibold">
                <span className="size-2 rounded-full bg-rose-500 animate-ping" />
                <span>Demo / Replay</span>
              </div>
            </div>

            {/* Sea Surface & Environmental Telemetry Bar */}
            <div className="relative z-10 grid grid-cols-2 sm:grid-cols-4 gap-2.5 pt-4 border-t border-sky-800/50 text-xs">
              <div className="rounded-xl bg-white/5 p-2.5 backdrop-blur-xs">
                <span className="text-[0.65rem] uppercase text-sky-300">Sea Surface Temp</span>
                <div className="text-sm font-extrabold text-white">29.6°C / 85.3°F</div>
                <span className="text-[0.65rem] text-emerald-400">Warm Loop Current</span>
              </div>
              <div className="rounded-xl bg-white/5 p-2.5 backdrop-blur-xs">
                <span className="text-[0.65rem] uppercase text-sky-300">Central Pressure</span>
                <div className="text-sm font-extrabold text-white">{activeTab === "isaias" ? "994 mb" : activeTab === "rachel" ? "979 mb" : "949 mb"}</div>
                <span className="text-[0.65rem] text-sky-300">Deepening</span>
              </div>
              <div className="rounded-xl bg-white/5 p-2.5 backdrop-blur-xs">
                <span className="text-[0.65rem] uppercase text-sky-300">Max Wind Gusts</span>
                <div className="text-sm font-extrabold text-white">{activeTab === "isaias" ? "65 mph" : activeTab === "rachel" ? "85 mph" : "130 mph"}</div>
                <span className="text-[0.65rem] text-amber-300">Tropical Force</span>
              </div>
              <div className="rounded-xl bg-white/5 p-2.5 backdrop-blur-xs">
                <span className="text-[0.65rem] uppercase text-sky-300">Forward Motion</span>
                <div className="text-sm font-extrabold text-white">8 kt (9 mph)</div>
                <span className="text-[0.65rem] text-sky-300">ENE (65°)</span>
              </div>
            </div>
          </div>

          <div className="mt-4 flex items-center justify-between text-xs text-muted">
            {activeTab === "taylor" && (
              <button
                type="button"
                disabled={!agents?.some((a) => a.id === "taylor-hurricane" && !String(a.status ?? "").startsWith("error"))}
                onClick={() => onOpenScenario("taylor-hurricane")}
                className="font-bold text-accent hover:underline flex items-center gap-1"
              >
                Launch Taylor County Dashboard &rarr;
              </button>
            )}
          </div>
        </div>

        {/* Right: Resource Optimizer & Allocation Status */}
        <div className="flex flex-col p-6 bg-[#f8fafc]/50">
          <div className="mb-3 flex items-center justify-between">
            <span className="text-[0.72rem] font-bold uppercase tracking-wider text-accent">Resource Staging Optimizer</span>
            <span className="rounded-md bg-teal-50 dark:bg-teal-950 border border-teal-200 dark:border-teal-800 px-2 py-0.5 text-[0.68rem] font-bold text-teal-800 dark:text-teal-300">
              Stub-based demo plan
            </span>
          </div>

          <h4 className="font-heading text-lg font-bold text-navy">
            {stagingData?.staging_area ?? "Staging unavailable"}
          </h4>
          <p className="text-xs text-muted mt-0.5">
            Highest-need-first allocation using backend demo inputs and a fixed 14-truck budget; not live fleet or shelter availability.
          </p>

          {!loading && !stagingData && <p role="alert" className="mt-3 text-sm text-bad-text">Staging service unavailable. No sample allocations substituted.</p>}
          {/* Staging KPI Tiles */}
          <div className="mt-4 grid grid-cols-2 gap-3">
            <div className="rounded-2xl border border-line bg-surface p-3.5 shadow-2xs">
              <span className="text-[0.68rem] font-bold uppercase text-muted">Utility Trucks</span>
              <div className="font-heading text-2xl font-extrabold text-navy mt-1">
                {stagingData?.trucks_available ?? "—"} <span className="text-sm text-muted font-normal">avail</span>
              </div>
              <span className="text-[0.72rem] text-accent font-medium">Demo truck budget</span>
            </div>

            <div className="rounded-2xl border border-line bg-surface p-3.5 shadow-2xs">
              <span className="text-[0.68rem] font-bold uppercase text-muted">Demo Shelter Beds</span>
              <div className="font-heading text-2xl font-extrabold text-navy mt-1">
                {stagingData ? fmt(stagingData.shelter_beds_available) : "—"}
              </div>
              <span className="text-[0.72rem] text-emerald-600 font-medium">Demand: {stagingData ? fmt(stagingData.shelter_demand_estimate) : "—"}</span>
            </div>
          </div>

          {/* County Allocations List */}
          <div className="mt-4 flex flex-1 flex-col justify-between">
            <div>
              <span className="text-[0.7rem] font-bold uppercase text-muted">County Truckload Allocations</span>
              <div className="mt-2 space-y-1.5">
                {(stagingData?.allocations ?? []).map((alloc) => (
                  <div key={alloc.county} className="flex items-center justify-between rounded-xl border border-line bg-surface px-3 py-2 text-xs">
                    <span className="font-semibold text-ink">{alloc.county}</span>
                    <div className="flex items-center gap-2">
                      <span className="font-extrabold text-navy">{alloc.truckloads_assigned} / {alloc.truckloads_needed} trucks</span>
                      {alloc.truckloads_assigned === alloc.truckloads_needed ? (
                        <span className="size-2 rounded-full bg-emerald-500" title="Met" />
                      ) : (
                        <span className="size-2 rounded-full bg-amber-500" title="Gap" />
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>

            <div className="mt-4 pt-3 border-t border-line flex items-center justify-between text-xs">
              <span className="text-muted">Method: highest-need-first (stub)</span>
              <span className="font-bold text-accent">{stagingData ? `Demo shelter shortfall: ${fmt(stagingData.shelter_bed_shortfall)}` : "Shortfall unavailable"}</span>
            </div>
          </div>
        </div>
      </div>
    </div>
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
