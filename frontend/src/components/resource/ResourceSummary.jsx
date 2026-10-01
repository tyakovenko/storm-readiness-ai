import MetricItem from "../storm/MetricItem.jsx";
import "./ResourceSummary.css";

export default function ResourceSummary({ requirements }) {
  return (
    <section className="resource-requirements" aria-labelledby="resource-requirements-heading">
      <div className="resource-requirements__heading">
        <h3 id="resource-requirements-heading">Resource Requirements</h3>
        <p className="resource-requirements__subtitle">
          Estimated resources required across predicted impact areas
        </p>
      </div>

      <dl className="resource-summary" aria-label="Resource requirement summary">
        {requirements.map((item) => (
          <MetricItem
            key={item.type}
            label={item.label}
            value={item.quantity.toLocaleString("en-US")}
            sublabel={item.sublabel}
          />
        ))}
      </dl>

      <p className="resource-requirements__disclaimer">Prototype planning data — not a real optimizer output.</p>
    </section>
  );
}
