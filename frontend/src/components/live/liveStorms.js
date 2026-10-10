// Pure helpers for the Live Operations storm map and cards (no React, no Leaflet).

// Saffir-Simpson thresholds in knots; colors tuned for the dark map.
const CATEGORIES = [
  { level: -1, min: 0, short: "TD", label: "Tropical Depression", color: "#7dd3fc" },
  { level: 0, min: 34, short: "TS", label: "Tropical Storm", color: "#5eead4" },
  { level: 1, min: 64, short: "Cat 1", label: "Category 1 Hurricane", color: "#fde047" },
  { level: 2, min: 83, short: "Cat 2", label: "Category 2 Hurricane", color: "#fdba74" },
  { level: 3, min: 96, short: "Cat 3", label: "Category 3 Hurricane", color: "#f87171" },
  { level: 4, min: 113, short: "Cat 4", label: "Category 4 Hurricane", color: "#f472b6" },
  { level: 5, min: 137, short: "Cat 5", label: "Category 5 Hurricane", color: "#c084fc" },
];

export function categoryFor(kt) {
  const v = Number(kt) || 0;
  return [...CATEGORIES].reverse().find((c) => v >= c.min) ?? CATEGORIES[0];
}

// NHC CurrentStorms.json classification codes.
const CLASSIFICATIONS = {
  HU: "Hurricane", TS: "Tropical Storm", TD: "Tropical Depression", STS: "Subtropical Storm",
  SS: "Subtropical Storm", SD: "Subtropical Depression", PTC: "Potential Tropical Cyclone", PC: "Post-Tropical Cyclone",
};
export const classificationLabel = (code) => CLASSIFICATIONS[String(code ?? "").toUpperCase()] ?? code ?? "Storm";

const BASINS = { AL: "Atlantic", EP: "East Pacific", CP: "Central Pacific" };
export const basinLabel = (stormId) => BASINS[String(stormId ?? "").slice(0, 2).toUpperCase()] ?? "";

const COMPASS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"];
export const compass = (deg) => (deg == null ? "—" : COMPASS[Math.round(((Number(deg) % 360) + 360) % 360 / 22.5) % 16]);

export const ktToMph = (kt) => Math.round(Number(kt) * 1.15078);
export const mphToKt = (mph) => Math.round(Number(mph) / 1.15078);

export function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

const R_NM = 3440.065;
const rad = (d) => (d * Math.PI) / 180;
function destination(lat, lon, bearingDeg, distNm) {
  const d = distNm / R_NM;
  const b = rad(bearingDeg);
  const p1 = rad(lat);
  const p2 = Math.asin(Math.sin(p1) * Math.cos(d) + Math.cos(p1) * Math.sin(d) * Math.cos(b));
  const l2 = rad(lon) + Math.atan2(Math.sin(b) * Math.sin(d) * Math.cos(p1), Math.cos(d) - Math.sin(p1) * Math.sin(p2));
  return { lat: (p2 * 180) / Math.PI, lon: (l2 * 180) / Math.PI };
}

// Current NHC position, then the official forecast points valid after it. With no official
// track, a 24h straight-line projection of current motion, flagged `extrapolated` (not a forecast).
// Memoized per (storm, track) object pair so Leaflet layers keep stable inputs.
const cache = new WeakMap();
export function positionsFor(storm, track) {
  const key = track ?? storm;
  const hit = cache.get(storm)?.get(key);
  if (hit) return hit;

  const nowMs = Date.parse(storm.last_update_utc) || Date.now();
  const current = { lat: storm.lat, lon: storm.lon, vmax_kt: storm.intensity_kt, ms: nowMs, tau_h: null };
  let out;
  if (track?.points?.length) {
    out = [current, ...track.points
      .map((p) => ({ ...p, ms: Date.parse(p.valid_utc) }))
      .filter((p) => p.ms > nowMs)];
  } else if (storm.movement_speed_mph > 0 && storm.movement_dir_deg != null) {
    const kt = mphToKt(storm.movement_speed_mph);
    out = [current, ...[12, 24].map((h) => ({
      ...destination(storm.lat, storm.lon, storm.movement_dir_deg, kt * h),
      vmax_kt: storm.intensity_kt, ms: nowMs + h * 3.6e6, tau_h: h, extrapolated: true,
    }))];
  } else {
    out = [current];
  }

  if (!cache.has(storm)) cache.set(storm, new WeakMap());
  cache.get(storm).set(key, out);
  return out;
}
