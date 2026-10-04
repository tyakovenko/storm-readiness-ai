// TEMPORARY mock for the Resource Planner's "Resource Requirements"
// summary. There is no resource-planning/optimizer endpoint yet. The
// backend already has a conceptually similar optimizer — solve_staging in
// backend/agent/tools.py (contract: StagingPlan / Allocation in
// backend/agent/contracts.py) — which allocates truckloads and shelter
// beds today. A future endpoint for this screen would likely sit at the
// end of that same pipeline (impact predictions -> optimizer -> resource
// recommendations). This file only mocks the OUTPUT shape such a backend
// would hand the UI; no planning or optimization logic lives here or
// anywhere else in the frontend.
//
// Storm identity (name, advisory number) and operational context
// (planning window, counties at risk) come from the backend via
// /api/overview, the same source as the Storm Overview — see
// pages/ResourcePlanner.jsx.
export const RESOURCE_REQUIREMENTS_MOCK = [
  { type: "utility_crews", label: "Utility Crews", quantity: 24, unit: "crews", sublabel: "Recommended" },
  { type: "generators", label: "Generators", quantity: 18, unit: "units", sublabel: "Recommended" },
  { type: "shelter_capacity", label: "Shelter Capacity", quantity: 1250, unit: "people", sublabel: "People" },
  { type: "emergency_vehicles", label: "Emergency Vehicles", quantity: 12, unit: "vehicles", sublabel: "Recommended" },
];

// Shared resource-type -> display label lookup, derived from the summary
// above so "Recommended Deployments" never has to repeat these strings.
export const RESOURCE_TYPE_LABELS = Object.fromEntries(
  RESOURCE_REQUIREMENTS_MOCK.map((r) => [r.type, r.label]),
);

// TEMPORARY mock for "Recommended Deployments" and the "Resource Staging
// Map" below it. Same caveats as above: no optimizer endpoint yet, this
// only mocks the output shape. `priority` and `riskTier` are kept as
// separate fields on purpose — how urgently a county should be staged is a
// planning decision, not simply a restatement of how severely it's
// predicted to be hit, even though they agree here. `rationale` is
// plain-text bullets so a future agent-generated explanation can replace
// them with no change to how DeploymentList renders them (and note this is
// static mock data read once, not an /api/chat call per row).
//
// IMPACT AREA vs STAGING LOCATION are deliberately different places:
// `impactAreaLocation` is an approximate county centroid (where damage is
// predicted), while `stagingLocation` is a nearby inland city used as a
// stand-in operational staging hub — not a verified real emergency staging
// facility. `whyThisLocation` intentionally avoids words like "safest",
// "optimal", or "best": we don't have verified facility capacity, road
// conditions, or closure predictions to back up a claim that strong, so it
// only describes the staging logic in general terms.
//
// Resource-total sanity check against RESOURCE_REQUIREMENTS_MOCK (24
// crews / 18 generators / 12 vehicles): these three deployments use
// 20 crews, 15 generators, and 5 vehicles — within budget, with the
// remainder held in reserve rather than fully allocated. The map and the
// deployment table both read `resources` off these same objects, so the
// two sections can never disagree on quantities.
export const RECOMMENDED_DEPLOYMENTS_MOCK = [
  {
    id: "dixie-001",
    county: "Dixie County",
    state: "FL",
    fips: "12029",
    priority: "high",
    riskTier: "high",
    predictedOutagePct: 47,
    deployBeforeLandfallHours: 18,
    resources: [
      { type: "utility_crews", quantity: 8 },
      { type: "generators", quantity: 6 },
      { type: "emergency_vehicles", quantity: 2 },
    ],
    rationale: [
      "47% predicted customer outage",
      "High forecast wind exposure",
      "Approximately 18,400 customers served",
      "Resources should arrive before deteriorating road conditions",
    ],
    targetAreas: ["Dixie County"],
    // Approximate Dixie County, FL centroid — map context only, not a
    // predicted damage polygon.
    impactAreaLocation: { latitude: 29.68, longitude: -83.15 },
    stagingLocation: {
      id: "staging-dixie-001",
      name: "Gainesville Operations Staging Area",
      city: "Gainesville",
      state: "FL",
      latitude: 29.6516,
      longitude: -82.3248,
    },
    whyThisLocation: [
      "Positioned outside the highest predicted impact area",
      "Provides inland access toward Dixie County",
      "Supports pre-landfall resource positioning",
    ],
  },
  {
    id: "levy-001",
    county: "Levy County",
    state: "FL",
    fips: "12075",
    priority: "high",
    riskTier: "high",
    predictedOutagePct: 38,
    deployBeforeLandfallHours: 12,
    resources: [
      { type: "utility_crews", quantity: 7 },
      { type: "generators", quantity: 5 },
      { type: "emergency_vehicles", quantity: 2 },
    ],
    rationale: [
      "38% predicted customer outage",
      "High forecast wind exposure",
      "Coastal surge exposure increases restoration time",
    ],
    targetAreas: ["Levy County"],
    // Approximate Levy County, FL centroid — map context only.
    impactAreaLocation: { latitude: 29.3, longitude: -82.78 },
    stagingLocation: {
      id: "staging-levy-001",
      name: "Ocala Staging Area",
      city: "Ocala",
      state: "FL",
      latitude: 29.1872,
      longitude: -82.1401,
    },
    whyThisLocation: [
      "Positioned outside the highest predicted impact area",
      "Provides inland access toward Levy County",
      "Supports pre-landfall resource positioning",
    ],
  },
  {
    id: "taylor-001",
    county: "Taylor County",
    state: "FL",
    fips: "12123",
    priority: "moderate",
    riskTier: "moderate",
    predictedOutagePct: 24,
    deployBeforeLandfallHours: 8,
    resources: [
      { type: "utility_crews", quantity: 5 },
      { type: "generators", quantity: 4 },
      { type: "emergency_vehicles", quantity: 1 },
    ],
    rationale: [
      "24% predicted customer outage",
      "Moderate forecast wind exposure",
      "Rural grid infrastructure increases restoration time",
    ],
    targetAreas: ["Taylor County"],
    // Approximate Taylor County, FL centroid — map context only.
    impactAreaLocation: { latitude: 30.07, longitude: -83.55 },
    stagingLocation: {
      id: "staging-taylor-001",
      name: "Tallahassee Staging Area",
      city: "Tallahassee",
      state: "FL",
      latitude: 30.4383,
      longitude: -84.2807,
    },
    whyThisLocation: [
      "Positioned outside the highest predicted impact area",
      "Provides inland access toward Taylor County",
      "Supports pre-landfall resource positioning",
    ],
  },
];
