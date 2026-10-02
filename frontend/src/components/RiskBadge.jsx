import { RISK_CLASSES } from "../utils/riskTier.js";

const DEFAULT_LABELS = {
  low: "Low Risk",
  moderate: "Moderate Risk",
  high: "High Risk",
  severe: "Severe Risk",
};

// Generic small badge for the app's shared risk vocabulary (low/moderate/
// high/severe). Pass children to override the text (e.g. "HIGH" for a
// priority column) while keeping the level-based color.
export default function RiskBadge({ level, children }) {
  return (
    <span
      className={`inline-block whitespace-nowrap rounded px-2 py-[3px] text-[0.68rem] font-bold uppercase tracking-[0.4px] ${RISK_CLASSES[level]?.badge ?? ""}`}
    >
      {children ?? DEFAULT_LABELS[level] ?? level}
    </span>
  );
}
