import { useState } from "react";
import RiskBadge from "../RiskBadge.jsx";
import { RESOURCE_TYPE_LABELS } from "../../data/resourcePlannerMock.js";
import "./DeploymentList.css";

function ResourceList({ resources }) {
  return (
    <ul className="deployment-resources">
      {resources.map((r) => (
        <li key={r.type}>
          <strong>{r.quantity}</strong> {RESOURCE_TYPE_LABELS[r.type] ?? r.type}
        </li>
      ))}
    </ul>
  );
}

function DeploymentDetail({ deployment }) {
  return (
    <dl className="deployment-detail">
      <div className="deployment-detail__row">
        <dt>Target County</dt>
        <dd>
          {deployment.county}, {deployment.state}
        </dd>
      </div>
      {deployment.stagingLocation && (
        <div className="deployment-detail__row">
          <dt>Staging Location</dt>
          <dd>
            {deployment.stagingLocation.name} ({deployment.stagingLocation.city}, {deployment.stagingLocation.state})
          </dd>
        </div>
      )}
      <div className="deployment-detail__row">
        <dt>Priority</dt>
        <dd>
          <RiskBadge level={deployment.priority}>{deployment.priority.toUpperCase()}</RiskBadge>
        </dd>
      </div>
      <div className="deployment-detail__row">
        <dt>Risk Level</dt>
        <dd>
          <RiskBadge level={deployment.riskTier} />
        </dd>
      </div>
      <div className="deployment-detail__row">
        <dt>Predicted Impact</dt>
        <dd>{deployment.predictedOutagePct}% predicted customer outage</dd>
      </div>
      <div className="deployment-detail__row">
        <dt>Resources</dt>
        <dd>
          <ResourceList resources={deployment.resources} />
        </dd>
      </div>
      <div className="deployment-detail__row">
        <dt>Deployment Timing</dt>
        <dd>
          Deploy by {deployment.deployBeforeLandfallHours} hrs before landfall
          <span className="deployment-detail__t-code"> (T-{deployment.deployBeforeLandfallHours})</span>
        </dd>
      </div>
      <div className="deployment-detail__row deployment-detail__row--why">
        <dt>Why this recommendation?</dt>
        <dd>
          <ul>
            {deployment.rationale.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        </dd>
      </div>
    </dl>
  );
}

export default function DeploymentList({ deployments, onSelectDeployment }) {
  const [expandedId, setExpandedId] = useState(null);

  return (
    <div className="deployment-list" role="table" aria-label="Recommended deployments">
      <div className="deployment-row deployment-row--header" role="row">
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
          <div className="deployment-row-group" key={d.id}>
            <div className="deployment-row" role="row">
              <span role="cell" data-label="Priority">
                <RiskBadge level={d.priority}>{d.priority.toUpperCase()}</RiskBadge>
              </span>
              <span role="cell" data-label="Target Area" className="deployment-row__county">
                {d.county}, {d.state}
              </span>
              <span role="cell" data-label="Resources">
                <ResourceList resources={d.resources} />
              </span>
              <span role="cell" data-label="Deploy By" className="deployment-row__timing">
                <span>Deploy by {d.deployBeforeLandfallHours} hrs before landfall</span>
                <span className="deployment-row__t-code">T-{d.deployBeforeLandfallHours}</span>
              </span>
              <span role="cell" data-label="Risk">
                <RiskBadge level={d.riskTier} />
              </span>
              <span role="cell" data-label="Action" className="deployment-row__action">
                <button
                  type="button"
                  className="deployment-row__view-plan"
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
              <div className="deployment-row__expanded" role="row" id={`deployment-plan-${d.id}`}>
                <DeploymentDetail deployment={d} />
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
