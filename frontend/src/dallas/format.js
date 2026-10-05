// Numbers exactly as the backend gives them (no rounding the trust layer would reject in chat).
export function fmt(v, digits) {
  if (v == null) return "—";
  const n = Number(v);
  return digits == null ? n.toLocaleString("en-US") : n.toLocaleString("en-US", { maximumFractionDigits: digits });
}

// "950–1,314 (median 1,200, n=3)": an estimate is never shown without its range.
export function rangeText(r) {
  if (!r) return "no data";
  return `${fmt(r.low, 1)}–${fmt(r.high, 1)} (median ${fmt(r.median, 1)}, n=${r.n})`;
}

export const CARD = "rounded-md border border-line bg-surface px-4 py-3.5";
export const LABEL = "text-[0.68rem] font-semibold uppercase tracking-[0.4px] text-muted";
export const BIG = "text-2xl font-bold leading-[1.1] text-navy";
export const NOTE = "text-[0.78rem] text-muted";

export const SECTORS = {
  transport: "Streets & signals",
  water: "Water",
  shelter: "Shelter transport",
  heat_housing: "No heat",
  animals_weather: "Animals in cold",
  trees_debris: "Trees & debris",
};
