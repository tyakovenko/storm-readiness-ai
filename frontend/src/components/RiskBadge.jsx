import "./RiskBadge.css";

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
  return <span className={`risk-badge risk-badge--${level}`}>{children ?? DEFAULT_LABELS[level] ?? level}</span>;
}
