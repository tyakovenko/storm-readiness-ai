import { PAGE, PageTitle } from "../components/Page.jsx";
import SectionHeading from "../components/SectionHeading.jsx";
import { CARD, LABEL, NOTE, fmt } from "../dallas/format.js";
import CountyMap from "./CountyMap.jsx";
import {
  Metric, StormContextHeader, ImpactPanel, STATUS, ktToMph, fmtUTC, addHoursISO, getForecastInputs,
} from "./shared.jsx";

// Storm Overview for one hurricane county: who/where/when, the replayed NHC forecast, the trained
// model's outage range (with its tested skill), why this county is exposed, past storms like it,
// and the map. Everything comes from /api/agents/{id}/overview = the same tools the agent calls.

// Phase 5: contextual Ask AI prompts for this page -- same panel as everywhere else (App.jsx's
// askWithQuestion), just handed a different starting question. Wording matches the intents
// backend/agent/hurricane_adk.py's mock composer actually recognizes (forecast/outage/
// uncertainty/historical), so clicking one gets the tailored answer, not the generic fallback.
const OVERVIEW_ASK_PROMPTS = [
  "Explain this forecast",
  "Explain this outage prediction",
  "How reliable is this estimate?",
  "Compare with similar storms",
];

// Phase 4: the forecast-aware model bundle genuinely supports 24h/48h/72h-lead-time predictions
// (it was trained and validated at exactly those three horizons — see model_skill.tested_on),
// but switching between them for a given county needs a second/third independent NHC advisory
// *cycle* selected from the raw ATCF a-deck archive, not just this one baked replay track. That
// archive is GCS-gated and isn't fetched by this app at request time, so there is only ever one
// real horizon available per replay: this one. The control stays inert rather than faking a
// switch — see backend/models/replay_snapshot.py for the exact limitation.
function HorizonControls({ activeLabel, leadTimeH }) {
  return (
    <div className="mt-3 flex flex-wrap items-center gap-2">
      <span className="text-[0.78rem] font-semibold text-muted">Forecast horizon:</span>
      <span className="rounded-full border border-accent bg-[#e8f0f8] px-3 py-1 text-[0.78rem] font-semibold text-accent">
        {activeLabel} ({fmt(leadTimeH)}h lead time)
      </span>
      {["24h", "48h", "72h"].map((h) => (
        <span key={h} title="Needs a second/third NHC advisory cycle from the raw ATCF archive, which this app doesn't fetch at request time"
          aria-disabled="true" className="cursor-not-allowed rounded-full border border-line px-3 py-1 text-[0.78rem] text-muted opacity-55">
          {h}
        </span>
      ))}
      <span className={NOTE}>
        The outage model is validated at 24h/48h/72h lead times, but switching horizons for this county needs
        the raw NHC advisory archive (not available without further data access) — this shows the one real
        advisory this replay has.
      </span>
    </div>
  );
}

// Why this location is at risk: forecast exposure (impact.inputs when the model ran) plus county
// vulnerability/exposure context (NRI, SVI, customers, tree canopy, population, ENSO).
function RiskFactorsSection({ alert, impact, profile, enso }) {
  const { windKt, distNm, rightOfTrack } = getForecastInputs(alert, impact);
  const windMethod = impact.inputs?.wind_estimate_method;
  return (
    <section className="mt-6">
      <SectionHeading title="Why this location is at risk" subtitle="Forecast exposure and county vulnerability behind the impact estimate" />
      {windMethod === "vmax_decay_fallback" && (
        <p className={`${NOTE} mb-2`}>
          Wind exposure below is a distance-decay estimate from peak storm intensity, not the forecast's own
          wind-radius field (not available for this replay) — treat it as approximate.
        </p>
      )}
      <div className="mt-3.5 grid grid-cols-4 gap-3 max-[900px]:grid-cols-2">
        <Metric label="Wind exposure" value={`${fmt(windKt)} kt`}
          note={`~${fmt(ktToMph(windKt))} mph • ${rightOfTrack ? "right (stronger) side" : "left (weaker) side"} of track`} />
        <Metric label="Storm proximity" value={`${fmt(distNm)} nm`} note="closest forecast distance to the county" />
        <Metric label="Hurricane risk score" value={fmt(profile.nri_hurricane_risk_score, 1)} note="FEMA National Risk Index, 0–100" />
        <Metric label="Social vulnerability" value={fmt(profile.svi_overall, 2)} note="CDC/ATSDR SVI, 0–1 (higher = more vulnerable)" />
        <Metric label="Electric customers served" value={fmt(profile.customers)} note="exposure base for the outage estimate" />
        <Metric label="Tree canopy" value={`${fmt(profile.tree_canopy_pct, 1)}%`} note="USFS — more canopy, more wind-driven outages" />
        <Metric label="Population" value={fmt(profile.population)} />
        <Metric label="Climate context" value={`${enso.phase} (${enso.strength})`} note={`ONI ${fmt(enso.oni_c, 2)}, ${enso.season} ${enso.year}`} />
      </div>
    </section>
  );
}

