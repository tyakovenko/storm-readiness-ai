import "./MetricItem.css";

export default function MetricItem({ label, value, sublabel, valueColor }) {
  return (
    <div className="metric-item">
      <dt className="metric-item__label">{label}</dt>
      <dd className="metric-item__value" style={valueColor ? { color: valueColor } : undefined}>
        {value}
      </dd>
      <dd className="metric-item__sublabel">{sublabel}</dd>
    </div>
  );
}
