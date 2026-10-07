import { RISK_CLASSES, getRiskLevel, getRiskLabel } from "../utils/riskTier.js";
import { BIG, CARD, LABEL, NOTE, fmt } from "../dallas/format.js";

export const STATUS = {
  replay: { label: "Replay of Historical Landfall", className: "bg-sky-50 text-sky-800 border border-sky-200/60" },
  live: { label: "Live NOAA/NHC Advisory", className: "bg-red-50 text-red-700 border border-red-200/60 animate-pulse" },
  scenario: { label: "Deterministic Planning Scenario", className: "bg-slate-100 text-slate-700 border border-slate-200" },
};

const KT_TO_MPH = 1.15078;
export const ktToMph = (kt) => (kt == null ? null : kt * KT_TO_MPH);

export function fmtUTC(iso) {
  if (!iso) return "—";
  return `${new Date(iso).toLocaleString("en-US", {
    month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "UTC",
  })} UTC`;
}

export function addHoursISO(iso, hours) {
  if (!iso || hours == null) return null;
  return new Date(new Date(iso).getTime() + hours * 3600_000).toISOString();
}

export function Metric({ label, value, note, icon }) {
  return (
    <div className="rounded-2xl border border-line bg-surface p-5 ocean-card-shadow transition-all duration-200 hover:border-sky-300">
      <div className="flex items-center justify-between gap-2">
        <span className="text-[0.7rem] font-bold uppercase tracking-[0.06em] text-accent">{label}</span>
        {icon && <span className="text-sky-500">{icon}</span>}
      </div>
      <div className="mt-1 font-heading text-2xl sm:text-[1.85rem] font-extrabold tracking-tight text-navy leading-tight">{value}</div>
      {note && <div className="mt-1 text-[0.82rem] text-muted leading-relaxed">{note}</div>}
    </div>
  );
}

export function StormContextHeader({ alert, county, state }) {
  const status = STATUS[alert.kind] ?? STATUS.replay;
  return (
    <div className="mb-6 rounded-2xl border border-sky-100 bg-gradient-to-r from-sky-50/80 via-white to-sky-50/40 p-5 sm:p-6 shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2.5">
          <span className={`rounded-full px-3 py-1 text-[0.72rem] font-bold uppercase tracking-wider ${status.className}`}>
            {status.label}
          </span>
          <h2 className="font-heading text-xl sm:text-2xl font-extrabold text-navy">
            Hurricane {alert.storm_name} <span className="text-sky-400 font-light mx-1">→</span> {county}{state ? `, ${state}` : ""}
          </h2>
        </div>
      </div>
      <p className="mt-2 text-[0.92rem] font-medium text-slate-700 leading-snug">
        {alert.headline.replace(/^REPLAY: /, "")}
      </p>
      {alert.note && <p className="mt-1 text-[0.8rem] text-muted">{alert.note}</p>}
    </div>
  );
}

