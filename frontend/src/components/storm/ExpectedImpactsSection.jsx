import ImpactCard from "./ImpactCard.jsx";
import { getRiskLevel } from "../../utils/riskTier.js";
import "./ExpectedImpactsSection.css";

export default function ExpectedImpactsSection({ impacts, totalCountiesAtRisk, onNavigate }) {
  const counties = impacts.counties;
  const highRiskCount = counties.filter((c) => {
    const level = getRiskLevel(c.risk_tier);
    return level === "high" || level === "severe";
  }).length;

  function goToRiskMap(county) {
    if (!onNavigate) return;
    if (county) onNavigate("risk-map", { fips: county.fips, name: county.name });
    else onNavigate("risk-map");
  }

  return (
    <section className="expected-impacts" aria-labelledby="expected-impacts-heading">
      <div className="expected-impacts__heading">
        <div>
          <h3 id="expected-impacts-heading">Expected Impacts</h3>
          <p className="expected-impacts__subtitle">Areas with the highest predicted storm impact</p>
        </div>
        <button type="button" className="expected-impacts__link" onClick={() => goToRiskMap()}>
          View Full Risk Map &rarr;
        </button>
      </div>

      {typeof totalCountiesAtRisk === "number" && (
        <p className="expected-impacts__summary">
          {totalCountiesAtRisk} counties at risk &bull; {highRiskCount} high-risk areas
        </p>
      )}

      <div className="expected-impacts__grid">
        {counties.map((county) => (
          <ImpactCard key={county.fips} county={county} onViewDetails={() => goToRiskMap(county)} />
        ))}
      </div>
    </section>
  );
}
