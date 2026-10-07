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

export const CARD = "rounded-2xl border border-line bg-surface p-5 ocean-card-shadow ocean-card-hover";
export const LABEL = "text-[0.7rem] font-bold uppercase tracking-[0.06em] text-accent";
export const BIG = "text-2xl sm:text-[1.85rem] font-extrabold leading-tight text-navy font-heading";
export const NOTE = "text-[0.82rem] text-muted leading-relaxed";

export const SECTORS = {
  transport: "Streets & signals",
  water: "Water",
  shelter: "Shelter transport",
  heat_housing: "No heat",
  animals_weather: "Animals in cold",
  trees_debris: "Trees & debris",
};
