import RiskBadge from "../RiskBadge.jsx";
import { RESOURCE_TYPE_LABELS } from "../../data/resourcePlannerMock.js";
import "./StagingLocationDetails.css";

export default function StagingLocationDetails({ deployment }) {
  if (!deployment || !deployment.stagingLocation) {
    return (
      <div className="staging-details staging-details--empty">
        <p className="staging-details__empty-text">Select a staging location on the map to see its plan.</p>
      </div>
    );
  }

  const { stagingLocation } = deployment;

  return (
    <dl className="staging-details" aria-label="Staging location details">
      <div className="staging-details__item">
        <dt className="staging-details__label">Staging Location</dt>
        <dd className="staging-details__value">{stagingLocation.name}</dd>
        <dd className="staging-details__sublabel">
          {stagingLocation.city}, {stagingLocation.state}
        </dd>
        <dd className="staging-details__tag">Suggested pre-positioning area</dd>
      </div>

      <div className="staging-details__item">
        <dt className="staging-details__label">Serves</dt>
        <dd className="staging-details__value">{deployment.targetAreas.join(", ")}</dd>
      </div>

      <div className="staging-details__item">
        <dt className="staging-details__label">Resources</dt>
        <dd>
          <ul className="staging-details__resources">
            {deployment.resources.map((r) => (
              <li key={r.type}>
                <strong>{r.quantity}</strong> {RESOURCE_TYPE_LABELS[r.type] ?? r.type}
              </li>
            ))}
          </ul>
        </dd>
      </div>

      <div className="staging-details__item">
        <dt className="staging-details__label">Deploy By</dt>
        <dd className="staging-details__value">{deployment.deployBeforeLandfallHours} hours before landfall</dd>
      </div>

      <div className="staging-details__item">
        <dt className="staging-details__label">Priority</dt>
        <dd>
          <RiskBadge level={deployment.priority}>{deployment.priority.toUpperCase()}</RiskBadge>
        </dd>
      </div>

      <div className="staging-details__item staging-details__item--why">
        <dt className="staging-details__label">Why This Location?</dt>
        <dd>
          <ul className="staging-details__why-list">
            {deployment.whyThisLocation.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        </dd>
      </div>
    </dl>
  );
}
