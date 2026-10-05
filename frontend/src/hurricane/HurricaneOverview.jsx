import { PAGE, PageTitle } from "../components/Page.jsx";
import SectionHeading from "../components/SectionHeading.jsx";
import { RISK_CLASSES, getRiskLevel, getRiskLabel } from "../utils/riskTier.js";
import { BIG, CARD, LABEL, NOTE, fmt } from "../dallas/format.js";
import CountyMap from "./CountyMap.jsx";

// Hurricane Overview for one county agent: the replayed NHC forecast, the trained model's
// outage range (with its tested skill), past storms like it, and the county map.
// Everything comes from /api/agents/{id}/overview = the same tools the agent calls.

function Metric({ label, value, note }) {
  return (
    <div className={CARD}>
      <div className={LABEL}>{label}</div>
      <div className={BIG}>{value}</div>
      {note && <div className={NOTE}>{note}</div>}
    </div>
  );
}

function ImpactPanel({ impact }) {
  if (impact.error) {
    return <p className="rounded bg-bad-bg px-3 py-2 text-[0.85rem] text-bad-text" role="alert">{impact.error}</p>;
  }
  const level = getRiskLevel(impact.risk_tier);
  const p = impact.pct_customers_out;
  const c = impact.customers_out;
  const sk = impact.model_skill;
  return (
    <div className={`${CARD} border-l-[3px] ${RISK_CLASSES[level].borderLeft}`}>
      <span className={`rounded px-2 py-[3px] text-[0.68rem] font-bold uppercase tracking-[0.4px] ${RISK_CLASSES[level].badge}`}>
        {getRiskLabel(impact.risk_tier)}
      </span>
      <div className="mt-2 grid grid-cols-2 gap-4 max-[700px]:grid-cols-1">
        <div>
          <div className={LABEL}>Customers without power (peak)</div>
          <div className={BIG}>{fmt(p.low)}–{fmt(p.high)}%</div>
          <div className={NOTE}>median {fmt(p.median)}% • {fmt(c.low)}–{fmt(c.high)} of {fmt(impact.customers_served)} customers</div>
        </div>
        <div>
          <div className={LABEL}>Why</div>
          <ul className="mt-1 list-disc pl-4 text-[0.82rem]">{impact.why.map((w) => <li key={w}>{w}</li>)}</ul>
        </div>
      </div>
      <p className={`${NOTE} mt-2`}>
        Model skill on {sk.tested_on}: median error {fmt(sk.mae_median)} points; {fmt(sk.coverage_pct)}% of outcomes inside the range;
        caught {fmt(sk.recall_hardest_hit_pct)}% of hardest-hit counties (≥40% out). {impact.caveat}
      </p>
    </div>
  );
}

export default function HurricaneOverview({ overview }) {
  const { alert, impact, similar, geo, shelters, profile, county } = overview;
  return (
    <section className={PAGE}>
      <PageTitle>Storm Overview — {county}</PageTitle>
      <div className="mb-4 border-b border-line pb-4">
        <div className="flex flex-wrap items-center gap-2.5">
          <span className="rounded bg-warn-bg px-2 py-[3px] text-[0.72rem] font-bold uppercase tracking-[0.3px] text-warn-text">
            Replay of a real forecast
          </span>
          <h3 className="text-[1.3rem] font-bold text-navy">{alert.storm_name}</h3>
        </div>
        <p className="mt-1 text-[0.85rem] text-muted">{alert.headline.replace(/^REPLAY: /, "")}</p>
        <p className="mt-1 text-[0.78rem] text-muted">{alert.note}</p>
      </div>

      <div className="grid grid-cols-5 gap-3 max-[900px]:grid-cols-2">
        <Metric label="Lead time" value={`${fmt(alert.lead_time_h)} h`} note="before closest approach" />
        <Metric label="Closest approach" value={`${fmt(alert.forecast_closest_nm)} nm`} note="forecast center to county" />
        <Metric label="Wind at county" value={`${fmt(alert.forecast_wind_at_county_kt)} kt`} note="estimated from forecast" />
        <Metric label="Storm intensity" value={`${fmt(alert.forecast_vmax_at_closest_kt)} kt`} note="at closest approach" />
        <Metric label="Side of track" value={alert.right_of_track ? "Right" : "Left"} note={alert.right_of_track ? "stronger side" : "weaker side"} />
      </div>

      <section className="mt-6">
        <SectionHeading title="Expected power outages" subtitle={impact.source ?? "Impact model unavailable"} />
        <div className="mt-3.5"><ImpactPanel impact={impact} /></div>
      </section>

      <section className="mt-6 grid grid-cols-[3fr_2fr] gap-4 max-[900px]:grid-cols-1">
        <div>
          <SectionHeading title="Forecast track and shelters" subtitle={`${county}: ${fmt(shelters.length)} FEMA shelters`} />
          <div className="mt-3.5"><CountyMap geo={geo} track={alert.forecast} shelters={shelters} /></div>
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

      <section className="mt-6 grid grid-cols-5 gap-3 max-[900px]:grid-cols-2">
        <Metric label="Population" value={fmt(profile.population)} />
        <Metric label="Electric customers" value={fmt(profile.customers)} />
        <Metric label="NRI hurricane risk" value={fmt(profile.nri_hurricane_risk_score, 1)} note="FEMA, 0–100" />
        <Metric label="Social vulnerability" value={fmt(profile.svi_overall, 2)} note="CDC SVI, 0–1" />
        <Metric label="Tree canopy" value={`${fmt(profile.tree_canopy_pct, 1)}%`} note="USFS" />
      </section>
      <p className={`${NOTE} mt-6`}>Sources: {[alert.source, impact.source, similar.source].filter(Boolean).join(" • ")}</p>
    </section>
  );
}
