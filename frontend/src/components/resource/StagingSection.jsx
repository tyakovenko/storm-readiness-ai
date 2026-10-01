import StagingMap from "./StagingMap.jsx";
import StagingLocationDetails from "./StagingLocationDetails.jsx";
import "./StagingSection.css";

export default function StagingSection({ deployments, selectedId, onSelect }) {
  const selectedDeployment = deployments.find((d) => d.id === selectedId) ?? deployments[0] ?? null;

  return (
    <section className="staging-section" aria-labelledby="staging-section-heading">
      <div className="staging-section__heading">
        <h3 id="staging-section-heading">Resource Staging Map</h3>
        <p className="staging-section__subtitle">
          Recommended pre-positioning locations for priority impact areas
        </p>
      </div>

      <div className="staging-section__grid">
        <StagingMap deployments={deployments} selectedId={selectedDeployment?.id ?? null} onSelect={onSelect} />
        <StagingLocationDetails deployment={selectedDeployment} />
      </div>
    </section>
  );
}
