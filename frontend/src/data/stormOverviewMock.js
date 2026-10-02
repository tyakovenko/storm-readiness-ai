// TEMPORARY prototype data for the parts of the Storm Overview the backend
// can't provide yet. Storm identity, category, wind, landfall timing and
// county impacts now come from GET /api/overview (see utils/stormSummary.js).
// These fields are not in the data contract (backend/agent/contracts.py) yet;
// when they are, read them from the advisory instead and delete this object.
export const STORM_FORECAST_PROTOTYPE = {
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
