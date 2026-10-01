// Small shared building blocks for the dashboard screens.

// The four tiers from the proposal. Every badge shows the tier name too, so
// risk is never communicated by color alone.
export const TIERS = {
  red: { label: "Red", color: "#c62828", badge: "bg-red-100 text-red-900 ring-red-300" },
  orange: { label: "Orange", color: "#e65100", badge: "bg-orange-100 text-orange-900 ring-orange-300" },
  yellow: { label: "Yellow", color: "#f9a825", badge: "bg-yellow-100 text-yellow-900 ring-yellow-300" },
  green: { label: "Green", color: "#2e7d32", badge: "bg-green-100 text-green-900 ring-green-300" },
};
export const NO_PREDICTION_COLOR = "#9aa3ae";

export function TierBadge({ tier }) {
  const t = TIERS[tier];
  if (!t) return null;
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-semibold ring-1 ${t.badge}`}>
      <span className="size-2 rounded-full" style={{ background: t.color }} aria-hidden="true" />
      {t.label}
    </span>
  );
}

export function Card({ title, action, children, className = "" }) {
  return (
    <section className={`rounded-xl border border-slate-200 bg-white p-4 shadow-sm ${className}`}>
      {(title || action) && (
        <div className="mb-3 flex items-center justify-between gap-2">
          {title && <h2 className="text-base font-semibold text-slate-900">{title}</h2>}
          {action}
        </div>
      )}
      {children}
    </section>
  );
}

export function Stat({ label, value, sub }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-1 text-2xl font-bold text-slate-900">{value}</div>
      {sub && <div className="mt-1 text-sm text-slate-600">{sub}</div>}
    </div>
  );
}

// A slot for something the screens need but the data contract doesn't provide yet.
// Shown instead of invented numbers, and names what's missing so the team can fill it.
export function WaitingOnData({ title, needs, source }) {
  return (
    <section className="rounded-xl border-2 border-dashed border-slate-300 bg-slate-50 p-4">
      <div className="flex items-center gap-2">
        <h2 className="text-base font-semibold text-slate-700">{title}</h2>
        <span className="rounded-full bg-slate-200 px-2 py-0.5 text-xs font-semibold text-slate-700">
          Waiting on data
        </span>
      </div>
      <p className="mt-2 text-sm text-slate-600">{needs}</p>
      {source && <p className="mt-1 text-xs text-slate-500">Planned source: {source}</p>}
    </section>
  );
}

export function Sources({ items }) {
  return (
    <details className="text-sm text-slate-600">
      <summary>Sources</summary>
      <ul className="mt-2 list-disc space-y-1 pl-5">
        {[...new Set(items.filter(Boolean))].map((s) => <li key={s}>{s}</li>)}
      </ul>
    </details>
  );
}

export const pctRange = (q) => `${q.median}% (range ${q.low}–${q.high}%)`;
export const formatUtc = (iso) => iso.replace("T", " ").replace(/Z$/, " UTC");
