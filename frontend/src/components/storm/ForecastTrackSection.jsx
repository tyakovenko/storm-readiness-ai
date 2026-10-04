import ForecastMap from "./ForecastMap.jsx";
import ForecastDetailsPanel from "./ForecastDetailsPanel.jsx";
import SectionHeading from "../SectionHeading.jsx";

export default function ForecastTrackSection({ storm, track }) {
  return (
    <section className="mt-6" aria-labelledby="forecast-track-heading">
      <SectionHeading
        id="forecast-track-heading"
        title="Forecast Track"
        subtitle="Projected storm path and forecast conditions"
      />

      <div className="mt-3.5 flex items-stretch gap-4 max-[900px]:flex-col">
        <div className="min-w-0 flex-[7_1_0] max-[900px]:w-full max-[900px]:flex-auto">
          <ForecastMap track={track} />
        </div>
        <div className="min-w-[220px] flex-[3_1_0] max-[900px]:w-full max-[900px]:flex-auto">
          <ForecastDetailsPanel storm={storm} />
        </div>
      </div>

      <p className="mt-2.5 text-xs italic text-muted">
        Prototype forecast track, rainfall and movement — not live NOAA/NHC data.
      </p>
    </section>
  );
}
