import { getRiskLevel, getRiskLabel } from "../../utils/riskTier.js";
import "./ImpactCard.css";

export default function ImpactCard({ county, onViewDetails }) {
  const level = getRiskLevel(county.risk_tier);
  const label = getRiskLabel(county.risk_tier);

  return (
    <article className={`impact-card impact-card--${level}`}>
      <span className={`impact-card__badge impact-card__badge--${level}`}>{label}</span>

      <h4 className="impact-card__county">
        {county.name}, {county.state}
      </h4>

      <div className="impact-card__stat">
        <span className="impact-card__pct">{county.pct_customers_out.median}%</span>
        <span className="impact-card__pct-label">Predicted customer outage</span>
      </div>

      <div className="impact-card__drivers">
        <span className="impact-card__drivers-label">Primary drivers</span>
        <span className="impact-card__drivers-text">{county.why.join(" • ")}</span>
      </div>

      <button type="button" className="impact-card__link" onClick={onViewDetails}>
        View details &rarr;
      </button>
    </article>
  );
}
