import { RISK_CLASSES, getRiskLevel, getRiskLabel } from "../utils/riskTier.js";
import { BIG, CARD, LABEL, NOTE, fmt } from "../dallas/format.js";

// Pieces shared by the hurricane county pages (Storm Overview, Risk Map): the storm-status badge,
// the impact panel, and small formatting helpers. Keeping these in one place means Risk Map shows
// the exact same prediction the Overview page shows — no second copy of the numbers or the rules.

// alert.kind is a real field (replay | live | scenario) — every badge reads it instead of assuming
// "replay", so a future live/scenario pack is never mislabeled.
export const STATUS = {
  replay: { label: "Replay of a real forecast", className: "bg-warn-bg text-warn-text" },
  live: { label: "Live NHC forecast", className: "bg-bad-bg text-bad-text" },
  scenario: { label: "Planning scenario", className: "bg-[#e8ecf1] text-[#3b4452]" },
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

export function Metric({ label, value, note }) {
  return (
    <div className={CARD}>
      <div className={LABEL}>{label}</div>
      <div className={BIG}>{value}</div>
      {note && <div className={NOTE}>{note}</div>}
    </div>
  );
}

// title/note: optional overrides for callers that want a shorter identity line or a shorter
// description (Storm Overview) -- left undefined, both default to the original full forms
// (Risk Map's call), so that screen's header is byte-for-byte unchanged.
export function StormContextHeader({ alert, county, state, title, note }) {
  const status = STATUS[alert.kind] ?? STATUS.replay;
  const headerTitle = title ?? (
    <>Hurricane {alert.storm_name} <span aria-hidden="true">→</span> {county}{state ? `, ${state}` : ""}</>
  );
  const noteText = note === undefined ? alert.note : note;
  return (
    <div className="mb-4 border-b border-line pb-4">
      <div className="flex flex-wrap items-center gap-2.5">
        <span className={`rounded px-2 py-[3px] text-[0.72rem] font-bold uppercase tracking-[0.3px] ${status.className}`}>
          {status.label}
        </span>
        <h3 className="text-[1.3rem] font-bold text-navy">{headerTitle}</h3>
      </div>
      <p className="mt-1 text-[0.85rem] text-muted">{alert.headline.replace(/^REPLAY: /, "")}</p>
      {noteText && <p className="mt-1 text-[0.78rem] text-muted">{noteText}</p>}
    </div>
  );
}

// compact (Phase 2B): a smaller rendering for the Storm Overview "your county" card -- median
// outage leads, then range and affected customers, caveats preserved; the model-skill/methodology
// text that the full panel shows inline instead lives in Storm Overview's "Why this location is at
// risk" section. The default (full) rendering is unchanged, so every other screen using this panel
// (e.g. the single-county Risk Map tab) looks exactly as before.
export function ImpactPanel({ impact, compact = false }) {
  if (impact.error) {
    return <p className="rounded bg-bad-bg px-3 py-2 text-[0.85rem] text-bad-text" role="alert">{impact.error}</p>;
  }
  const level = getRiskLevel(impact.risk_tier);
  const p = impact.pct_customers_out;
  const c = impact.customers_out;
  const sk = impact.model_skill;
  // Phase 2A: estimate_impact()'s default is the peak/closest-approach snapshot (fixed, not
  // horizon-selectable); registry.hurricane_overview()'s horizon_h path (storm_view.
  // county_impact_at_horizon) returns a specific forecast valid time instead -- label whichever
  // one this actually is rather than always saying "(peak)" for both.
  const validTimeLabel = impact.horizon_h != null ? `at +${impact.horizon_h}h` : "peak";
  // Phase 4: the skill fields present depend on which engine produced this (the new bundle's
  // metadata doesn't have a recall_hardest_hit_pct the way the legacy run did) -- shown
  // flexibly rather than assuming a fixed set of keys.
  const skillBits = [
    sk.mae_median != null && `median error ${fmt(sk.mae_median)} points`,
    sk.coverage_pct != null && `${fmt(sk.coverage_pct)}% of outcomes inside the range`,
    sk.recall_hardest_hit_pct != null && `caught ${fmt(sk.recall_hardest_hit_pct)}% of hardest-hit counties (≥40% out)`,
  ].filter(Boolean).join("; ");
  if (compact) {
    return (
      <div className={`rounded-md border border-line bg-surface px-3 py-2.5 border-l-[3px] ${RISK_CLASSES[level].borderLeft}`}>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <span className={`rounded px-2 py-[3px] text-[0.68rem] font-bold uppercase tracking-[0.4px] ${RISK_CLASSES[level].badge}`}>
            {getRiskLabel(impact.risk_tier)}
          </span>
          {impact.model_version && (
            <span className="rounded bg-[#e8ecf1] px-2 py-[2px] text-[0.68rem] font-semibold text-[#3b4452]">
              Model {impact.model_version}
            </span>
          )}
        </div>
        <div className="mt-2">
          <div className={LABEL}>Median predicted outage ({validTimeLabel})</div>
          <div className={BIG}>{fmt(p.median)}%</div>
          <div className={NOTE}>
            range {fmt(p.low)}–{fmt(p.high)}% • {fmt(c.median)} of {fmt(impact.customers_served)} customers affected
          </div>
        </div>
        {impact.calibration?.severe_uncertainty_caveat && (
          <p className="mt-1.5 rounded bg-warn-bg px-2 py-1.5 text-[0.78rem] text-warn-text">
            {impact.calibration.severe_uncertainty_caveat}
          </p>
        )}
      </div>
    );
  }
  return (
    <div className={`${CARD} border-l-[3px] ${RISK_CLASSES[level].borderLeft}`}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className={`rounded px-2 py-[3px] text-[0.68rem] font-bold uppercase tracking-[0.4px] ${RISK_CLASSES[level].badge}`}>
          {getRiskLabel(impact.risk_tier)}
        </span>
        {impact.model_version && (
          <span className="rounded bg-[#e8ecf1] px-2 py-[2px] text-[0.68rem] font-semibold text-[#3b4452]">
            Model {impact.model_version}
          </span>
        )}
      </div>
      <div className="mt-3 grid grid-cols-2 gap-4 max-[700px]:grid-cols-1">
        <div>
          <div className={LABEL}>Customers without power ({validTimeLabel})</div>
          <div className={BIG}>{fmt(c.low)}–{fmt(c.high)}</div>
          <div className={NOTE}>median {fmt(c.median)} of {fmt(impact.customers_served)} customers served</div>
        </div>
        <div>
          <div className={LABEL}>Share of customers out ({validTimeLabel})</div>
          <div className={BIG}>{fmt(p.low)}–{fmt(p.high)}%</div>
          <div className={NOTE}>median {fmt(p.median)}%</div>
        </div>
      </div>
      <div className="mt-3">
        <div className={LABEL}>Why</div>
        <ul className="mt-1 list-disc pl-4 text-[0.82rem]">{impact.why.map((w) => <li key={w}>{w}</li>)}</ul>
      </div>
      {skillBits && <p className={`${NOTE} mt-3`}>Model skill on {sk.tested_on}: {skillBits}. {impact.caveat}</p>}
      {impact.calibration?.severe_uncertainty_caveat && (
        <p className="mt-2 rounded bg-warn-bg px-2.5 py-2 text-[0.8rem] text-warn-text">
          {impact.calibration.severe_uncertainty_caveat}
        </p>
      )}
    </div>
  );
}

// The forecast exposure factors the model actually used (impact.inputs, when the model ran),
// falling back to the alert's own forecast fields if the model is unavailable. Used by both the
// Overview page's "why this is at risk" grid and the Risk Map's "model prediction drivers" section,
// so the two pages never disagree about what the model saw.
export function getForecastInputs(alert, impact) {
  const inputs = !impact.error ? impact.inputs : null;
  return {
    windKt: inputs ? inputs.forecast_wind_at_county_kt : alert.forecast_wind_at_county_kt,
    distNm: inputs ? inputs.forecast_closest_nm : alert.forecast_closest_nm,
    rightOfTrack: inputs ? inputs.right_of_track : alert.right_of_track,
    fromModel: Boolean(inputs),
  };
}

// Normalizes today's single-county overview into the shape a future forecast-aware, multi-location
// API is expected to return (location/risk_level/predicted_outage/prediction_range/risk_drivers/
// forecast_horizon — see the Risk Map build notes). The map and the priority list both render a
// *list* of these, so when that API exists and returns more than one entry, nothing here needs to
// change — only the length of this array grows. Today it is always exactly one real entry: the
// selected county. Never fabricate additional entries.
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
