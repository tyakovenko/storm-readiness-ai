import DeploymentList from "./DeploymentList.jsx";
import SectionHeading from "../SectionHeading.jsx";

export default function RecommendedDeployments({ deployments, onSelectDeployment }) {
  return (
    <section className="mt-6" aria-labelledby="recommended-deployments-heading">
      <SectionHeading
        id="recommended-deployments-heading"
        title="Recommended Deployments"
        subtitle="Priority staging recommendations based on predicted county impacts"
      />

      <p className="mb-3.5 mt-2.5 text-[0.82rem] text-muted">{deployments.length} priority staging areas</p>

      <DeploymentList deployments={deployments} onSelectDeployment={onSelectDeployment} />
    </section>
  );
}
