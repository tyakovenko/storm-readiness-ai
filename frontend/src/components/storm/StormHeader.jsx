import { getStormSeverityLevel } from "../../utils/stormSeverity.js";
import "./StormHeader.css";

export default function StormHeader({ storm }) {
  const severityLevel = getStormSeverityLevel(storm.category);

  return (
    <div className="storm-header">
      <div className="storm-header__main">
        <div className="storm-header__title-row">
          <h3 className="storm-header__name">{storm.stormName}</h3>
          <span className={`storm-header__severity storm-header__severity--${severityLevel}`}>
            Category {storm.category} &bull; {storm.classification}
          </span>
        </div>
        <p className="storm-header__meta">
          Latest forecast <span aria-hidden="true">•</span> Updated {storm.updatedAt}
        </p>
      </div>
      <div className="storm-header__advisory">
        <span className="storm-header__advisory-label">Advisory</span>
        <span className="storm-header__advisory-value">#{storm.advisoryNumber}</span>
      </div>
    </div>
  );
}
