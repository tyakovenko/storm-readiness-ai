// TEMPORARY frontend development data for the Storm Overview page.
// The backend has no storm endpoint yet (no GET /api/storm). This object
// is a stand-in so the UI can be built against a realistic shape.
// Replace this import with a fetch to GET /api/storm once that endpoint
// exists, keeping this field shape so the components don't need to change.
export const STORM_OVERVIEW_MOCK = {
  stormName: "Hurricane Idalia",
  advisoryNumber: 15,
  updatedAt: "2:00 PM",
  category: 3,
  classification: "Major Hurricane",
  maxWindKt: 105,
  landfallHours: 36,
  countiesAtRisk: 12,

  // Forecast Track section fields (also prototype data; see forecastTrack below).
  landfallLocation: "Cedar Key, FL",
  rainfallInches: "6–10 in",
  movementDirection: "NE",
  movementSpeedMph: 14,
};

// TEMPORARY forecast track for the "Where is it going?" map. Positions are
// a plausible but invented path through the Gulf toward Florida's Big Bend —
// not real NOAA/NHC advisory data. Each point's shape mirrors what a future
// GET /api/storm response should provide, so the map can be pointed at real
// data later without changing ForecastMap.jsx:
//   { latitude, longitude, forecastTime, windKt, category, pointType }
// pointType is one of "current" | "forecast" | "landfall" and drives marker
// styling — a real API should keep marking exactly one point as "current"
// and one as "landfall".
export const STORM_FORECAST_TRACK = [
  { id: "t0", pointType: "current", latitude: 23.8, longitude: -85.9, forecastTime: "Now", windKt: 105, category: 3 },
  { id: "t1", pointType: "forecast", latitude: 25.6, longitude: -84.6, forecastTime: "+12 hr", windKt: 110, category: 3 },
  { id: "t2", pointType: "forecast", latitude: 27.4, longitude: -83.8, forecastTime: "+24 hr", windKt: 105, category: 3 },
  { id: "t3", pointType: "landfall", latitude: 29.14, longitude: -83.03, forecastTime: "+36 hr", windKt: 100, category: 3 },
  { id: "t4", pointType: "forecast", latitude: 30.6, longitude: -82.2, forecastTime: "+48 hr", windKt: 60, category: 1 },
];

// TEMPORARY mock for the Expected Impacts section. There is no GET
// /api/impact endpoint yet, but the backend already defines this exact
// shape for its predict_impact tool — see backend/agent/contracts.py
// (Impact / CountyImpact) and docs/data-contract.md. Field names here
// intentionally match that contract as closely as possible (snake_case,
// risk_tier as green/yellow/orange/red, pct_customers_out as
// {low, median, high}) so a real endpoint can be swapped in later with
// little to no shape translation in the components that read this.
// Only the top 3 highest-risk counties are listed — this is a summary
// card row, not the full `countiesAtRisk` count from STORM_OVERVIEW_MOCK.
export const EXPECTED_IMPACTS_MOCK = {
  advisory_number: 15,
  model_version: "stub-v0",
  source: "Stub data — not a real impact model (prototype)",
  counties: [
    {
      fips: "12029",
      name: "Dixie County",
      state: "FL",
      risk_tier: "orange",
      pct_customers_out: { low: 38, median: 47, high: 58 },
      customers_served: 8400,
      why: ["High forecast winds", "Infrastructure exposure"],
    },
    {
      fips: "12075",
      name: "Levy County",
      state: "FL",
      risk_tier: "orange",
      pct_customers_out: { low: 29, median: 38, high: 49 },
      customers_served: 15200,
      why: ["High forecast winds", "Coastal surge exposure"],
    },
    {
      fips: "12123",
      name: "Taylor County",
      state: "FL",
      risk_tier: "yellow",
      pct_customers_out: { low: 17, median: 24, high: 33 },
      customers_served: 10100,
      why: ["Moderate forecast winds", "Rural grid infrastructure"],
    },
  ],
};
