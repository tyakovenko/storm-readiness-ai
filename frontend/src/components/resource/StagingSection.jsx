import StagingMap from "./StagingMap.jsx";
import StagingLocationDetails from "./StagingLocationDetails.jsx";
import SectionHeading from "../SectionHeading.jsx";

export default function StagingSection({ deployments, selectedId, onSelect }) {
  const selectedDeployment = deployments.find((d) => d.id === selectedId) ?? deployments[0] ?? null;

  return (
    <section className="mt-6" aria-labelledby="staging-section-heading">
      <SectionHeading
        id="staging-section-heading"
        title="Resource Staging Map"
        subtitle="Recommended pre-positioning locations for priority impact areas"
      />

      <div className="mt-3.5 flex items-stretch gap-4 max-[900px]:flex-col">
        <div className="min-w-0 flex-[7_1_0] max-[900px]:w-full max-[900px]:flex-auto">
          <StagingMap deployments={deployments} selectedId={selectedDeployment?.id ?? null} onSelect={onSelect} />
        </div>
        <div className="min-w-[220px] flex-[3_1_0] max-[900px]:w-full max-[900px]:flex-auto">
          <StagingLocationDetails deployment={selectedDeployment} />
        </div>
      </div>
    </section>
  );
}
