import { useRef, useState } from "react";
import { PAGE, PageStatus, PageTitle } from "../components/Page.jsx";
import StormHeader from "../components/storm/StormHeader.jsx";
import StormMetrics from "../components/storm/StormMetrics.jsx";
import ForecastTrackSection from "../components/storm/ForecastTrackSection.jsx";
import ExpectedImpactsSection from "../components/storm/ExpectedImpactsSection.jsx";
import RiskMapSection from "../components/storm/RiskMapSection.jsx";
import { STORM_FORECAST_TRACK } from "../data/stormOverviewMock.js";
import { toStormSummary } from "../utils/stormSummary.js";

export default function StormOverview({ overview, overviewError }) {
  const [selectedFips, setSelectedFips] = useState(null);
  const riskMapRef = useRef(null);

  if (!overview) return <PageStatus title="Storm Overview" error={overviewError} />;

  const storm = toStormSummary(overview);
  // The summary row shows the 3 highest-impact counties; the risk map shows them all.
  const topCounties = [...overview.impact.counties]
    .sort((a, b) => b.pct_customers_out.median - a.pct_customers_out.median)
    .slice(0, 3);

  function viewOnRiskMap(fips) {
    if (fips) setSelectedFips(fips);
    riskMapRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  return (
    <section className={PAGE}>
      <PageTitle>Storm Overview</PageTitle>
      <StormHeader storm={storm} />
      <StormMetrics storm={storm} />
      <ForecastTrackSection storm={storm} track={STORM_FORECAST_TRACK} />
      <ExpectedImpactsSection
        impacts={{ ...overview.impact, counties: topCounties }}
        totalCountiesAtRisk={storm.countiesAtRisk}
        onViewCounty={viewOnRiskMap}
      />
      <RiskMapSection
        sectionRef={riskMapRef}
        impact={overview.impact}
        shelters={overview.assets.shelters}
        selectedFips={selectedFips}
        onSelect={setSelectedFips}
      />
    </section>
  );
}
