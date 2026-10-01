import DeploymentList from "./DeploymentList.jsx";
import "./RecommendedDeployments.css";

export default function RecommendedDeployments({ deployments, onSelectDeployment }) {
  return (
    <section className="recommended-deployments" aria-labelledby="recommended-deployments-heading">
      <div className="recommended-deployments__heading">
        <h3 id="recommended-deployments-heading">Recommended Deployments</h3>
        <p className="recommended-deployments__subtitle">
          Priority staging recommendations based on predicted county impacts
        </p>
      </div>

      <p className="recommended-deployments__summary">{deployments.length} priority staging areas</p>

      <DeploymentList deployments={deployments} onSelectDeployment={onSelectDeployment} />
    </section>
  );
}
