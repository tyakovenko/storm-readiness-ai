// Maps the backend's risk_tier values (green/yellow/orange/red — see
// CountyImpact in backend/agent/contracts.py) to this app's risk-level
// vocabulary and shared --risk-* color tokens, so county impact cards use
// the exact same severity system as the rest of the dashboard.
const TIER_TO_LEVEL = { green: "low", yellow: "moderate", orange: "high", red: "severe" };
const LEVEL_LABEL = { low: "Low Risk", moderate: "Moderate Risk", high: "High Risk", severe: "Severe Risk" };

export function getRiskLevel(riskTier) {
  return TIER_TO_LEVEL[riskTier] ?? "moderate";
}

export function getRiskLabel(riskTier) {
  return LEVEL_LABEL[getRiskLevel(riskTier)];
}
