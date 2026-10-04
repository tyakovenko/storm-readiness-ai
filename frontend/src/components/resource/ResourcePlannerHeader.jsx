export default function ResourcePlannerHeader({ stormName, advisoryNumber, planningWindowHours, countiesAtRisk }) {
  return (
    <div className="mb-5 flex flex-col gap-2 border-b border-line pb-3.5">
      <p className="max-w-[60ch] text-[0.95rem] text-muted">
        Recommended resource allocation based on predicted storm impacts
      </p>

      <div className="flex flex-wrap items-center gap-6 text-[0.85rem]">
        <span className="font-semibold text-navy">
          {stormName} <span aria-hidden="true">&bull;</span> Advisory #{advisoryNumber}
        </span>

        <span className="flex items-baseline gap-1.5 text-muted">
          <span className="text-[0.68rem] font-bold uppercase tracking-[0.4px] text-muted">Planning Window</span>
          <span className="font-semibold text-ink">Next {planningWindowHours} hours</span>
        </span>

        <span className="flex items-baseline gap-1.5 text-muted">
          <span className="font-semibold text-ink">{countiesAtRisk} counties at risk</span>
        </span>
      </div>
    </div>
  );
}
