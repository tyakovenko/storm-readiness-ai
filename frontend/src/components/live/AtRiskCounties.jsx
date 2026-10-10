// Counties the trained outage model flags along each live storm's NHC forecast track, with the
// resources each county has (shelters, hospitals, fire departments) and how past storms hit it.
import RiskBadge from "../RiskBadge.jsx";
import { getRiskLevel, RISK_CLASSES } from "../../utils/riskTier.js";
import { categoryFor, classificationLabel } from "./liveStorms.js";

const n = (v) => (v == null ? "—" : Math.round(Number(v)).toLocaleString("en-US"));
const pct = (v) => `${Number(v).toFixed(Number(v) < 10 ? 1 : 0)}%`;
const utc = (iso) => new Date(iso).toLocaleString("en-US", { weekday: "short", hour: "numeric", timeZone: "UTC", timeZoneName: "short" });

function Stat({ label, value, sub }) {
  return (
    <div className="min-w-0 rounded-xl border border-slate-200 bg-slate-100 p-2.5">
      <div className="text-[0.62rem] font-bold uppercase tracking-wide text-muted">{label}</div>
      <div className="text-sm font-extrabold text-navy">{value}</div>
      {sub && <div className="text-[0.68rem] leading-snug text-muted">{sub}</div>}
    </div>
  );
}

function CountyCard({ c, agentIds, onOpenAgent }) {
  const level = getRiskLevel(c.risk_tier);
  const { shelters: sh, hospitals: ho, fire: fi, history: hi } = c;
  const canOpen = c.pack_slug && agentIds.has(c.pack_slug);
  return (
    <article className={`flex min-w-0 flex-col gap-3 rounded-2xl border border-line border-l-4 bg-surface p-4 shadow-xs ${RISK_CLASSES[level].borderLeft}`}>
      <header className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h4 className="truncate text-[1.02rem] font-bold text-navy">{c.name}<span className="text-sm font-medium text-muted">, {c.state}</span></h4>
          <p className="text-[0.72rem] text-muted">
            {c.distance_to_track_nm} nm from track · closest {utc(c.closest_forecast_utc)} at {n(c.forecast_wind_kt_at_closest)} kt
          </p>
        </div>
        <RiskBadge level={level} />
      </header>

      <div>
        <div className="text-[0.62rem] font-bold uppercase tracking-wide text-muted">Predicted customers without power</div>
        <div className="flex flex-wrap items-baseline gap-x-2">
          <span className="text-2xl font-extrabold text-navy">~{n(c.customers_out.median)}</span>
          <span className="text-xs text-muted">
            {pct(c.pct_customers_out.median)} of {n(c.customers_served)} · range {n(c.customers_out.low)}–{n(c.customers_out.high)}
          </span>
        </div>
        <div className="text-[0.72rem] text-muted">Est. utility trucks: <strong className="text-ink">{n(c.trucks_needed.median)}</strong> ({n(c.trucks_needed.low)}–{n(c.trucks_needed.high)})</div>
      </div>

      <div className="grid grid-cols-3 gap-2">
        <Stat label="Shelters" value={n(sh.count)} sub={`${n(sh.evacuation_capacity)} beds · ${n(sh.with_generator)} w/ generator`} />
        <Stat label="Hospitals" value={ho.count == null ? "—" : n(ho.count)} sub={ho.count == null ? ho.error : `${n(ho.with_emergency_dept)} with ER`} />
        <Stat label="Fire depts" value={fi.departments == null ? "—" : n(fi.departments)}
          sub={fi.departments == null ? fi.error : `${n(fi.stations)} stations · ${n(fi.career_firefighters)} career / ${n(fi.volunteer_firefighters)} vol.`} />
      </div>

      <div className="rounded-xl border border-line px-3 py-2 text-[0.75rem]">
        <div className="text-[0.62rem] font-bold uppercase tracking-wide text-muted">Storm history</div>
        {hi.worst.length ? (
          <div className="mt-0.5 text-ink">
            Worst past outages:{" "}
            {hi.worst.map((w, i) => (
              <span key={`${w.storm}-${w.year}`}>{i > 0 && " · "}<strong>{w.storm} {w.year}</strong> {pct(w.pct_customers_out)} ({n(w.peak_customers_out)})</span>
            ))}
          </div>
        ) : (
          <div className="mt-0.5 text-muted">No storm-driven outage of 1%+ on record (2014–2025).</div>
        )}
        <div className="text-muted">
          {n(hi.fema_declarations)} FEMA hurricane/tropical declarations
          {hi.recent_declarations[0] && ` · latest: ${hi.recent_declarations[0].title} (${hi.recent_declarations[0].year})`}
        </div>
      </div>

      <details className="group text-[0.75rem]">
        <summary className="cursor-pointer font-semibold text-accent">Facilities and model drivers</summary>
        <div className="mt-2 grid gap-3 sm:grid-cols-2">
          <div>
            <div className="font-bold text-navy">Hospitals</div>
            <ul className="mt-0.5 space-y-0.5 text-muted">
              {(ho.top ?? []).map((h) => <li key={h.name}>{h.name}, {h.city}{h.emergency_services ? " · ER" : ""}</li>)}
              {ho.count === 0 && <li>None listed by CMS</li>}
            </ul>
          </div>
          <div>
            <div className="font-bold text-navy">Largest fire departments</div>
            <ul className="mt-0.5 space-y-0.5 text-muted">
              {(fi.top ?? []).map((d) => <li key={d.name}>{d.name}: {n(d.stations)} stn · {n(d.career)} career / {n(d.volunteer)} vol.</li>)}
            </ul>
          </div>
          <div>
            <div className="font-bold text-navy">Largest shelters</div>
            <ul className="mt-0.5 space-y-0.5 text-muted">
              {sh.top.map((s, i) => <li key={`${s.name}-${i}`}>{s.name}, {s.city} · {n(s.evacuation_capacity)} beds{s.in_surge_zone ? " · surge zone" : ""}</li>)}
              {sh.count === 0 && <li>None in FEMA NSS</li>}
            </ul>
          </div>
          <div>
            <div className="font-bold text-navy">Why the model flags it</div>
            <ul className="mt-0.5 list-disc space-y-0.5 pl-4 text-muted">
              {c.why.map((w) => <li key={w}>{w}</li>)}
            </ul>
          </div>
        </div>
      </details>

      {canOpen && (
        <button type="button" onClick={() => onOpenAgent(c.pack_slug)} className="self-start text-xs font-bold text-accent hover:underline">
          Open county dashboard →
        </button>
      )}
    </article>
  );
}

