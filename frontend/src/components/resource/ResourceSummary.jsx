import MetricItem from "../storm/MetricItem.jsx";
import SectionHeading from "../SectionHeading.jsx";

export default function ResourceSummary({ requirements }) {
  return (
    <section className="mt-6" aria-labelledby="resource-requirements-heading">
      <SectionHeading
        id="resource-requirements-heading"
        title="Resource Requirements"
        subtitle="Estimated resources required across predicted impact areas"
      />

      <dl
        className="mt-2.5 flex overflow-hidden rounded-md border border-line bg-surface max-[760px]:flex-wrap"
        aria-label="Resource requirement summary"
      >
        {requirements.map((item) => (
          <MetricItem
            key={item.type}
            label={item.label}
            value={item.quantity.toLocaleString("en-US")}
            sublabel={item.sublabel}
          />
        ))}
      </dl>

      <p className="mt-2.5 text-xs italic text-muted">Prototype planning data — not a real optimizer output.</p>
    </section>
  );
}
