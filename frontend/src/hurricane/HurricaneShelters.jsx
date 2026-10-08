import { useEffect, useMemo, useState } from "react";
import { PAGE, PageTitle } from "../components/Page.jsx";
import SectionHeading from "../components/SectionHeading.jsx";
import { fetchOverview, createPlan, approvePlan } from "../api.js";
import { CARD, LABEL, NOTE, fmt } from "../dallas/format.js";
import CountyMap from "./CountyMap.jsx";

// Shelters & what-ifs for one hurricane county agent: FEMA shelters, beds outside surge zones and
// floodplains, and re-plans when shelters can't open. Re-plan = plan_shelters + diff_plans on the
// backend, the same tools the agent calls.

const TH = "px-3 py-2 text-left text-[0.72rem] font-semibold uppercase tracking-[0.4px] text-muted";
const TD = "px-3 py-2 text-[0.82rem]";

// Local, tighter-than-shared-CARD metric tile for the top dashboard row (same pattern Storm
// Overview uses for its own compact metric row) -- the shared CARD below is kept for the
// what-if/save-approve cards, which stay their original size.
const TCARD = "rounded-md border border-line bg-surface px-3 py-2.5";
const TVALUE = "text-xl font-bold leading-[1.1] text-navy";

export default function HurricaneShelters({ overview: initial, agentId }) {
  const [overview, setOverview] = useState(initial);
  const [closed, setClosed] = useState([]);
  const [includeSurge, setIncludeSurge] = useState(false);
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  // Phase 2C: the saved/approved plan record for the CURRENT what-if, via the existing
  // Human-in-the-Loop plan_store endpoints -- cleared whenever the what-if changes, so a user
  // can never approve a plan whose shelter configuration no longer matches what's on screen.
  const [savedPlan, setSavedPlan] = useState(null);
  const [planBusy, setPlanBusy] = useState(false);
  const [planError, setPlanError] = useState("");
  const [confirmingApprove, setConfirmingApprove] = useState(false);
  const { plan, diff, assets, shelters, geo, county } = overview;

  // Phase 2C cleanup: this screen always shows the storm's one home county (StormShell never
  // passes a different county in), so the only time it actually changes is a genuine storm
  // switch (a new agentId) -- reset everything, including any saved/approved plan, so a plan
  // record from the PREVIOUS storm/county can never linger onscreen under the new one. An
  // incidental re-fetch of the SAME storm (e.g. Risk Map's horizon resolving in the background)
  // doesn't touch agentId, so it correctly leaves an in-progress what-if/plan alone.
  useEffect(() => {
    setOverview(initial);
    setClosed([]);
    setIncludeSurge(false);
    setQuery("");
    setError("");
    setSavedPlan(null);
    setPlanError("");
    setConfirmingApprove(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [agentId]);

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
      setSavedPlan(null);
      setConfirmingApprove(false);
      setPlanError("");
    } catch (e) {
      setError(`Re-plan failed: ${e.message}`);
    } finally {
      setBusy(false);
    }
  }

  async function saveDraft() {
    if (planBusy) return;
    setPlanBusy(true);
    setPlanError("");
    try {
      const saved = await createPlan({
        agentId, county,
        inputs: { exclude_surge_and_floodplain: !includeSurge, unavailable_shelters: closed },
        allocations: {
          beds_available: plan.beds_available, shelters_open: plan.shelters_open,
          water_gallons_needed: plan.water_gallons_needed, generators_kw_needed: plan.generators_kw_needed,
          personnel_needed: plan.personnel_needed,
        },
      });
      setSavedPlan(saved);
    } catch (e) {
      setPlanError(`Save failed: ${e.message}`);
    } finally {
      setPlanBusy(false);
    }
  }

  async function confirmApproval() {
    if (planBusy || !savedPlan) return;
    setPlanBusy(true);
    setPlanError("");
    try {
      setSavedPlan(await approvePlan(savedPlan.plan_id));
      setConfirmingApprove(false);
    } catch (e) {
      setPlanError(`Approval failed: ${e.message}`);
    } finally {
      setPlanBusy(false);
    }
  }

  const largest = [...shelters].sort((a, b) => (b.evacuation_capacity ?? 0) - (a.evacuation_capacity ?? 0)).slice(0, 25);

  const hasResourceEstimate = plan.water_gallons_needed != null && plan.generators_kw_needed != null && plan.personnel_needed != null;

  return (
    <section className={PAGE}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <PageTitle>Resource Planner — {county}</PageTitle>
        <span className="rounded bg-[#e8ecf1] px-2 py-[2px] text-[0.68rem] font-semibold text-[#3b4452]">Model-derived estimate</span>
      </div>

      {/* Phase 2C: water_gallons_needed/generators_kw_needed/personnel_needed already come back
          from the existing plan_shelters tool (backend/agent/hurricane_tools.py) but were never
          shown -- no new calculation, just surfacing what the backend already computes from
          affected population (CDC SVI). Labeled explicitly as a model estimate, never an
          allocation/approved plan (see PlanApprovalResult for that). Merged into one compact
          dashboard row with the FEMA shelter-capacity metrics below -- same two groups, same
          independent "not available yet" fallback for the resource-estimate trio, just one grid. */}
      <section>
        <SectionHeading title="Resource & shelter metrics"
          subtitle="Commodity needs estimated from affected population; shelter capacity from the current what-if -- neither is an approved allocation or deployed plan" />
        <div className="mt-3 grid grid-cols-4 gap-2.5 max-[1000px]:grid-cols-3 max-[680px]:grid-cols-2 max-[420px]:grid-cols-1">
          {hasResourceEstimate && (
            <>
              <div className={TCARD}>
                <div className={LABEL}>Water needed</div>
                <div className={TVALUE}>{fmt(plan.water_gallons_needed)} gal</div>
              </div>
              <div className={TCARD}>
                <div className={LABEL}>Generator capacity needed</div>
                <div className={TVALUE}>{fmt(plan.generators_kw_needed)} kW</div>
              </div>
              <div className={TCARD}>
                <div className={LABEL}>Personnel needed</div>
                <div className={TVALUE}>{fmt(plan.personnel_needed)}</div>
              </div>
            </>
          )}
          <div className={TCARD}>
            <div className={LABEL}>Beds available</div>
            <div className={TVALUE}>{fmt(plan.beds_available)}</div>
            {diff && <div className={NOTE}>default plan: {fmt(diff.beds_before)}</div>}
          </div>
          <div className={TCARD}>
            <div className={LABEL}>Shelters open</div>
            <div className={TVALUE}>{fmt(plan.shelters_open)}</div>
            <div className={NOTE}>of {fmt(assets.shelters_total)} FEMA shelters</div>
          </div>
          <div className={TCARD}>
            <div className={LABEL}>Beds that take pets</div>
            <div className={TVALUE}>{fmt(plan.beds_with_pets)}</div>
          </div>
          <div className={TCARD}>
            <div className={LABEL}>Beds with a generator</div>
            <div className={TVALUE}>{fmt(plan.beds_with_generator)}</div>
          </div>
        </div>
        {!hasResourceEstimate && <p className={`${NOTE} mt-2`}>Resource estimates aren&rsquo;t available for {county} yet.</p>}
        {hasResourceEstimate && (
          <p className={`${NOTE} mt-2`}>
            {plan.method} Driven by affected population, not by which shelters are open -- the shelter
            what-if controls below change available shelter capacity, not these overall water, generator or
            personnel requirements.
          </p>
        )}
        <p className={`${NOTE} mt-1`}>Shelter demand: {plan.shelter_demand}.</p>
      </section>

      <section className="mt-5 grid grid-cols-[3fr_2fr] gap-4 max-[900px]:grid-cols-1">
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

      <section className="mt-5">
        <SectionHeading title="Shelter what-if controls"
          subtitle="Changes available shelter capacity above -- does not recalculate overall water, generator or personnel requirements" />
        <div className={`${CARD} mt-3 flex flex-wrap items-end gap-5`}>
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
      </section>

      {/* Phase 2C: reuses the existing Human-in-the-Loop plan_store (create_plan/update_plan) via
          /api/plans -- no new persistence or approval logic. Saving records this exact what-if
          as a draft; approving only records sign-off for execution planning, never deployment. */}
      <section className="mt-5">
        <SectionHeading title="Save & approve this plan" subtitle="Human-in-the-loop record for the current shelter configuration" />
        <div className={`${CARD} mt-3 flex flex-wrap items-center gap-3`}>
          <button type="button" disabled={planBusy} onClick={saveDraft}
            className="cursor-pointer rounded border border-line px-3.5 py-2 text-[0.85rem] font-semibold text-navy hover:bg-canvas disabled:cursor-not-allowed disabled:opacity-50">
            {planBusy && !savedPlan ? "Saving…" : "Save draft"}
          </button>
          {savedPlan && (
            <span className="text-[0.85rem]">
              Plan <span className="font-mono font-semibold text-navy">{savedPlan.plan_id}</span> — status:{" "}
              <span className="font-semibold text-navy">{savedPlan.status}</span>
            </span>
          )}
          {savedPlan && savedPlan.status !== "approved" && !confirmingApprove && (
            <button type="button" disabled={planBusy} onClick={() => setConfirmingApprove(true)}
              className="cursor-pointer rounded border border-accent px-3.5 py-2 text-[0.85rem] font-semibold text-accent hover:bg-[#e8f0f8] disabled:cursor-not-allowed disabled:opacity-50">
              Approve plan
            </button>
          )}
          {confirmingApprove && (
            <span className="flex flex-wrap items-center gap-2 rounded bg-warn-bg px-3 py-2 text-[0.82rem] text-warn-text">
              Confirm approval? This records sign-off for execution planning only -- it does not dispatch or
              deploy any actual resources.
              <button type="button" disabled={planBusy} onClick={confirmApproval}
                className="cursor-pointer rounded bg-warn-text px-2.5 py-1 font-semibold text-white disabled:opacity-50">
                {planBusy ? "Approving…" : "Confirm approval"}
              </button>
              <button type="button" disabled={planBusy} onClick={() => setConfirmingApprove(false)}
                className="cursor-pointer rounded border border-line bg-surface px-2.5 py-1 font-semibold text-navy">
                Cancel
              </button>
            </span>
          )}
          {savedPlan?.status === "approved" && (
            <span className="rounded bg-[#e8ecf1] px-2 py-[2px] text-[0.72rem] font-semibold text-[#3b4452]">
              Approved for execution planning — not a confirmation that resources have been deployed
            </span>
          )}
        </div>
        {planError && <p className="mt-2 rounded bg-bad-bg px-3 py-2 text-[0.85rem] text-bad-text" role="alert">{planError}</p>}
      </section>
    </section>
  );
}
