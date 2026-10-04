import ImpactCard from "./ImpactCard.jsx";
import SectionHeading from "../SectionHeading.jsx";
import { getRiskLevel } from "../../utils/riskTier.js";

// Summary row of the highest-impact counties. "View details" and "View Full
// Risk Map" jump to the Risk Map further down this page (onViewCounty).
export default function ExpectedImpactsSection({ impacts, totalCountiesAtRisk, onViewCounty }) {
  const counties = impacts.counties;
  const highRiskCount = counties.filter((c) => {
    const level = getRiskLevel(c.risk_tier);
    return level === "high" || level === "severe";
  }).length;

  return (
    <section className="mt-6" aria-labelledby="expected-impacts-heading">
      <SectionHeading
        id="expected-impacts-heading"
        title="Expected Impacts"
        subtitle="Areas with the highest predicted storm impact"
        action={
          <button
            type="button"
            className="cursor-pointer whitespace-nowrap bg-transparent py-1 text-[0.85rem] font-semibold text-accent hover:text-accent-dark hover:underline"
            onClick={() => onViewCounty?.()}
          >
            View Full Risk Map &rarr;
          </button>
        }
      />

      {typeof totalCountiesAtRisk === "number" && (
        <p className="mt-2.5 text-[0.82rem] text-muted">
          {totalCountiesAtRisk} counties at risk &bull; {highRiskCount} high-risk areas
        </p>
      )}

      <div className="mt-3.5 flex items-stretch gap-3.5 max-[860px]:flex-wrap">
        {counties.map((county) => (
          <ImpactCard key={county.fips} county={county} onViewDetails={() => onViewCounty?.(county.fips)} />
        ))}
      </div>
    </section>
  );
}
