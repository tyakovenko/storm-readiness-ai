import { STORM_FORECAST_PROTOTYPE } from "../data/stormOverviewMock.js";

// Saffir-Simpson naming: category 3+ is a major hurricane.
export function classifyCategory(category) {
  if (category === 0) return "Tropical Storm";
  return category >= 3 ? "Major Hurricane" : "Hurricane";
}

function formatIssued(isoUtc) {
  const d = new Date(isoUtc);
  if (Number.isNaN(d.getTime())) return isoUtc;
  const when = d.toLocaleString("en-US", {
    month: "short", day: "numeric", hour: "numeric", minute: "2-digit", timeZone: "UTC",
  });
  return `${when} UTC`;
}

// Builds the storm object the Storm Overview / Resource Planner components read,
// from the backend's /api/overview. Fields the data contract doesn't have yet
// (rainfall, movement) come from the labeled prototype data instead.
export function toStormSummary(overview) {
  const a = overview.advisory;
  return {
    stormName: a.storm_name,
    advisoryNumber: a.advisory_number,
    updatedAt: formatIssued(a.issued_utc),
    category: a.category,
    classification: classifyCategory(a.category),
    maxWindKt: a.max_wind_kt,
    landfallHours: a.lead_time_to_landfall_h,
    countiesAtRisk: overview.impact.counties.length,
    landfallLocation: a.forecast_landfall,
    rainfallInches: STORM_FORECAST_PROTOTYPE.rainfallInches,
    movementDirection: STORM_FORECAST_PROTOTYPE.movementDirection,
    movementSpeedMph: STORM_FORECAST_PROTOTYPE.movementSpeedMph,
  };
}
