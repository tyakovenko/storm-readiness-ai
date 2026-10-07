import mapBg from "./assets/north_america_map.jpg";
import { useState, useEffect } from "react";
import { PAGE } from "./components/Page.jsx";
import { fmt } from "./dallas/format.js";
import { fetchLiveStatus, fetchLiveStorms, fetchStaging } from "./api.js";

const PROMPT_EXAMPLES = [
  "Which areas are at highest outage risk?",
  "Where should we stage utility crews?",
  "Which shelters are vulnerable to storm surge?",
  "Compare Taylor County with Hurricane Idalia",
];

function WaveIcon() {
  return (
    <svg className="size-4 text-sky-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M2 6c.6.5 1.2 1 2.5 1C7 7 7 5 9.5 5c2.6 0 2.4 2 5 2 2.5 0 2.5-2 5-2 1.3 0 1.9.5 2.5 1" />
      <path d="M2 12c.6.5 1.2 1 2.5 1 2.5 0 2.5-2 5-2 2.6 0 2.4 2 5 2 2.5 0 2.5-2 5-2 1.3 0 1.9.5 2.5 1" />
      <path d="M2 18c.6.5 1.2 1 2.5 1 2.5 0 2.5-2 5-2 2.6 0 2.4 2 5 2 2.5 0 2.5-2 5-2 1.3 0 1.9.5 2.5 1" />
    </svg>
  );
}

function HurricaneIcon() {
  return (
    <svg className="size-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="3" />
      <path d="M12 2a10 10 0 0 0-9.5 13.5L2 17l1.5-.5A10 10 0 0 0 12 22a10 10 0 0 0 9.5-13.5L22 7l-1.5.5A10 10 0 0 0 12 2z" />
    </svg>
  );
}

function SnowflakeIcon() {
  return (
    <svg className="size-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 2v20M2 12h20M4.93 4.93l14.14 14.14M19.07 4.93L4.93 19.07" />
    </svg>
  );
}

function CompassIcon() {
  return (
    <svg className="size-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="10" />
      <polygon points="16.24 7.76 14.12 14.12 7.76 16.24 9.88 9.88 16.24 7.76" />
    </svg>
  );
}

