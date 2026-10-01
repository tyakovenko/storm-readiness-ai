import { useEffect, useState } from "react";
import { askAgent, fetchOverview } from "../api.js";
import AgentReply from "../components/AgentReply.jsx";
import { Card, Sources, Stat, TierBadge, WaitingOnData } from "../components/ui.jsx";

// Screen 3: the staging plan, what-if controls, and a trust-checked AI explanation per county.
// The plan comes from the real solve_staging tool (via /api/overview); explanations come from
// the agent (/api/chat), so they pass the same trust checks as the chat.

const yesNo = (v) => (v === true ? "Yes" : v === false ? "No" : "Unknown");

export default function ResourcePlanner({ base, health }) {
  const defaultTrucks = base.staging.trucks_available;
  const [trucks, setTrucks] = useState(defaultTrucks);
  const [closed, setClosed] = useState([]);
  const [plan, setPlan] = useState(base);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [explanations, setExplanations] = useState({}); // county -> {loading} | {result} | {error}

  const isWhatIf = trucks !== defaultTrucks || closed.length > 0;

  useEffect(() => {
    if (!isWhatIf) {
      setPlan(base);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError("");
    fetchOverview({ maxTrucks: trucks, closed })
      .then((d) => !cancelled && setPlan(d))
      .catch((e) => !cancelled && setError(`Re-plan failed: ${e.message}`))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [trucks, closed, isWhatIf, base]);

  // Explanations describe one plan; clear them when the plan's inputs change.
  useEffect(() => {
    setExplanations({});
  }, [trucks, closed]);

  const s = plan.staging;
  const tierOf = Object.fromEntries(plan.impact.counties.map((c) => [c.fips, c.risk_tier]));
  const closedSet = new Set(s.shelters_closed);

  async function explain(county) {
    // The what-if goes into the question so the agent re-plans with the same inputs as this screen.
    const whatIf = [
      trucks !== defaultTrucks ? `We only have ${trucks} trucks.` : "",
      closed.length ? `${closed.join(" and ")} ${closed.length > 1 ? "are" : "is"} closed.` : "",
    ].filter(Boolean).join(" ");
    const question = `${whatIf} Explain the truck staging plan for ${county}.`.trim();
    setExplanations((e) => ({ ...e, [county]: { loading: true } }));
    try {
      const result = await askAgent(question);
      setExplanations((e) => ({ ...e, [county]: { result } }));
    } catch (err) {
      setExplanations((e) => ({ ...e, [county]: { error: err.message } }));
    }
  }

  const toggleShelter = (id) => setClosed((c) => (c.includes(id) ? c.filter((x) => x !== id) : [...c, id]));

  return (
    <div className="space-y-4">
      <Card
        title="What if…"
        action={isWhatIf && (
          <button type="button" className="text-sm font-semibold text-blue-700 hover:underline" onClick={() => { setTrucks(defaultTrucks); setClosed([]); }}>
            Reset to baseline
          </button>
        )}
      >
        <div className="flex flex-wrap gap-6">
          <label className="flex flex-col gap-1 text-sm font-medium text-slate-700">
            Trucks available
            <input
              type="number" min="0" max="99" value={trucks}
              onChange={(e) => setTrucks(e.target.value === "" ? 0 : Math.max(0, Number(e.target.value)))}
              className="w-28 rounded-lg border border-slate-300 px-3 py-2 text-base"
            />
          </label>
          <fieldset className="text-sm">
            <legend className="mb-1 font-medium text-slate-700">Mark shelters closed</legend>
            <div className="flex flex-wrap gap-3">
              {base.assets.shelters.map((sh) => (
                <label key={sh.id} className="flex items-center gap-1.5">
                  <input type="checkbox" checked={closed.includes(sh.id)} onChange={() => toggleShelter(sh.id)} />
                  {sh.id}
                </label>
              ))}
            </div>
          </fieldset>
        </div>
        {loading && <p className="mt-2 text-sm text-slate-500">Re-planning…</p>}
        {error && <p className="mt-2 text-sm text-red-800" role="alert">{error}</p>}
      </Card>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Staging area" value={s.staging_area} />
        <Stat label="Trucks available" value={s.trucks_available} />
        <Stat label="Unmet truckloads" value={s.total_truckloads_unmet} />
        <Stat
          label="Shelter beds"
          value={s.shelter_beds_available.toLocaleString()}
          sub={`Shortfall ${s.shelter_bed_shortfall.toLocaleString()} vs. estimated demand ${s.shelter_demand_estimate.toLocaleString()}*`}
        />
      </div>
      <p className="-mt-2 text-xs text-slate-600">* {s.shelter_demand_assumption}</p>

      <Card title="Recommended truck staging">
        <p className="mb-3 text-xs text-slate-500">Method: {s.method}</p>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-slate-200 text-xs uppercase text-slate-500">
              <tr>
                <th className="py-2 pr-3">County</th>
                <th className="py-2 pr-3">Risk</th>
                <th className="py-2 pr-3">Needed</th>
                <th className="py-2 pr-3">Assigned</th>
                <th className="py-2 pr-3">Unmet</th>
                <th className="py-2">AI explanation</th>
              </tr>
            </thead>
            <tbody>
              {s.allocations.map((a) => {
                const ex = explanations[a.county];
                return [
                  <tr key={a.fips} className="border-b border-slate-100">
                    <td className="py-2 pr-3 font-medium">{a.county}</td>
                    <td className="py-2 pr-3"><TierBadge tier={tierOf[a.fips]} /></td>
                    <td className="py-2 pr-3">{a.truckloads_needed}</td>
                    <td className="py-2 pr-3 font-semibold">{a.truckloads_assigned}</td>
                    <td className={`py-2 pr-3 ${a.truckloads_unmet ? "font-semibold text-red-800" : ""}`}>{a.truckloads_unmet}</td>
                    <td className="py-2">
                      <button
                        type="button" disabled={ex?.loading || loading} onClick={() => explain(a.county)}
                        className="rounded-lg border border-slate-300 px-3 py-1 text-sm font-semibold text-blue-700 hover:bg-slate-50 disabled:opacity-50"
                      >
                        {ex?.loading ? "Asking…" : ex?.result ? "Ask again" : "Explain with AI"}
                      </button>
                    </td>
                  </tr>,
                  ex && !ex.loading && (
                    <tr key={`${a.fips}-why`} className="border-b border-slate-100 bg-slate-50">
                      <td colSpan={6} className="p-3">
                        {ex.error ? <p className="text-sm text-red-800" role="alert">The agent failed: {ex.error}</p> : <AgentReply result={ex.result} />}
                      </td>
                    </tr>
                  ),
                ];
              })}
            </tbody>
          </table>
        </div>
        <p className="mt-2 text-xs text-slate-500">
          Explanations run the AI agent and its trust checks{health?.mock ? " (mock mode: scripted, free)" : ", which costs a little per click with a real model"}.
        </p>
      </Card>

      <Card title="Shelters">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-slate-200 text-xs uppercase text-slate-500">
              <tr>
                <th className="py-2 pr-3">Shelter</th>
                <th className="py-2 pr-3">Status</th>
                <th className="py-2 pr-3">Evacuation beds</th>
                <th className="py-2 pr-3">Generator</th>
                <th className="py-2 pr-3">Wheelchair</th>
                <th className="py-2 pr-3">Pets</th>
                <th className="py-2">In surge zone</th>
              </tr>
            </thead>
            <tbody>
              {plan.assets.shelters.map((sh) => (
                <tr key={sh.id} className={`border-b border-slate-100 ${closedSet.has(sh.id) ? "text-slate-400 line-through" : ""}`}>
                  <td className="py-2 pr-3"><span className="font-medium">{sh.id}</span> · {sh.name}</td>
                  <td className="py-2 pr-3">{closedSet.has(sh.id) ? "Closed (what-if)" : sh.status}</td>
                  <td className="py-2 pr-3">{sh.evacuation_capacity}</td>
                  <td className="py-2 pr-3">{yesNo(sh.generator)}</td>
                  <td className="py-2 pr-3">{yesNo(sh.wheelchair_accessible)}</td>
                  <td className="py-2 pr-3">{yesNo(sh.pets_allowed)}</td>
                  <td className="py-2">{yesNo(sh.in_surge_zone)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <div className="grid gap-4 lg:grid-cols-3">
        <WaitingOnData
          title="Resource types"
          needs="Crews, generators, water, personnel. The plan only has generic truckloads today, so the screen can't split them by type."
          source="solve_staging with a resource-type list (Workstream B)"
        />
        <WaitingOnData
          title="When to deploy"
          needs="Deployment times per county. No tool returns timing yet, and the trust layer can't check invented times, so none are shown."
          source="Optimizer output with timing + a trust check for times"
        />
        <WaitingOnData
          title="Staging location on the map"
          needs="Coordinates for the staging area. Only its name is in the data."
          source="FEMA distribution centers / staging sites"
        />
      </div>

      <Sources items={[s.source, plan.assets.source]} />
    </div>
  );
}