export default function HurricaneOverview({ overview, agent, onAsk }) {
  const { alert, impact, similar, geo, shelters, profile, county, enso } = overview;
  const status = STATUS[alert.kind] ?? STATUS.replay;
  const closestApproachUtc = addHoursISO(alert.advisory_init_utc, alert.lead_time_h);

  return (
    <section className={PAGE}>
      <PageTitle>Storm Overview — {county}{agent?.state ? `, ${agent.state}` : ""}</PageTitle>
      <StormContextHeader alert={alert} county={county} state={agent?.state} />

      <div className="grid grid-cols-6 gap-3 max-[900px]:grid-cols-2">
        <Metric label="Advisory issued" value={fmtUTC(alert.advisory_init_utc)} note={`${alert.kind} advisory`} />
        <Metric label="Lead time" value={`${fmt(alert.lead_time_h)} h`} note="before closest approach" />
        <Metric label="Expected closest approach" value={fmtUTC(closestApproachUtc)} note="advisory time + lead time" />
        <Metric label="Distance to county" value={`${fmt(alert.forecast_closest_nm)} nm`} note="forecast center to county" />
        <Metric label="Wind at county" value={`${fmt(alert.forecast_wind_at_county_kt)} kt`} note={`~${fmt(ktToMph(alert.forecast_wind_at_county_kt))} mph`} />
        <Metric label="Peak intensity" value={`${fmt(alert.forecast_vmax_at_closest_kt)} kt`} note={`~${fmt(ktToMph(alert.forecast_vmax_at_closest_kt))} mph at closest approach`} />
      </div>
      <HorizonControls activeLabel={status.label} leadTimeH={alert.lead_time_h} />

      <section className="mt-6">
        <SectionHeading title="Expected power outages" subtitle={impact.source ?? "Impact model unavailable"} />
        <div className="mt-3.5"><ImpactPanel impact={impact} /></div>
      </section>

      <section className="mt-6 grid grid-cols-[3fr_2fr] gap-4 max-[900px]:grid-cols-1">
        <div>
          <SectionHeading title="Forecast track and shelters" subtitle={`${county}: ${fmt(shelters.length)} FEMA shelters`} />
          <div className="mt-3.5">
            <CountyMap geo={geo} track={alert.forecast} shelters={shelters} trackLabel={alert.kind} height="h-[480px]" />
          </div>
        </div>
        <div>
          <SectionHeading title="Most similar past storms" subtitle="Passed within 150 nm since 2015, ranked by wind, distance and side" />
          <ol className="mt-3.5 flex flex-col gap-2.5">
            {similar.storms.map((s) => (
              <li key={s.storm_id} className={CARD}>
                <div className="flex items-start justify-between gap-2">
                  <span className="font-bold text-navy">{s.name}</span>
                  <span className="rounded bg-[#e8ecf1] px-2 py-[2px] text-[0.72rem] font-semibold text-[#3b4452]">
                    similarity {fmt(s.similarity, 3)}
                  </span>
                </div>
                <div className={NOTE}>
                  {fmt(s.max_wind_kt_at_county)} kt at county • {fmt(s.dist_to_track_nm)} nm • {s.right_of_track ? "right" : "left"} side
                </div>
                <div className="text-[0.88rem] font-semibold text-navy">
                  Peak {fmt(s.peak_customers_out)} customers out ({fmt(s.peak_pct_customers, 1)}%)
                </div>
              </li>
            ))}
          </ol>
          <p className={`${NOTE} mt-2`}>{similar.caveat}</p>
        </div>
      </section>

      <RiskFactorsSection alert={alert} impact={impact} profile={profile} enso={enso} />

      <section className="mt-6">
        <SectionHeading title="Ask AI about this storm" subtitle="Opens the same Ask AI panel, scoped to this storm and county" />
        <div className="mt-3 flex flex-wrap gap-1.5">
          {OVERVIEW_ASK_PROMPTS.map((q) => (
            <button key={q} type="button" onClick={() => onAsk?.(q)}
              className="cursor-pointer rounded-full border border-line bg-surface px-3 py-1.5 text-[0.8rem] text-accent hover:border-accent">
              {q}
            </button>
          ))}
        </div>
      </section>

      <section className="mt-6">
        <SectionHeading title="Sources & trust" subtitle="Where this page's numbers come from" />
        <ul className="mt-2 list-disc pl-5 text-[0.82rem] text-muted">
          <li>Forecast: {alert.source}</li>
          {!impact.error && <li>Outage model: {impact.source} (run {impact.model_run})</li>}
          <li>Similar storms: {similar.source}</li>
          <li>Climate context (ENSO): {enso.source}</li>
        </ul>
      </section>
    </section>
  );
}