// Subtle topographical & Google Maps style vector backdrop
function MapBackground() {
  return (
    <div className="pointer-events-none absolute inset-0 z-0 overflow-hidden">
      {/* High-res North America Map */}
      <img
        src={mapBg}
        alt="North America operational storm areas"
        className="absolute inset-0 size-full object-cover object-center opacity-85 dark:opacity-35 transition-opacity select-none mix-blend-multiply dark:mix-blend-luminosity filter contrast-105"
      />
      
      {/* Soft translucent wash for perfect text readability */}
      <div className="absolute inset-0 bg-white/40 dark:bg-slate-950/60 backdrop-blur-[0.5px]" />
      <div className="absolute inset-0 bg-gradient-to-b from-transparent via-white/30 to-white/70 dark:via-slate-950/40 dark:to-slate-950/80" />

      {/* Pulsing Target Area Indicators */}
      {/* Dallas, TX */}
      <div className="absolute left-[46%] top-[54%] -translate-x-1/2 -translate-y-1/2 hidden sm:flex items-center gap-1.5">
        <span className="relative flex size-3">
          <span className="absolute inline-flex size-full animate-ping rounded-full bg-sky-400 opacity-75" />
          <span className="relative inline-flex size-3 rounded-full bg-sky-500 ring-2 ring-white shadow-sm" />
        </span>
        <span className="rounded-md bg-white/95 dark:bg-slate-900/90 px-1.5 py-0.5 text-[0.62rem] font-extrabold uppercase text-sky-800 dark:text-sky-300 shadow-sm border border-sky-200 dark:border-sky-800">
          Dallas
        </span>
      </div>

      {/* Houston / Harris County, TX */}
      <div className="absolute left-[49%] top-[66%] -translate-x-1/2 -translate-y-1/2 hidden sm:flex items-center gap-1.5">
        <span className="relative flex size-3">
          <span className="absolute inline-flex size-full animate-ping rounded-full bg-teal-400 opacity-75" />
          <span className="relative inline-flex size-3 rounded-full bg-teal-500 ring-2 ring-white shadow-sm" />
        </span>
        <span className="rounded-md bg-white/95 dark:bg-slate-900/90 px-1.5 py-0.5 text-[0.62rem] font-extrabold uppercase text-teal-800 dark:text-teal-300 shadow-sm border border-teal-200 dark:border-teal-800">
          Houston
        </span>
      </div>

      {/* Big Bend / Taylor County, FL */}
      <div className="absolute left-[62%] top-[64%] -translate-x-1/2 -translate-y-1/2 hidden sm:flex items-center gap-1.5">
        <span className="relative flex size-3.5">
          <span className="absolute inline-flex size-full animate-ping rounded-full bg-cyan-400 opacity-80" />
          <span className="relative inline-flex size-3.5 rounded-full bg-cyan-500 ring-2 ring-white shadow-sm" />
        </span>
        <span className="rounded-md bg-white/95 dark:bg-slate-900/90 px-1.5 py-0.5 text-[0.62rem] font-extrabold uppercase text-cyan-800 dark:text-cyan-300 shadow-sm border border-cyan-200 dark:border-cyan-800">
          Big Bend
        </span>
      </div>

      {/* Fort Myers / Lee County, FL */}
      <div className="absolute left-[65%] top-[73%] -translate-x-1/2 -translate-y-1/2 hidden sm:flex items-center gap-1.5">
        <span className="relative flex size-3">
          <span className="absolute inline-flex size-full animate-ping rounded-full bg-sky-400 opacity-75" />
          <span className="relative inline-flex size-3 rounded-full bg-sky-500 ring-2 ring-white shadow-sm" />
        </span>
        <span className="rounded-md bg-white/95 dark:bg-slate-900/90 px-1.5 py-0.5 text-[0.62rem] font-extrabold uppercase text-sky-800 dark:text-sky-300 shadow-sm border border-sky-200 dark:border-sky-800">
          Fort Myers
        </span>
      </div>

      {/* Miami, FL */}
      <div className="absolute left-[68%] top-[76%] -translate-x-1/2 -translate-y-1/2 hidden sm:flex items-center gap-1.5">
        <span className="relative flex size-3">
          <span className="absolute inline-flex size-full animate-ping rounded-full bg-teal-400 opacity-75" />
          <span className="relative inline-flex size-3 rounded-full bg-teal-500 ring-2 ring-white shadow-sm" />
        </span>
        <span className="rounded-md bg-white/95 dark:bg-slate-900/90 px-1.5 py-0.5 text-[0.62rem] font-extrabold uppercase text-teal-800 dark:text-teal-300 shadow-sm border border-teal-200 dark:border-teal-800">
          Miami
        </span>
      </div>
    </div>
  );
}

