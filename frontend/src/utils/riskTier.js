// Maps the backend's risk_tier values (green/yellow/orange/red — see
// CountyImpact in backend/agent/contracts.py) to this app's risk-level
// vocabulary and shared risk colors, so every screen uses the exact same
// severity system.
const TIER_TO_LEVEL = { green: "low", yellow: "moderate", orange: "high", red: "severe" };
export const LEVEL_LABEL = { low: "Low Risk", moderate: "Moderate Risk", high: "High Risk", severe: "Severe Risk" };

export function getRiskLevel(riskTier) {
  return TIER_TO_LEVEL[riskTier] ?? "moderate";
}

export function getRiskLabel(riskTier) {
  return LEVEL_LABEL[getRiskLevel(riskTier)];
}

// Tailwind classes per risk level, written out in full so Tailwind can find them.
export const RISK_CLASSES = {
  low: { badge: "bg-risk-low-bg text-risk-low", border: "border-risk-low", borderLeft: "border-l-risk-low" },
  moderate: { badge: "bg-risk-moderate-bg text-risk-moderate", border: "border-risk-moderate", borderLeft: "border-l-risk-moderate" },
  high: { badge: "bg-risk-high-bg text-risk-high", border: "border-risk-high", borderLeft: "border-l-risk-high" },
  severe: { badge: "bg-risk-severe-bg text-risk-severe", border: "border-risk-severe", borderLeft: "border-l-risk-severe" },
};

// Leaflet draws to SVG and can't read CSS variables, so maps use these literal
// copies of the --color-risk-* theme values in index.css. Keep the two in sync.
export const RISK_HEX = { low: "#2e7d32", moderate: "#c98a00", high: "#d9641e", severe: "#c62828" };
