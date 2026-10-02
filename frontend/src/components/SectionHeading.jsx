// The title + subtitle used at the top of every page section.
// `action` renders on the right (e.g. a "View Full Risk Map" link).
export default function SectionHeading({ id, title, subtitle, action }) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-4">
      <div>
        <h3 id={id} className="text-[1.1rem] font-bold text-navy">{title}</h3>
        {subtitle && <p className="mt-0.5 text-[0.85rem] text-muted">{subtitle}</p>}
      </div>
      {action}
    </div>
  );
}
