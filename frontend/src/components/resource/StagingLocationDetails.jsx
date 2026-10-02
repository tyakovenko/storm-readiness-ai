import RiskBadge from "../RiskBadge.jsx";
import { RESOURCE_TYPE_LABELS } from "../../data/resourcePlannerMock.js";
import { DETAIL_ITEM, DETAIL_LABEL, DETAIL_VALUE } from "../storm/ForecastDetailsPanel.jsx";

const PANEL = "flex h-[420px] flex-col gap-3.5 overflow-y-auto rounded-md border border-line bg-surface p-4 max-[760px]:h-auto";

export default function StagingLocationDetails({ deployment }) {
  if (!deployment || !deployment.stagingLocation) {
    return (
      <div className={`${PANEL} items-center justify-center text-center`}>
        <p className="text-[0.88rem] text-muted">Select a staging location on the map to see its plan.</p>
      </div>
    );
  }

  const { stagingLocation } = deployment;

  return (
    <dl className={PANEL} aria-label="Staging location details">
      <div className={DETAIL_ITEM}>
        <dt className={DETAIL_LABEL}>Staging Location</dt>
        <dd className={DETAIL_VALUE}>{stagingLocation.name}</dd>
        <dd className="text-[0.82rem] text-muted">
          {stagingLocation.city}, {stagingLocation.state}
        </dd>
        <dd className="mt-0.5 text-xs italic text-muted">Suggested pre-positioning area</dd>
      </div>

      <div className={DETAIL_ITEM}>
        <dt className={DETAIL_LABEL}>Serves</dt>
        <dd className={DETAIL_VALUE}>{deployment.targetAreas.join(", ")}</dd>
      </div>

      <div className={DETAIL_ITEM}>
        <dt className={DETAIL_LABEL}>Resources</dt>
        <dd>
          <ul className="flex flex-col gap-0.5 text-[0.88rem] text-ink">
            {deployment.resources.map((r) => (
              <li key={r.type}>
                <strong className="text-navy">{r.quantity}</strong> {RESOURCE_TYPE_LABELS[r.type] ?? r.type}
              </li>
            ))}
          </ul>
        </dd>
      </div>

      <div className={DETAIL_ITEM}>
        <dt className={DETAIL_LABEL}>Deploy By</dt>
        <dd className={DETAIL_VALUE}>{deployment.deployBeforeLandfallHours} hours before landfall</dd>
      </div>

      <div className={DETAIL_ITEM}>
        <dt className={DETAIL_LABEL}>Priority</dt>
        <dd>
          <RiskBadge level={deployment.priority}>{deployment.priority.toUpperCase()}</RiskBadge>
        </dd>
      </div>

      <div className={DETAIL_ITEM}>
        <dt className={DETAIL_LABEL}>Why This Location?</dt>
        <dd>
          <ul className="flex list-disc flex-col gap-0.5 pl-[18px] text-[0.85rem] text-ink">
            {deployment.whyThisLocation.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        </dd>
      </div>
    </dl>
  );
}
