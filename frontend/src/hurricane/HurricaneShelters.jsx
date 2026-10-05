import { useMemo, useState } from "react";
import { PAGE, PageTitle } from "../components/Page.jsx";
import SectionHeading from "../components/SectionHeading.jsx";
import { fetchOverview } from "../api.js";
import { BIG, CARD, LABEL, NOTE, fmt } from "../dallas/format.js";
import CountyMap from "./CountyMap.jsx";

// Shelters & what-ifs for one hurricane county agent: FEMA shelters, beds outside surge zones and
// floodplains, and re-plans when shelters can't open. Re-plan = plan_shelters + diff_plans on the
// backend, the same tools the agent calls.

const TH = "px-3 py-2 text-left text-[0.72rem] font-semibold uppercase tracking-[0.4px] text-muted";
const TD = "px-3 py-2 text-[0.82rem]";

export default function HurricaneShelters({ overview: initial, agentId }) {
  const [overview, setOverview] = useState(initial);
  const [closed, setClosed] = useState([]);
  const [includeSurge, setIncludeSurge] = useState(false);
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const { plan, diff, assets, shelters, geo, county, gaps } = overview;

  const matches = useMemo(() => {
    const q = query.trim().toLowerCase();
    return q.length < 2 ? [] : shelters.filter((s) => s.name.toLowerCase().includes(q) && !closed.includes(s.name)).slice(0, 8);
  }, [query, shelters, closed]);

  async function replan(nextClosed, nextSurge) {
    setBusy(true);
    setError("");
    try {
      setOverview(await fetchOverview({ closed: nextClosed, include_surge: nextSurge }, agentId));
      setClosed(nextClosed);
      setIncludeSurge(nextSurge);
    } catch (e) {
      setError(`Re-plan failed: ${e.message}`);
    } finally {
      setBusy(false);
    }
  }

  const largest = [...shelters].sort((a, b) => (b.evacuation_capacity ?? 0) - (a.evacuation_capacity ?? 0)).slice(0, 25);

  return (
    <section className={PAGE}>
      <PageTitle>Shelters — {county}</PageTitle>

      <div className={`${CARD} flex flex-wrap items-end gap-5`}>
        <label className="flex flex-col gap-1">
          <span className={LABEL}>Mark a shelter unavailable</span>
          <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search shelter name…"
            className="w-72 rounded border border-line px-2 py-1.5 text-[0.9rem]" />
          {matches.length > 0 && (
            <ul className="w-72 rounded border border-line bg-surface text-[0.82rem]">
              {matches.map((s) => (
                <li key={s.id}>
                  <button type="button" disabled={busy} className="w-full cursor-pointer px-2 py-1 text-left hover:bg-canvas"
                    onClick={() => { setQuery(""); replan([...closed, s.name], includeSurge); }}>
                    {s.name} <span className="text-muted">({s.evacuation_capacity ?? "?"} beds)</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </label>
        <label className="flex items-center gap-2 text-[0.85rem]">
          <input type="checkbox" checked={includeSurge} disabled={busy} onChange={(e) => replan(closed, e.target.checked)} />
          Include surge-zone and floodplain shelters
        </label>
        <button type="button" disabled={busy || (!closed.length && !includeSurge)} onClick={() => replan([], false)}
          className="cursor-pointer rounded border border-line px-3.5 py-2 text-[0.85rem] font-semibold text-navy hover:bg-canvas">
          Reset
        </button>
        {closed.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {closed.map((n) => (
              <span key={n} className="rounded bg-bad-bg px-2 py-[2px] text-[0.75rem] font-semibold text-bad-text">
                {n}{" "}
                <button type="button" aria-label={`Reopen ${n}`} className="cursor-pointer" disabled={busy}
                  onClick={() => replan(closed.filter((x) => x !== n), includeSurge)}>×</button>
              </span>
            ))}
          </div>
        )}
      </div>
      {error && <p className="mt-2 rounded bg-bad-bg px-3 py-2 text-[0.85rem] text-bad-text" role="alert">{error}</p>}

      <div className="mt-4 grid grid-cols-4 gap-3 max-[900px]:grid-cols-2">
        <div className={CARD}>
          <div className={LABEL}>Beds available</div>
          <div className={BIG}>{fmt(plan.beds_available)}</div>
          {diff && <div className={NOTE}>default plan: {fmt(diff.beds_before)}</div>}
        </div>
        <div className={CARD}>
          <div className={LABEL}>Shelters open</div>
          <div className={BIG}>{fmt(plan.shelters_open)}</div>
          <div className={NOTE}>of {fmt(assets.shelters_total)} FEMA shelters in the county</div>
        </div>
        <div className={CARD}>
          <div className={LABEL}>Beds that take pets</div>
          <div className={BIG}>{fmt(plan.beds_with_pets)}</div>
        </div>
        <div className={CARD}>
          <div className={LABEL}>Beds with a generator</div>
          <div className={BIG}>{fmt(plan.beds_with_generator)}</div>
        </div>
      </div>
      <p className={`${NOTE} mt-2`}>Shelter demand: {plan.shelter_demand}. {plan.method}</p>

      <section className="mt-6 grid grid-cols-[3fr_2fr] gap-4 max-[900px]:grid-cols-1">
        <div>
          <SectionHeading title="Shelter map" subtitle="Dot size = evacuation beds" />
          <div className="mt-3.5"><CountyMap geo={geo} shelters={shelters} closed={closed} /></div>
        </div>
        <div>
          <SectionHeading title="Largest shelters" subtitle="FEMA National Shelter System" />
          <div className={`${CARD} mt-3.5 max-h-[460px] overflow-y-auto p-0`}>
            <table className="w-full">
              <thead className="sticky top-0 bg-surface">
                <tr><th className={TH}>Shelter</th><th className={TH}>Beds</th><th className={TH}>Flags</th></tr>
              </thead>
              <tbody>
                {largest.map((s) => (
                  <tr key={s.id} className={`border-t border-line ${closed.includes(s.name) ? "opacity-50" : ""}`}>
                    <td className={TD}>{s.name}<span className="block text-[0.72rem] text-muted">{s.city}</span></td>
                    <td className={TD}>{s.evacuation_capacity ?? "—"}</td>
                    <td className={`${TD} text-[0.72rem]`}>
                      {[s.in_surge_zone && "surge", s.in_100yr_floodplain && "floodplain", s.generator && "generator",
                        s.pets && !/no/i.test(s.pets) && "pets"].filter(Boolean).join(" • ") || "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </section>

      <section className="mt-6">
        <SectionHeading title="Not covered yet" subtitle="Local data the research layer will add for this county" />
        <ul className="mt-2 list-disc pl-5 text-[0.85rem] text-muted">{gaps.map((g) => <li key={g.metric}>{g.metric}</li>)}</ul>
      </section>
    </section>
  );
}
