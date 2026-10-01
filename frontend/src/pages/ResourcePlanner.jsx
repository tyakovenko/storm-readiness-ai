import { useState } from "react";
import "./Pages.css";
import ResourcePlannerHeader from "../components/resource/ResourcePlannerHeader.jsx";
import ResourceSummary from "../components/resource/ResourceSummary.jsx";
import RecommendedDeployments from "../components/resource/RecommendedDeployments.jsx";
import StagingSection from "../components/resource/StagingSection.jsx";
import { STORM_OVERVIEW_MOCK } from "../data/stormOverviewMock.js";
import { RESOURCE_REQUIREMENTS_MOCK, RECOMMENDED_DEPLOYMENTS_MOCK } from "../data/resourcePlannerMock.js";

export default function ResourcePlanner() {
  // Shared, page-local selection (not global app state): "View Plan" in the
  // deployment table and clicking a staging marker on the map both drive
  // this same id, so the two sections stay in sync without over-engineering
  // a bigger state mechanism.
  const [selectedDeploymentId, setSelectedDeploymentId] = useState(RECOMMENDED_DEPLOYMENTS_MOCK[0]?.id ?? null);

  return (
    <section className="page">
      <h2 className="page__title">Resource Planner</h2>
      <ResourcePlannerHeader
        stormName={STORM_OVERVIEW_MOCK.stormName}
        advisoryNumber={STORM_OVERVIEW_MOCK.advisoryNumber}
        planningWindowHours={STORM_OVERVIEW_MOCK.landfallHours}
        countiesAtRisk={STORM_OVERVIEW_MOCK.countiesAtRisk}
      />
      <ResourceSummary requirements={RESOURCE_REQUIREMENTS_MOCK} />
      <RecommendedDeployments
        deployments={RECOMMENDED_DEPLOYMENTS_MOCK}
        onSelectDeployment={setSelectedDeploymentId}
      />
      <StagingSection
        deployments={RECOMMENDED_DEPLOYMENTS_MOCK}
        selectedId={selectedDeploymentId}
        onSelect={setSelectedDeploymentId}
      />
    </section>
  );
}