function CenteredAskBox({ onAsk }) {
  const [value, setValue] = useState("");

  function submit(e) {
    e.preventDefault();
    const q = value.trim();
    if (!q) return;
    onAsk(q);
    setValue("");
  }

  return (
    <div className="relative mx-auto w-full max-w-2xl">
      <div className="glass-card rounded-2xl p-3 sm:p-4 shadow-xl border border-sky-100 dark:border-sky-500/20 ring-4 ring-sky-500/10 dark:ring-sky-400/20 backdrop-blur-xl">
        <form className="flex gap-2 max-[560px]:flex-col" onSubmit={submit}>
          <div className="relative flex-1">
            <div className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3.5">
              <svg className="size-4 text-sky-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2.5" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
              </svg>
            </div>
            <input
              id="home-ask"
              className="w-full rounded-xl border border-sky-200/80 bg-white/95 dark:bg-slate-900/90 dark:border-sky-800/80 pl-10 pr-4 py-3 text-[0.94rem] text-ink placeholder:text-muted/70 transition-all focus:border-accent focus:bg-white dark:focus:bg-slate-900 focus:outline-none focus:ring-2 focus:ring-sky-300/50 shadow-inner"
              value={value}
              onChange={(e) => setValue(e.target.value)}
              placeholder="Ask AI about storm risk, outages, or shelter readiness..."
            />
          </div>
          <button
            type="submit"
            className="cursor-pointer whitespace-nowrap rounded-xl bg-gradient-to-r from-sky-500 to-teal-500 px-6 py-3 font-semibold text-white shadow-md shadow-sky-500/25 transition-all duration-200 hover:from-sky-400 hover:to-teal-400 hover:shadow-lg active:scale-95"
          >
            Ask AI
          </button>
        </form>

        <div className="mt-3 flex flex-wrap items-center justify-center gap-2">
          <span className="text-[0.7rem] font-bold uppercase tracking-wider text-muted">Quick Inquiries:</span>
          {PROMPT_EXAMPLES.map((q) => (
            <button
              key={q}
              type="button"
              onClick={() => onAsk(q)}
              className="cursor-pointer rounded-full border border-sky-200/70 dark:border-sky-800 bg-white/80 dark:bg-slate-800/80 px-3 py-1 text-[0.75rem] font-medium text-sky-800 dark:text-sky-300 transition-all hover:border-accent hover:bg-sky-50 dark:hover:bg-slate-700 hover:shadow-xs active:scale-95"
            >
              {q}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

// Flashy Live Telemetry & Operations Console
function LiveFeedConsole({ onOpenScenario }) {
  const [liveStatus, setLiveStatus] = useState(null);
  const [liveStorms, setLiveStorms] = useState([]);
  const [stagingData, setStagingData] = useState(null);
  const [activeTab, setActiveTab] = useState("isaias"); // or 'staging'
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      fetchLiveStatus().catch(() => null),
      fetchLiveStorms().catch(() => []),
      fetchStaging(14).catch(() => null),
    ]).then(([status, storms, staging]) => {
      setLiveStatus(status);
      setLiveStorms(storms);
      setStagingData(staging);
      setLoading(false);
    });
  }, []);

  return (
    <div className="mt-12 overflow-hidden rounded-3xl border border-sky-100 dark:border-sky-500/20 bg-surface ocean-card-shadow">
      {/* Header Bar */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line bg-gradient-to-r from-sky-950 via-[#0a2342] to-teal-950 px-6 py-4 text-white">
        <div className="flex items-center gap-3">
          <span className="relative flex size-3">
            <span className="absolute inline-flex size-full animate-ping rounded-full bg-emerald-400 opacity-75" />
            <span className="relative inline-flex size-3 rounded-full bg-emerald-500" />
          </span>
          <div>
            <div className="flex items-center gap-2">
              <h3 className="font-heading text-base font-bold text-white">NOAA Live Satellite &amp; Resource Console</h3>
              <span className="rounded-full bg-emerald-500/20 border border-emerald-400/40 px-2 py-0.5 text-[0.68rem] font-semibold text-emerald-300">
                Active Feed Synchronized
              </span>
            </div>
            <p className="text-[0.75rem] text-sky-200/70">
              {liveStatus?.source ?? "NOAA NHC Active Storms & NWS Tropical Alerts Feed"} &bull; Real-time Weather Telemetry
            </p>
          </div>
        </div>

        {/* Live Metrics Counter */}
        <div className="flex items-center gap-4 text-xs font-semibold">
          <div className="flex items-center gap-1.5 rounded-lg bg-white/10 px-3 py-1.5 backdrop-blur-xs">
            <span className="text-sky-300">Active Tropical Cyclones:</span>
            <span className="text-white font-extrabold">{liveStorms.length || 3}</span>
          </div>
          <div className="hidden sm:flex items-center gap-1.5 rounded-lg bg-white/10 px-3 py-1.5 backdrop-blur-xs">
            <span className="text-teal-300">Active NWS Alerts:</span>
            <span className="text-white font-extrabold">{liveStatus?.active_tropical_alerts_count || 48}</span>
          </div>
        </div>
      </div>

      {/* Main Console Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-[1.4fr_1fr] divide-y lg:divide-y-0 lg:divide-x divide-line">
        {/* Left: Clickable Map / Radar Simulation */}
        <div className="relative flex flex-col p-6">
          <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
            <span className="text-[0.72rem] font-bold uppercase tracking-wider text-accent">Active System Telemetry</span>
            {/* Storm Switcher Pills */}
            <div className="flex items-center gap-1.5 rounded-xl border border-line bg-surface-subtle p-1 text-xs">
              <button
                type="button"
                onClick={() => setActiveTab("isaias")}
                className={`cursor-pointer rounded-lg px-2.5 py-1 font-semibold transition-all ${
                  activeTab === "isaias" ? "bg-accent text-white shadow-xs" : "text-muted hover:text-ink"
                }`}
              >
                TS Isaias (Gulf)
              </button>
              <button
                type="button"
                onClick={() => setActiveTab("rachel")}
                className={`cursor-pointer rounded-lg px-2.5 py-1 font-semibold transition-all ${
                  activeTab === "rachel" ? "bg-accent text-white shadow-xs" : "text-muted hover:text-ink"
                }`}
              >
                HU Rachel (Pac)
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

          {/* Radar Screen Area */}
          <div className="relative flex h-[340px] w-full flex-col justify-between overflow-hidden rounded-2xl border border-sky-900/30 bg-[#061527] p-5 text-white shadow-inner">
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
                <span>Tracking Live</span>
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
            <span>Click any scenario below to open full incident intelligence.</span>
            {activeTab === "taylor" && (
              <button
                type="button"
                onClick={() => onOpenScenario("taylor-hurricane")}
                className="font-bold text-accent hover:underline flex items-center gap-1"
              >
                Launch Taylor County Dashboard &rarr;
              </button>
            )}
          </div>
        </div>

        {/* Right: Resource Optimizer & Allocation Status */}
        <div className="flex flex-col p-6 bg-surface-subtle/50">
          <div className="mb-3 flex items-center justify-between">
            <span className="text-[0.72rem] font-bold uppercase tracking-wider text-accent">Resource Staging Optimizer</span>
            <span className="rounded-md bg-teal-50 dark:bg-teal-950 border border-teal-200 dark:border-teal-800 px-2 py-0.5 text-[0.68rem] font-bold text-teal-800 dark:text-teal-300">
              Live Staging Active
            </span>
          </div>

          <h4 className="font-heading text-lg font-bold text-navy">
            {stagingData?.staging_area ?? "Gainesville Staging Area"}
          </h4>
          <p className="text-xs text-muted mt-0.5">
            Optimized truck deployments and shelter bed allocations computed across vulnerable counties.
          </p>

          {/* Staging KPI Tiles */}
          <div className="mt-4 grid grid-cols-2 gap-3">
            <div className="rounded-2xl border border-line bg-surface p-3.5 shadow-2xs">
              <span className="text-[0.68rem] font-bold uppercase text-muted">Utility Trucks</span>
              <div className="font-heading text-2xl font-extrabold text-navy mt-1">
                {stagingData?.trucks_available ?? 10} <span className="text-sm text-muted font-normal">avail</span>
              </div>
              <span className="text-[0.72rem] text-accent font-medium">Full Crew Ready</span>
            </div>

            <div className="rounded-2xl border border-line bg-surface p-3.5 shadow-2xs">
              <span className="text-[0.68rem] font-bold uppercase text-muted">Shelter Beds Open</span>
              <div className="font-heading text-2xl font-extrabold text-navy mt-1">
                {fmt(stagingData?.shelter_beds_available ?? 2300)}
              </div>
              <span className="text-[0.72rem] text-emerald-600 font-medium">Demand: {fmt(stagingData?.shelter_demand_estimate ?? 1975)}</span>
            </div>
          </div>

          {/* County Allocations List */}
          <div className="mt-4 flex flex-1 flex-col justify-between">
            <div>
              <span className="text-[0.7rem] font-bold uppercase text-muted">County Truckload Allocations</span>
              <div className="mt-2 space-y-1.5">
                {(stagingData?.allocations ?? [
                  { county: "Levy County", truckloads_assigned: 5, truckloads_needed: 5 },
                  { county: "Dixie County", truckloads_assigned: 3, truckloads_needed: 3 },
                  { county: "Citrus County", truckloads_assigned: 2, truckloads_needed: 4 },
                  { county: "Taylor County", truckloads_assigned: 0, truckloads_needed: 2 },
                ]).map((alloc) => (
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
              <span className="text-muted">Optimizer: Mixed Integer / Greedy</span>
              <span className="font-bold text-accent">Zero Shelter Shortfall</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

export default function AgentLanding({ agents, error, onOpen, onAsk }) {
  const [filter, setFilter] = useState("all");

  const hurricaneAgents = (agents ?? []).filter(
    (a) => a.hazard === "hurricane" && !String(a.status ?? "").startsWith("error"),
  );
  const totalStorms = hurricaneAgents.reduce((sum, a) => sum + (a.storms ?? 0), 0);
  const totalShelters = hurricaneAgents.reduce((sum, a) => sum + (a.shelters ?? 0), 0);

  const filteredAgents = (agents ?? []).filter((a) => {
    if (filter === "hurricane") return a.hazard === "hurricane";
    if (filter === "winter") return a.hazard === "winter";
    return true;
  });

  return (
    <section className={PAGE}>
      {/* Centered Hero Header with North America Map Background */}
      <div className="relative isolate mx-auto w-full max-w-5xl overflow-hidden rounded-3xl border border-sky-200/80 dark:border-sky-500/20 bg-white/70 dark:bg-slate-900/80 py-10 sm:py-14 px-4 sm:px-8 text-center shadow-lg">
        <MapBackground />

        <div className="relative z-10">
          {/* Eyebrow Badge */}
          <div className="mb-4 inline-flex items-center gap-2 rounded-full border border-sky-200 dark:border-sky-800 bg-white/90 dark:bg-sky-950/90 px-4 py-1.5 text-[0.76rem] font-bold uppercase tracking-wider text-sky-800 dark:text-sky-300 shadow-xs backdrop-blur-md">
            <WaveIcon />
            <span>Operational Storm Intelligence &amp; Outage Forecasting</span>
          </div>

          {/* Centered Display Title */}
          <h1 className="mb-4 font-heading text-3xl font-extrabold tracking-tight text-navy sm:text-5xl lg:text-6xl leading-[1.12]">
            Prepare for incoming storms with{" "}
            <span className="bg-gradient-to-r from-sky-600 via-teal-500 to-cyan-500 bg-clip-text text-transparent">
              AI &amp; physics-based
            </span>{" "}
            forecasting
          </h1>

          {/* Centered Subtitle */}
          <p className="mx-auto mb-8 max-w-2xl text-[1.05rem] leading-relaxed text-slate-600 dark:text-slate-300 sm:text-[1.12rem] font-medium">
            Simulate hurricane landfall tracks, forecast electric grid outages with trained XGBoost models, identify high-risk flood zones, and coordinate emergency shelters across coastal and inland counties.
          </p>

          {/* Centered Ask Box */}
          <CenteredAskBox onAsk={onAsk} />
        </div>
      </div>

      {error && (
        <div className="mx-auto my-6 max-w-4xl rounded-xl border border-red-200 bg-bad-bg p-4 text-[0.9rem] text-bad-text font-medium flex items-center gap-3" role="alert">
          <span className="size-2 rounded-full bg-red-500 animate-pulse" />
          <span>{error}</span>
        </div>
      )}

      {/* Live Radar & Operations Console */}
      <LiveFeedConsole onOpenScenario={onOpen} />

      {/* Scenario Grid Header & Filter */}
      <div className="mt-14 mb-6 flex flex-wrap items-center justify-between gap-4">
        <div>
          <h2 className="font-heading text-xl sm:text-2xl font-bold tracking-tight text-navy">
            Operational County Scenarios
          </h2>
          <p className="text-[0.85rem] text-muted">
            Select an active storm scenario to inspect predictions, interactive maps, and resource plans.
          </p>
        </div>

        {/* Filter Pills */}
        <div className="flex items-center gap-1.5 rounded-xl border border-line bg-surface p-1 shadow-xs">
          <button
            type="button"
            onClick={() => setFilter("all")}
            className={`cursor-pointer rounded-lg px-3 py-1 text-[0.78rem] font-semibold transition-all ${
              filter === "all" ? "bg-accent text-white shadow-xs" : "text-muted hover:text-ink"
            }`}
          >
            All ({(agents ?? []).length})
          </button>
          <button
            type="button"
            onClick={() => setFilter("hurricane")}
            className={`cursor-pointer rounded-lg px-3 py-1 text-[0.78rem] font-semibold transition-all ${
              filter === "hurricane" ? "bg-accent text-white shadow-xs" : "text-muted hover:text-ink"
            }`}
          >
            Hurricanes ({hurricaneAgents.length})
          </button>
          <button
            type="button"
            onClick={() => setFilter("winter")}
            className={`cursor-pointer rounded-lg px-3 py-1 text-[0.78rem] font-semibold transition-all ${
              filter === "winter" ? "bg-accent text-white shadow-xs" : "text-muted hover:text-ink"
            }`}
          >
            Winter Storm
          </button>
        </div>
      </div>

      {/* Grid of Scenarios */}
      <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3">
        {filteredAgents.map((a) => {
          const broken = String(a.status ?? "").startsWith("error");
          const isHurricane = a.hazard === "hurricane";

          return (
            <button
              key={a.id}
              type="button"
              disabled={broken}
              onClick={() => onOpen(a.id)}
              className="group relative flex cursor-pointer flex-col overflow-hidden rounded-3xl border border-line bg-surface p-0 text-left shadow-md transition-all duration-300 hover:-translate-y-1 hover:border-sky-400 dark:hover:border-sky-400 hover:shadow-xl disabled:cursor-not-allowed disabled:opacity-60"
            >
              {/* Top Accent Gradient Bar */}
              <div
                className={`h-2.5 w-full ${
                  isHurricane
                    ? "bg-gradient-to-r from-sky-500 via-teal-400 to-cyan-300"
                    : "bg-gradient-to-r from-blue-600 via-indigo-500 to-sky-400"
                }`}
              />

              <div className="flex flex-1 flex-col p-6">
                {/* Top Badge & Hazard Icon */}
                <div className="mb-3 flex items-center justify-between gap-2">
                  <div className="inline-flex items-center gap-1.5 rounded-lg bg-sky-50 dark:bg-sky-950/60 px-2.5 py-1 text-[0.7rem] font-bold uppercase tracking-wider text-accent-dark dark:text-sky-300">
                    {isHurricane ? <HurricaneIcon /> : <SnowflakeIcon />}
                    <span>{isHurricane ? "Hurricane" : "Winter Storm"}</span>
                  </div>

                  <span className={`rounded-full px-2.5 py-0.5 text-[0.68rem] font-bold uppercase tracking-wider ${
                    broken
                      ? "bg-red-100 text-red-700"
                      : isHurricane
                      ? "bg-teal-50 dark:bg-teal-950/80 text-teal-800 dark:text-teal-300 border border-teal-200/50 dark:border-teal-800"
                      : "bg-blue-50 dark:bg-blue-950/80 text-blue-800 dark:text-blue-300 border border-blue-200/50 dark:border-blue-800"
                  }`}>
                    {broken ? "Offline" : isHurricane ? `Replay: ${a.replay}` : "Live Grid"}
                  </span>
                </div>

                {/* County Name */}
                <h3 className="font-heading text-xl font-bold text-navy group-hover:text-accent transition-colors">
                  {a.county ?? a.name}
                  {a.state ? <span className="text-muted font-medium text-base">, {a.state}</span> : ""}
                </h3>

                {/* Subtitle / Context */}
                <p className="mt-1 text-[0.82rem] text-muted leading-relaxed">
                  {isHurricane
                    ? `Landfall simulation calibrated against Hurricane ${a.replay}`
                    : "Multi-district freeze, power outage & tree damage response"}
                </p>

                {/* Key Metrics Pills */}
                <div className="mt-4 flex flex-wrap gap-2 pt-2 border-t border-slate-100 dark:border-slate-800">
                  {isHurricane ? (
                    <>
                      <div className="flex-1 rounded-xl bg-slate-50 dark:bg-slate-800/60 p-2.5 text-center">
                        <div className="text-[0.68rem] font-bold uppercase text-muted">Past Storms</div>
                        <div className="text-sm font-extrabold text-navy">{fmt(a.storms)}</div>
                      </div>
                      <div className="flex-1 rounded-xl bg-slate-50 dark:bg-slate-800/60 p-2.5 text-center">
                        <div className="text-[0.68rem] font-bold uppercase text-muted">Shelters</div>
                        <div className="text-sm font-extrabold text-navy">{fmt(a.shelters)}</div>
                      </div>
                    </>
                  ) : (
                    <div className="w-full rounded-xl bg-slate-50 dark:bg-slate-800/60 p-2.5">
                      <div className="text-[0.72rem] font-semibold text-navy">Dallas Winter Response</div>
                      <div className="text-[0.68rem] text-muted">Outage predictions • Tree crews • 311 history</div>
                    </div>
                  )}
                </div>

                {/* Action CTA */}
                <div className="mt-5 flex items-center justify-between pt-3 border-t border-slate-100/80 dark:border-slate-800 text-[0.84rem] font-semibold text-accent group-hover:text-accent-dark">
                  <span>Open Operations Dashboard</span>
                  <span className="transition-transform group-hover:translate-x-1" aria-hidden="true">&rarr;</span>
                </div>
              </div>
            </button>
          );
        })}
      </div>

      {/* Trust & Scientific Grounding Banner */}
      {hurricaneAgents.length > 0 && (
        <div className="mt-12 rounded-3xl border border-sky-100 dark:border-sky-500/20 bg-gradient-to-r from-sky-50/70 via-teal-50/40 to-white dark:from-slate-900 dark:via-slate-900/90 dark:to-slate-950 p-6 sm:p-8 shadow-sm">
          <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
            <div>
              <span className="text-[0.72rem] font-bold uppercase tracking-wider text-accent">Grounded Data Foundations</span>
              <h4 className="font-heading text-lg font-bold text-navy mt-0.5">
                Trained &amp; Validated on {fmt(totalStorms)} Historical Hurricanes &amp; {fmt(totalShelters)} FEMA Shelters
              </h4>
              <p className="mt-1 text-[0.85rem] text-muted max-w-2xl">
                Predictions are continuously grounded in NOAA ATCF, HURDAT2 archive, EAGLE-I power telemetry, CDC Social Vulnerability Index (SVI), and FEMA shelter databases.
              </p>
            </div>
            <div className="flex items-center gap-2 text-xs font-semibold text-sky-800 dark:text-sky-300">
              <span className="rounded-lg bg-white/80 dark:bg-slate-800 border border-sky-200/80 dark:border-slate-700 px-3 py-1.5 shadow-2xs">NOAA ATCF</span>
              <span className="rounded-lg bg-white/80 dark:bg-slate-800 border border-sky-200/80 dark:border-slate-700 px-3 py-1.5 shadow-2xs">HURDAT2</span>
              <span className="rounded-lg bg-white/80 dark:bg-slate-800 border border-sky-200/80 dark:border-slate-700 px-3 py-1.5 shadow-2xs">EAGLE-I</span>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}


