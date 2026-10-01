import "./Pages.css";
import StormHeader from "../components/storm/StormHeader.jsx";
import StormMetrics from "../components/storm/StormMetrics.jsx";
import ForecastTrackSection from "../components/storm/ForecastTrackSection.jsx";
import ExpectedImpactsSection from "../components/storm/ExpectedImpactsSection.jsx";
import { STORM_OVERVIEW_MOCK, STORM_FORECAST_TRACK, EXPECTED_IMPACTS_MOCK } from "../data/stormOverviewMock.js";

export default function StormOverview({ onNavigate }) {
  return (
    <section className="page">
      <h2 className="page__title">Storm Overview</h2>
      <StormHeader storm={STORM_OVERVIEW_MOCK} />
      <StormMetrics storm={STORM_OVERVIEW_MOCK} />
      <ForecastTrackSection storm={STORM_OVERVIEW_MOCK} track={STORM_FORECAST_TRACK} />
      <ExpectedImpactsSection
        impacts={EXPECTED_IMPACTS_MOCK}
        totalCountiesAtRisk={STORM_OVERVIEW_MOCK.countiesAtRisk}
        onNavigate={onNavigate}
      />
    </section>
  );
}
