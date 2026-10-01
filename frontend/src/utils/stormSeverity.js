// Maps a hurricane category to one of the app's risk levels, so severity
// is always shown with the shared risk color system, never ad hoc colors.
const SEVERITY_COLOR_VAR = {
  low: "var(--risk-low)",
  moderate: "var(--risk-moderate)",
  high: "var(--risk-high)",
  severe: "var(--risk-severe)",
};

// Leaflet renders markers to SVG/canvas and can't resolve CSS custom
// properties, so this mirrors the --risk-* tokens in App.css as literal
// hex values for map use only. Keep these two palettes in sync.
const SEVERITY_COLOR_HEX = {
  low: "#2e7d32",
  moderate: "#c98a00",
  high: "#d9641e",
  severe: "#c62828",
};

export function getStormSeverityLevel(category) {
  if (category >= 4) return "severe";
  if (category === 3) return "high";
  if (category >= 1) return "moderate";
  return "low";
}

export function getStormSeverityColor(category) {
  return SEVERITY_COLOR_VAR[getStormSeverityLevel(category)];
}

export function getStormSeverityHex(category) {
  return SEVERITY_COLOR_HEX[getStormSeverityLevel(category)];
}
