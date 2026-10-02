import { useState } from "react";
import { PAGE, PageTitle } from "../components/Page.jsx";
import ResourcePlannerHeader from "../components/resource/ResourcePlannerHeader.jsx";
import ResourceSummary from "../components/resource/ResourceSummary.jsx";
import RecommendedDeployments from "../components/resource/RecommendedDeployments.jsx";
import StagingSection from "../components/resource/StagingSection.jsx";
import { RESOURCE_REQUIREMENTS_MOCK, RECOMMENDED_DEPLOYMENTS_MOCK } from "../data/resourcePlannerMock.js";
import { toStormSummary } from "../utils/stormSummary.js";

export default function ResourcePlanner({ overview }) {
  // Shared, page-local selection (not global app state): "View Plan" in the
  // deployment table and clicking a staging marker on the map both drive
  // this same id, so the two sections stay in sync without over-engineering
  // a bigger state mechanism.
  const [selectedDeploymentId, setSelectedDeploymentId] = useState(RECOMMENDED_DEPLOYMENTS_MOCK[0]?.id ?? null);
  // Storm identity matches the Storm Overview (backend); the plan itself is still prototype data.
  const storm = overview ? toStormSummary(overview) : null;

  return (
    <section className={PAGE}>
      <PageTitle>Resource Planner</PageTitle>
      {storm && (
        <ResourcePlannerHeader
          stormName={storm.stormName}
          advisoryNumber={storm.advisoryNumber}
          planningWindowHours={storm.landfallHours}
          countiesAtRisk={storm.countiesAtRisk}
        />
      )}
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