export default function AtRiskCounties({ storms, risks, riskState, selectedId, onSelect, agents, onOpenAgent }) {
  const storm = storms.find((s) => s.storm_id === selectedId);
  const risk = risks[selectedId];
  const state = riskState[selectedId];
  const agentIds = new Set((agents ?? []).map((a) => a.id));
  if (!storms.length) return null;

  return (
    <section aria-label="Counties at risk from active storms" className="mt-10">
      <div className="mb-5 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h2 className="text-xl font-bold tracking-tight text-navy sm:text-2xl">Counties at Risk from Active Storms</h2>
          <p className="max-w-3xl text-[0.85rem] text-muted">
            US counties within {risk?.risk_radius_nm ?? 120} nm of each storm&apos;s NHC forecast track, scored by the trained outage model,
            with the shelters, hospitals and fire departments they have and how past storms hit them.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-1.5 rounded-xl border border-line bg-surface p-1 shadow-xs" role="tablist" aria-label="Storm">
          {storms.map((s) => {
            const r = risks[s.storm_id];
            return (
              <button
                key={s.storm_id}
                type="button"
                role="tab"
                aria-selected={s.storm_id === selectedId}
                onClick={() => onSelect(s.storm_id)}
                className={`inline-flex cursor-pointer items-center gap-1.5 rounded-lg px-3 py-1 text-[0.78rem] font-semibold transition-all ${
                  s.storm_id === selectedId ? "bg-accent text-white shadow-xs" : "text-muted hover:text-ink"
                }`}
              >
                <span className="size-2 rounded-full" style={{ background: categoryFor(s.intensity_kt).color }} />
                {s.name}
                <span className="opacity-75">({r ? r.counties.length : riskState[s.storm_id] === "error" ? "!" : "…"})</span>
              </button>
            );
          })}
        </div>
      </div>

      {storm && (
        <div role="status" className="mb-4 text-[0.8rem] text-muted">
          {state === "loading" && `Running the outage model for counties along ${storm.name}'s forecast track… the first run loads national data and can take up to a minute.`}
          {state === "error" && `Couldn't build ${storm.name}'s county view. No sample counties substituted.`}
          {risk && (risk.counties.length ? (
            <>
              <strong className="text-ink">{classificationLabel(storm.classification)} {storm.name}</strong>: top {risk.counties.length} of {risk.counties_evaluated} counties evaluated
              {" "}· ~{n(risk.counties.reduce((a, c) => a + c.customers_out.median, 0))} customers out (median)
              {" "}· NHC forecast {utc(risk.forecast_cycle_utc)}
              {risk.skipped.length > 0 && ` · ${risk.skipped.length} skipped (missing real county data)`}
            </>
          ) : (
            <><strong className="text-ink">{storm.name}</strong>: {risk.note}</>
          ))}
        </div>
      )}
      {risk?.caveats?.map((c) => <p key={c} className="mb-3 rounded-lg bg-risk-moderate-bg px-3 py-2 text-[0.78rem] text-risk-moderate">{c}</p>)}

      {risk?.counties?.length > 0 && (
        <>
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
            {risk.counties.map((c) => <CountyCard key={c.fips} c={c} agentIds={agentIds} onOpenAgent={onOpenAgent} />)}
          </div>
          <p className="mt-4 text-[0.72rem] text-muted">
            Sources: {risk.model_source}; {risk.sources.join("; ")}. {risk.assumptions.join(" ")}
          </p>
        </>
      )}
    </section>
  );
}
