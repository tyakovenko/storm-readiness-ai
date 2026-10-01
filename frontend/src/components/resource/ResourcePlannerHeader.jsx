import "./ResourcePlannerHeader.css";

export default function ResourcePlannerHeader({ stormName, advisoryNumber, planningWindowHours, countiesAtRisk }) {
  return (
    <div className="resource-planner-header">
      <p className="resource-planner-header__lede">
        Recommended resource allocation based on predicted storm impacts
      </p>

      <div className="resource-planner-header__status">
        <span className="resource-planner-header__storm">
          {stormName} <span aria-hidden="true">&bull;</span> Advisory #{advisoryNumber}
        </span>

        <span className="resource-planner-header__stat">
          <span className="resource-planner-header__stat-label">Planning Window</span>
          <span className="resource-planner-header__stat-value">Next {planningWindowHours} hours</span>
        </span>

        <span className="resource-planner-header__stat">
          <span className="resource-planner-header__stat-value">{countiesAtRisk} counties at risk</span>
        </span>
      </div>
    </div>
  );
}
