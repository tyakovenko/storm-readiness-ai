// Scenario layout extracted from the teammate's Live Operations dashboard (30ea26c).
import { useState } from "react";
import { fmt } from "../dallas/format.js";

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


export default function OperationalCountyScenarios({ agents, onOpen, hurricaneImage, winterImage }) {
  const [filter, setFilter] = useState("all");
  const all = agents ?? [];
  const hurricaneAgents = all.filter((a) => a.hazard === "hurricane");
  const filteredAgents = all.filter((a) => filter === "all" || a.hazard === filter);
  return <section aria-label="Operational County Scenarios">
      {/* Scenario Grid Header & Filter */}
      <div className="mb-6 flex flex-wrap items-center justify-between gap-4">
        <div>
          <h2 className="text-xl sm:text-2xl font-bold tracking-tight text-navy">
            Operational County Scenarios
          </h2>
          <p className="text-[0.85rem] text-muted">
            Select an storm scenario to inspect predictions, interactive maps, and resource plans.
          </p>
        </div>

        {/* Filter Pills */}
        <div className="flex flex-wrap items-center gap-1.5 rounded-xl border border-line bg-surface p-1 shadow-xs">
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
      <div className="grid auto-rows-fr grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {filteredAgents.map((a) => {
          const broken = String(a.status ?? "").startsWith("error");
          const isHurricane = a.hazard === "hurricane";

          return (
            <button
              key={a.id}
              type="button"
              disabled={broken}
              onClick={() => onOpen(a.id)}
              className="group relative flex h-full min-w-0 cursor-pointer flex-col overflow-hidden rounded-2xl border border-line bg-surface p-0 text-left shadow-sm transition-all duration-300 hover:-translate-y-1 hover:border-sky-400 dark:hover:border-sky-400 hover:shadow-md disabled:cursor-not-allowed disabled:opacity-60"
            >
              <img src={isHurricane ? hurricaneImage : winterImage}
                alt={isHurricane ? "Illustrative hurricane scenery, not a live satellite forecast" : "Illustrative winter storm scenery"}
                className="h-[110px] w-full shrink-0 object-cover" />
              {/* Top Accent Gradient Bar */}
              <div
                className={`h-1.5 w-full shrink-0 ${
                  isHurricane
                    ? "bg-gradient-to-r from-sky-500 via-teal-400 to-cyan-300"
                    : "bg-gradient-to-r from-blue-600 via-indigo-500 to-sky-400"
                }`}
              />

              <div className="flex min-w-0 flex-1 flex-col p-4">
                {/* Top Badge & Hazard Icon */}
                <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
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
                    {broken ? "Offline" : isHurricane ? (a.replay ? `Replay: ${a.replay}` : "Available scenario") : "Planning / alert"}
                  </span>
                </div>

                {/* County Name */}
                <h3 className="text-[1.05rem] leading-snug font-bold text-navy group-hover:text-accent transition-colors">
                  {a.county ?? a.name}
                  {a.state ? <span className="text-muted font-medium text-sm">, {a.state}</span> : ""}
                </h3>

                {/* Subtitle / Context */}
                <p className="mt-1 text-[0.78rem] text-muted leading-snug">
                  {isHurricane
                    ? (a.replay ? `Landfall simulation calibrated against Hurricane ${a.replay}` : "County hurricane preparedness scenario")
                    : "Multi-district freeze, power outage & tree damage response"}
                </p>

                {/* Key Metrics Pills */}
                <div className="mt-3 mb-3 flex flex-wrap gap-2 pt-2 border-t border-slate-100 dark:border-slate-800">
                  {isHurricane ? (
                    <>
                      <div className="flex-1 rounded-xl bg-slate-50 dark:bg-slate-800/60 p-2 text-center">
                        <div className="text-[0.68rem] font-bold uppercase text-muted">Past Storms</div>
                        <div className="text-sm font-extrabold text-navy">{fmt(a.storms)}</div>
                      </div>
                      <div className="flex-1 rounded-xl bg-slate-50 dark:bg-slate-800/60 p-2 text-center">
                        <div className="text-[0.68rem] font-bold uppercase text-muted">Shelters</div>
                        <div className="text-sm font-extrabold text-navy">{fmt(a.shelters)}</div>
                      </div>
                    </>
                  ) : (
                    <div className="w-full rounded-xl bg-slate-50 dark:bg-slate-800/60 p-2">
                      <div className="text-[0.72rem] font-semibold text-navy">Dallas Winter Response</div>
                      <div className="text-[0.68rem] text-muted">Outage predictions • Tree crews • 311 history</div>
                    </div>
                  )}
                </div>

                {/* Action CTA */}
                <div className="mt-auto flex items-center justify-between gap-2 pt-2 border-t border-slate-100/80 dark:border-slate-800 text-[0.78rem] font-semibold text-accent group-hover:text-accent-dark">
                  <span>Open Operations Dashboard</span>
                  <span className="transition-transform group-hover:translate-x-1" aria-hidden="true">&rarr;</span>
                </div>
              </div>
            </button>
          );
        })}
      </div>



    {agents && filteredAgents.length === 0 && <p>No county scenarios available for this filter.</p>}
  </section>;
}
