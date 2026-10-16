import { PAGE, PageTitle } from "../components/Page.jsx";
import SectionHeading from "../components/SectionHeading.jsx";
import RiskBadge from "../components/RiskBadge.jsx";
import { LABEL, NOTE, fmt } from "../dallas/format.js";
import { getRiskLevel, RISK_HEX } from "../utils/riskTier.js";
import CountyMap from "./CountyMap.jsx";
import {
  Metric, StormContextHeader, ImpactPanel, ktToMph, fmtUTC, getForecastInputs,
} from "./shared.jsx";

// Storm Overview for one hurricane county: a concise emergency-management dashboard -- storm
// identity + horizon, the storm's regional picture, this county's own prediction, the forecast
// track, Ask AI, and (collapsed, since they're reference detail rather than the operational
// picture) similar past storms / risk factors / sources. Everything comes from the existing
// /api/agents/{id}/overview and /api/storms/{slug}/overview responses -- no new data or calcs.

// Local, tighter-than-shared-CARD card for this page only (~20-25% less padding) -- the shared
// CARD in dallas/format.js is used by Dallas/Resource Planner/legacy Risk Map and stays untouched.
const TCARD = "rounded-md border border-line bg-surface px-3 py-2.5";
const TVALUE = "text-xl font-bold leading-[1.1] text-navy";

const OVERVIEW_ASK_PROMPTS = [
  "Explain this forecast",
  "Explain this outage prediction",
  "How reliable is this estimate?",
  "Compare with similar storms",
];

// Native <details>/<summary> -- keyboard-operable and exposed to assistive tech with no extra
// library, for the reference sections that don't need to be visible by default.
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

