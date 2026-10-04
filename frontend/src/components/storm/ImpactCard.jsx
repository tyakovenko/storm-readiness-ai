import { getRiskLevel, getRiskLabel, RISK_CLASSES } from "../../utils/riskTier.js";

export default function ImpactCard({ county, onViewDetails }) {
  const level = getRiskLevel(county.risk_tier);
  const label = getRiskLabel(county.risk_tier);
  const q = county.pct_customers_out;

  return (
    <article
      className={`flex min-w-[220px] flex-[1_1_0] flex-col gap-2.5 rounded-md border border-l-[3px] border-line bg-surface px-4 py-3.5 ${RISK_CLASSES[level].borderLeft}`}
    >
      <span
        className={`self-start rounded px-2 py-[3px] text-[0.68rem] font-bold uppercase tracking-[0.4px] ${RISK_CLASSES[level].badge}`}
      >
        {label}
      </span>

      <h4 className="text-base font-bold text-navy">
        {county.name}, {county.state}
      </h4>

      <div className="flex flex-col gap-0.5">
        <span className="text-2xl font-bold leading-[1.1] text-navy">{q.median}%</span>
        <span className="text-[0.78rem] text-muted">Predicted customer outage</span>
        {/* Far from landfall the forecast is uncertain, so the range always goes with the median. */}
        <span className="text-[0.78rem] text-muted">Range {q.low}–{q.high}%</span>
      </div>

      <div className="flex flex-col gap-0.5 text-[0.78rem]">
        <span className="text-[0.66rem] font-semibold uppercase tracking-[0.4px] text-muted">Primary drivers</span>
        <span className="text-ink">{county.why.join(" • ")}</span>
      </div>

      <button
        type="button"
        className="mt-auto cursor-pointer self-start bg-transparent p-0 text-[0.82rem] font-semibold text-accent hover:text-accent-dark hover:underline"
        onClick={onViewDetails}
      >
        View details &rarr;
      </button>
    </article>
  );
}