export function ImpactPanel({ impact }) {
  if (impact.error) {
    return (
      <div className="rounded-xl border border-red-200 bg-bad-bg p-4 text-[0.88rem] text-bad-text font-medium" role="alert">
        {impact.error}
      </div>
    );
  }
  const level = getRiskLevel(impact.risk_tier);
  const p = impact.pct_customers_out;
  const c = impact.customers_out;
  const sk = impact.model_skill;

  const skillBits = [
    sk.mae_median != null && `median error ${fmt(sk.mae_median)} points`,
    sk.coverage_pct != null && `${fmt(sk.coverage_pct)}% coverage interval`,
    sk.recall_hardest_hit_pct != null && `detected ${fmt(sk.recall_hardest_hit_pct)}% of hardest-hit counties`,
  ].filter(Boolean).join("; ");

  return (
    <div className="rounded-2xl border border-line bg-surface p-6 ocean-card-shadow">
      <div className="flex flex-wrap items-center justify-between gap-3 pb-4 border-b border-slate-100">
        <div className="flex items-center gap-2.5">
          <span className="text-xs font-bold uppercase tracking-wider text-muted">Predicted Grid Severity:</span>
          <span className={`rounded-full px-3 py-1 text-[0.75rem] font-extrabold uppercase tracking-wider ${RISK_CLASSES[level].badge}`}>
            {getRiskLabel(impact.risk_tier)} Risk
          </span>
        </div>
        {impact.model_version && (
          <span className="rounded-md border border-slate-200 bg-slate-50 px-2.5 py-1 text-[0.7rem] font-semibold text-slate-600">
            Model: {impact.model_version}
          </span>
        )}
      </div>

      <div className="mt-5 grid grid-cols-1 gap-6 sm:grid-cols-2">
        <div className="rounded-xl bg-slate-50/80 p-4 border border-slate-100">
          <div className="text-[0.72rem] font-bold uppercase tracking-wider text-accent">Customers Without Power (Peak)</div>
          <div className="mt-1 font-heading text-3xl font-extrabold text-navy">
            {fmt(c.low)} – {fmt(c.high)}
          </div>
          <div className="mt-1 text-[0.82rem] text-muted">
            Median estimate: <strong className="text-navy">{fmt(c.median)}</strong> out of {fmt(impact.customers_served)} total customers
          </div>
        </div>

        <div className="rounded-xl bg-slate-50/80 p-4 border border-slate-100">
          <div className="text-[0.72rem] font-bold uppercase tracking-wider text-accent">Share of Customers Affected</div>
          <div className="mt-1 font-heading text-3xl font-extrabold text-navy">
            {fmt(p.low)}% – {fmt(p.high)}%
          </div>
          <div className="mt-1 text-[0.82rem] text-muted">
            Median outage rate: <strong className="text-navy">{fmt(p.median)}%</strong>
          </div>
        </div>
      </div>

      <div className="mt-5">
        <div className="text-[0.72rem] font-bold uppercase tracking-wider text-slate-500">Key Prediction Drivers</div>
        <ul className="mt-2 space-y-1.5 pl-4 list-disc text-[0.85rem] text-slate-700 marker:text-sky-500">
          {impact.why.map((w) => <li key={w}>{w}</li>)}
        </ul>
      </div>

      {skillBits && (
        <div className="mt-4 rounded-lg bg-sky-50/60 p-3 text-[0.78rem] text-sky-900 border border-sky-100/80">
          <strong>Validation skill ({sk.tested_on}):</strong> {skillBits}. {impact.caveat}
        </div>
      )}

      {impact.calibration?.severe_uncertainty_caveat && (
        <p className="mt-3 rounded-lg bg-amber-50 p-3 text-[0.8rem] text-amber-900 border border-amber-200/60">
          ⚠️ {impact.calibration.severe_uncertainty_caveat}
        </p>
      )}
    </div>
  );
}

export function getForecastInputs(alert, impact) {
  const inputs = !impact.error ? impact.inputs : null;
  return {
    windKt: inputs ? inputs.forecast_wind_at_county_kt : alert.forecast_wind_at_county_kt,
    distNm: inputs ? inputs.forecast_closest_nm : alert.forecast_closest_nm,
    rightOfTrack: inputs ? inputs.right_of_track : alert.right_of_track,
    fromModel: Boolean(inputs),
  };
}

export function toRiskLocations(overview) {
  const { alert, impact, county, fips } = overview;
  if (impact.error) {
    return [{
      id: fips, name: county, risk_level: null, predicted_outage: null, prediction_range: null,
      customers_out: null, risk_drivers: [], forecast_horizon_h: alert.lead_time_h, source: null,
      error: impact.error,
    }];
  }
  return [{
    id: fips, name: county, risk_level: impact.risk_tier, predicted_outage: impact.pct_customers_out.median,
    prediction_range: impact.pct_customers_out, customers_out: impact.customers_out,
    risk_drivers: impact.why, forecast_horizon_h: alert.lead_time_h, source: impact.source, error: null,
  }];
}