// A small circular icon badge for the top metric row -- plain Unicode glyphs, no icon library.
function IconMetric({ icon, tone, label, value, note }) {
  return (
    <div className={`${TCARD} flex items-start gap-2.5`}>
      <span className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-[1rem] ${tone}`} aria-hidden="true">
        {icon}
      </span>
      <div className="min-w-0">
        <div className={LABEL}>{label}</div>
        <div className={TVALUE}>{value}</div>
        {note && <div className={NOTE}>{note}</div>}
      </div>
    </div>
  );
}

// The shared horizon control, boxed as its own card -- Risk Map and Storm Overview drive and
// reflect the same state (storm_view.county_impact_at_horizon), so switching here updates both
// screens identically. Never invents a horizon this storm's advisory doesn't actually have.
function HorizonCard({ stormOverview, impact, onSelectHorizon }) {
  const horizons = stormOverview?.available_horizons_h;
  const activeHorizon = impact.horizon_h ?? stormOverview?.horizon_h ?? null;
  const validTime = impact.forecast_valid_time_utc ? fmtUTC(impact.forecast_valid_time_utc) : null;
  if (activeHorizon == null) return null;
  return (
    <div className={`${TCARD} shrink-0`}>
      <div className={LABEL}>Forecast valid time <span className="font-normal normal-case text-muted">(after advisory)</span></div>
      <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
        {horizons?.length && onSelectHorizon ? (
          horizons.map((h) => (
            <button key={h} type="button" onClick={() => onSelectHorizon(h)}
              className={`cursor-pointer rounded-full px-3 py-1 text-[0.8rem] font-semibold ${
                h === activeHorizon ? "bg-accent text-white" : "border border-line text-muted hover:text-ink"
              }`}>
              +{h}h
            </button>
          ))
        ) : (
          <span className="rounded-full bg-accent px-3 py-1 text-[0.8rem] font-semibold text-white">+{activeHorizon}h</span>
        )}
        {validTime && <span className="ml-1 border-l border-line pl-2.5 text-[0.8rem] font-semibold text-navy">{validTime}</span>}
      </div>
    </div>
  );
}

// Storm-wide regional picture as compact horizontal bars -- reuses the exact multi-county
// prediction Risk Map already fetches (GET /api/storms/{slug}/overview, same trained model),
// never a second model call or an invented number.
function RegionalImpactSummary({ stormOverview, homeFips, onOpenCounty }) {
  if (!stormOverview) return <p className={`${NOTE} mt-2`}>Loading regional picture…</p>;
  const sorted = [...stormOverview.counties].sort((a, b) => b.pct_customers_out.median - a.pct_customers_out.median);
  const max = Math.max(...sorted.map((c) => c.pct_customers_out.median), 1);
  return (
    <section className={`${TCARD} h-full`}>
      <SectionHeading title="Regional impact" subtitle={`Top affected counties at +${stormOverview.horizon_h}h (same model as county page)`} />
      <ul className="mt-2.5 flex flex-col gap-1.5">
        {sorted.map((c) => {
          const level = getRiskLevel(c.risk_tier);
          const selected = c.fips === homeFips;
          const widthPct = Math.max(4, (c.pct_customers_out.median / max) * 100);
          return (
            <li key={c.fips}>
              <button type="button" disabled={!onOpenCounty} onClick={() => onOpenCounty?.(c.fips)}
                className={`group flex w-full items-center gap-2.5 rounded px-1.5 py-1 text-left disabled:cursor-default enabled:cursor-pointer enabled:hover:bg-canvas ${selected ? "bg-[#e8f0f8]" : ""}`}>
                <span className="w-32 shrink-0 truncate text-[0.8rem] font-semibold text-navy group-enabled:group-hover:text-accent">
                  {c.name}{selected && " (selected)"}
                </span>
                <span className="relative h-3 flex-1 rounded-full bg-[#eef1f5]">
                  <span className="absolute inset-y-0 left-0 rounded-full" style={{ width: `${widthPct}%`, backgroundColor: RISK_HEX[level] }} />
                </span>
                <span className="w-11 shrink-0 text-right text-[0.8rem] font-bold text-navy">{fmt(c.pct_customers_out.median)}%</span>
                <RiskBadge level={level} />
              </button>
            </li>
          );
        })}
      </ul>
      <p className={`${NOTE} mt-2`}>Same trained model as each county's own page, read at this storm's +{stormOverview.horizon_h}h forecast point.</p>
    </section>
  );
}

export default function HurricaneOverview({ overview, agent, onAsk, stormOverview, onSelectHorizon, onOpenCounty }) {
  const { alert, impact, similar, geo, shelters, profile, county, enso } = overview;
  const { windKt, distNm, rightOfTrack } = getForecastInputs(alert, impact);
  const windMethod = impact.inputs?.wind_estimate_method;
  const level = getRiskLevel(impact.risk_tier);

  const sk = impact.model_skill ?? {};
  const skillBits = [
    sk.mae_median != null && `median error ${fmt(sk.mae_median)} points`,
    sk.coverage_pct != null && `${fmt(sk.coverage_pct)}% of outcomes inside the range`,
    sk.recall_hardest_hit_pct != null && `caught ${fmt(sk.recall_hardest_hit_pct)}% of hardest-hit counties (≥40% out)`,
  ].filter(Boolean).join("; ");

  return (
    <section className={PAGE}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          {/* StormContextHeader below already carries the storm name, county and replay badge --
              this title stays generic so the two headings don't repeat the same identity twice.
              Overview shows a short identity + description; the per-storm training-data detail
              that used to live in this note now lives in "Sources & trust" below instead. */}
          <PageTitle>Storm Overview</PageTitle>
          <StormContextHeader alert={alert} county={county} state={agent?.state}
            title={`Hurricane ${alert.storm_name}`}
            note="Real NHC forecast used to simulate pre-landfall emergency planning. Not a live storm." />
        </div>
        <HorizonCard stormOverview={stormOverview} impact={impact} onSelectHorizon={onSelectHorizon} />
      </div>

      <div className="mt-4 grid grid-cols-3 gap-2.5 max-[700px]:grid-cols-1">
        <IconMetric icon="📅" tone="bg-[#e8f0f8] text-accent" label="Advisory issued"
          value={fmtUTC(alert.advisory_init_utc)} note={`${alert.kind} advisory`} />
        <IconMetric icon="🌀" tone="bg-bad-bg text-bad-text" label="Peak intensity"
          value={`${fmt(alert.forecast_vmax_at_closest_kt)} kt`} note={`~${fmt(ktToMph(alert.forecast_vmax_at_closest_kt))} mph at closest approach`} />
        <IconMetric icon="💨" tone="bg-[#e8f0f8] text-accent" label="Wind at county"
          value={`${fmt(alert.forecast_wind_at_county_kt)} kt`} note={`~${fmt(ktToMph(alert.forecast_wind_at_county_kt))} mph, closest approach`} />
      </div>

      <div className="mt-4 grid grid-cols-[3fr_2fr] gap-3 max-[900px]:grid-cols-1">
        <RegionalImpactSummary stormOverview={stormOverview} homeFips={overview.fips} onOpenCounty={onOpenCounty} />

        <section className={`${TCARD} h-full`}>
          <SectionHeading title={`${county} — your county`} action={<RiskBadge level={level} />}
            subtitle={impact.source ?? "Impact model unavailable"} />
          <div className="mt-2.5"><ImpactPanel impact={impact} compact /></div>
        </section>
      </div>

      <div className="mt-4 grid grid-cols-[3fr_2fr] gap-3 max-[900px]:grid-cols-1">
        <section className={`${TCARD} h-full`}>
          <SectionHeading title="Forecast track" subtitle={`NHC forecast positions and intensity · ${county}: ${fmt(shelters.length)} FEMA shelters`} />
          <div className="mt-2.5"><CountyMap geo={geo} track={alert.forecast} shelters={shelters} trackLabel={alert.kind} height="h-[320px]" /></div>
        </section>

        <div className="flex flex-col gap-2.5">
          <section className={TCARD}>
            <SectionHeading title="Ask AI about this storm" subtitle="Get insights about this forecast, outage prediction, or similar storms" />
            <div className="mt-2.5 flex flex-wrap gap-1.5">
              {OVERVIEW_ASK_PROMPTS.map((q) => (
                <button key={q} type="button" onClick={() => onAsk?.(q)}
                  className="cursor-pointer rounded-full border border-line bg-surface px-2.5 py-1 text-[0.78rem] text-accent hover:border-accent">
                  {q}
                </button>
              ))}
            </div>
          </section>

          <Collapsible title="Most similar past storms" subtitle="Passed within 150 nm since 2015">
            <ol className="flex flex-col gap-2">
              {similar.storms.map((s) => (
                <li key={s.storm_id} className={TCARD}>
                  <div className="flex items-start justify-between gap-2">
                    <span className="font-bold text-navy">{s.name}</span>
                    <span className="rounded bg-[#e8ecf1] px-2 py-[2px] text-[0.72rem] font-semibold text-[#3b4452]">
                      similarity {fmt(s.similarity, 3)}
                    </span>
                  </div>
                  <div className={NOTE}>
                    {fmt(s.max_wind_kt_at_county)} kt at county • {fmt(s.dist_to_track_nm)} nm • {s.right_of_track ? "right" : "left"} side
                  </div>
                  <div className="text-[0.86rem] font-semibold text-navy">
                    Peak {fmt(s.peak_customers_out)} customers out ({fmt(s.peak_pct_customers, 1)}%)
                  </div>
                </li>
              ))}
            </ol>
            <p className={`${NOTE} mt-2`}>{similar.caveat}</p>
          </Collapsible>

          <Collapsible title="Why this location is at risk" subtitle="Forecast exposure, vulnerability and model methodology">
            {windMethod === "vmax_decay_fallback" && (
              <p className={`${NOTE} mb-2`}>
                Wind exposure below is a distance-decay estimate from peak storm intensity, not the forecast's own
                wind-radius field (not available for this replay) — treat it as approximate.
              </p>
            )}
            <div className="grid grid-cols-2 gap-2.5">
              <Metric label="Wind exposure" value={`${fmt(windKt)} kt`}
                note={`~${fmt(ktToMph(windKt))} mph • ${rightOfTrack ? "right (stronger) side" : "left (weaker) side"} of track`} />
              <Metric label="Storm proximity" value={`${fmt(distNm)} nm`} note="closest forecast distance to the county" />
              <Metric label="Hurricane risk score" value={fmt(profile.nri_hurricane_risk_score, 1)} note="FEMA NRI, 0–100" />
              <Metric label="Social vulnerability" value={fmt(profile.svi_overall, 2)} note="CDC/ATSDR SVI, 0–1" />
              <Metric label="Electric customers served" value={fmt(profile.customers)} />
              <Metric label="Tree canopy" value={`${fmt(profile.tree_canopy_pct, 1)}%`} note="USFS" />
              <Metric label="Population" value={fmt(profile.population)} />
              <Metric label="Climate context" value={`${enso.phase} (${enso.strength})`} note={`ONI ${fmt(enso.oni_c, 2)}, ${enso.season} ${enso.year}`} />
            </div>
            {!impact.error && skillBits && (
              <p className={`${NOTE} mt-2.5`}>Model skill on {sk.tested_on}: {skillBits}. {impact.caveat}</p>
            )}
          </Collapsible>

          <Collapsible title="Sources & trust" subtitle="Where this page's numbers come from">
            <ul className="list-disc pl-5 text-[0.82rem] text-muted">
              <li>Forecast: {alert.source}</li>
              {!impact.error && <li>Outage model: {impact.source}{impact.model_run ? ` (run ${impact.model_run})` : ""}</li>}
              <li>Similar storms: {similar.source}</li>
              <li>Climate context (ENSO): {enso.source}</li>
              <li>
                {alert.in_training_data
                  ? "This storm is in the impact model's training data, so its estimate is not an unseen test."
                  : "This storm is not in the impact model's training data."}
              </li>
            </ul>
            {stormOverview?.caveat && <p className={`${NOTE} mt-2.5`}>{stormOverview.caveat}</p>}
          </Collapsible>
        </div>
      </div>
    </section>
  );
}
