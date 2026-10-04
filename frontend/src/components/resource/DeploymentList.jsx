import { useState } from "react";
import RiskBadge from "../RiskBadge.jsx";
import { RESOURCE_TYPE_LABELS } from "../../data/resourcePlannerMock.js";

// Six-column table on wide screens; under 860px each row stacks into a card
// and every cell shows its column name (from data-label) above the value.
const ROW = "grid grid-cols-[92px_1.3fr_1.5fr_1.3fr_112px_108px] items-center gap-3.5 px-4 py-2.5 max-[860px]:grid-cols-1 max-[860px]:gap-2";
const STACKED_LABEL =
  "max-[860px]:before:mb-0.5 max-[860px]:before:block max-[860px]:before:text-[0.65rem] max-[860px]:before:font-bold max-[860px]:before:uppercase max-[860px]:before:tracking-[0.4px] max-[860px]:before:text-muted max-[860px]:before:content-[attr(data-label)]";
const SMALL_CAPS = "text-[0.68rem] font-bold uppercase tracking-[0.4px] text-muted";
const LINK_BUTTON =
  "cursor-pointer whitespace-nowrap bg-transparent p-0 text-[0.82rem] font-semibold text-accent hover:text-accent-dark hover:underline";

function ResourceList({ resources }) {
  return (
    <ul className="flex flex-col gap-0.5 text-[0.82rem] text-ink">
      {resources.map((r) => (
        <li key={r.type}>
          <strong className="text-navy">{r.quantity}</strong> {RESOURCE_TYPE_LABELS[r.type] ?? r.type}
        </li>
      ))}
    </ul>
  );
}

function DetailRow({ label, children }) {
  return (
    <div className="contents max-[860px]:flex max-[860px]:flex-col max-[860px]:gap-0.5">
      <dt className={SMALL_CAPS}>{label}</dt>
      <dd className="text-[0.88rem] text-ink">{children}</dd>
    </div>
  );
}

function DeploymentDetail({ deployment }) {
  return (
    <dl className="grid grid-cols-[160px_1fr] gap-x-4 gap-y-2.5 max-[860px]:grid-cols-1">
      <DetailRow label="Target County">
        {deployment.county}, {deployment.state}
      </DetailRow>
      {deployment.stagingLocation && (
        <DetailRow label="Staging Location">
          {deployment.stagingLocation.name} ({deployment.stagingLocation.city}, {deployment.stagingLocation.state})
        </DetailRow>
      )}
      <DetailRow label="Priority">
        <RiskBadge level={deployment.priority}>{deployment.priority.toUpperCase()}</RiskBadge>
      </DetailRow>
      <DetailRow label="Risk Level">
        <RiskBadge level={deployment.riskTier} />
      </DetailRow>
      <DetailRow label="Predicted Impact">{deployment.predictedOutagePct}% predicted customer outage</DetailRow>
      <DetailRow label="Resources">
        <ResourceList resources={deployment.resources} />
      </DetailRow>
      <DetailRow label="Deployment Timing">
        Deploy by {deployment.deployBeforeLandfallHours} hrs before landfall
        <span className="text-[0.8rem] text-muted"> (T-{deployment.deployBeforeLandfallHours})</span>
      </DetailRow>
      <DetailRow label="Why this recommendation?">
        <ul className="flex list-disc flex-col gap-0.5 pl-[18px]">
          {deployment.rationale.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      </DetailRow>
    </dl>
  );
}

export default function DeploymentList({ deployments, onSelectDeployment }) {
  const [expandedId, setExpandedId] = useState(null);

  return (
    <div className="overflow-hidden rounded-md border border-line bg-surface" role="table" aria-label="Recommended deployments">
      <div className={`${ROW} border-b border-line bg-canvas ${SMALL_CAPS} max-[860px]:hidden`} role="row">
        <span role="columnheader">Priority</span>
        <span role="columnheader">Target Area</span>
        <span role="columnheader">Resources</span>
        <span role="columnheader">Deploy By</span>
        <span role="columnheader">Risk</span>
        <span role="columnheader" className="sr-only">Action</span>
      </div>

      {deployments.map((d) => {
        const expanded = expandedId === d.id;
        return (
          <div className="group" key={d.id}>
            <div className={`${ROW} border-b border-line group-last:border-b-0 group-hover:bg-canvas`} role="row">
              <span role="cell" data-label="Priority" className={STACKED_LABEL}>
                <RiskBadge level={d.priority}>{d.priority.toUpperCase()}</RiskBadge>
              </span>
              <span role="cell" data-label="Target Area" className={`${STACKED_LABEL} text-[0.92rem] font-bold text-navy`}>
                {d.county}, {d.state}
              </span>
              <span role="cell" data-label="Resources" className={STACKED_LABEL}>
                <ResourceList resources={d.resources} />
              </span>
              <span role="cell" data-label="Deploy By" className={`${STACKED_LABEL} flex flex-col gap-0.5 text-[0.82rem] text-ink`}>
                <span>Deploy by {d.deployBeforeLandfallHours} hrs before landfall</span>
                <span className="text-[0.72rem] text-muted">T-{d.deployBeforeLandfallHours}</span>
              </span>
              <span role="cell" data-label="Risk" className={STACKED_LABEL}>
                <RiskBadge level={d.riskTier} />
              </span>
              <span role="cell" data-label="Action" className="text-right max-[860px]:text-left">
                <button
                  type="button"
                  className={LINK_BUTTON}
                  onClick={() => {
                    setExpandedId(expanded ? null : d.id);
                    onSelectDeployment?.(d.id);
                  }}
                  aria-expanded={expanded}
                  aria-controls={`deployment-plan-${d.id}`}
                >
                  {expanded ? "Hide Plan" : "View Plan"} &rarr;
                </button>
              </span>
            </div>

            {expanded && (
              <div className="border-b border-line bg-canvas p-4" role="row" id={`deployment-plan-${d.id}`}>
                <DeploymentDetail deployment={d} />
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
