import { getStormSeverityLevel } from "../../utils/stormSeverity.js";
import { RISK_CLASSES } from "../../utils/riskTier.js";

export default function StormHeader({ storm }) {
  const severity = RISK_CLASSES[getStormSeverityLevel(storm.category)];

  return (
    <div className="mb-4 flex flex-wrap items-start justify-between gap-4 border-b border-line pb-4">
      <div>
        <div className="flex flex-wrap items-center gap-2.5">
          <h3 className="text-[1.4rem] font-bold text-navy">{storm.stormName}</h3>
          <span
            className={`inline-flex items-center whitespace-nowrap rounded border px-2 py-[3px] text-[0.72rem] font-bold uppercase tracking-[0.3px] ${severity.badge} ${severity.border}`}
          >
            Category {storm.category} &bull; {storm.classification}
          </span>
        </div>
        <p className="mt-1 text-[0.85rem] text-muted">
          Latest forecast <span aria-hidden="true">•</span> Updated {storm.updatedAt}
        </p>
      </div>
      <div className="flex shrink-0 flex-col items-end text-right">
        <span className="text-[0.7rem] font-semibold uppercase tracking-[0.4px] text-muted">Advisory</span>
        <span className="text-[1.1rem] font-bold text-navy">#{storm.advisoryNumber}</span>
      </div>
    </div>
  );
}
