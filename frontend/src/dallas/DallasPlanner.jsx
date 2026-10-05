import { useState } from "react";
import { PAGE, PageTitle } from "../components/Page.jsx";
import SectionHeading from "../components/SectionHeading.jsx";
import { fetchOverview } from "../api.js";
import DistrictMap from "./DistrictMap.jsx";
import { BIG, CARD, LABEL, NOTE, fmt, rangeText } from "./format.js";

// Resource Planner for Dallas: sanding trucks by council district and shelter
// beds vs documented demand, with what-ifs (fewer trucks, shelters closed).
// The what-if re-runs plan_response/diff_plans on the backend - same as the agent.

const TH = "px-3 py-2 text-left text-[0.72rem] font-semibold uppercase tracking-[0.4px] text-muted";
const TD = "px-3 py-2 text-[0.85rem]";

function WhatIf({ shelters, trucks, closed, busy, onApply, onReset }) {
  const [t, setT] = useState(trucks);
  const [c, setC] = useState(new Set(closed));
  const toggle = (id) => setC((prev) => { const n = new Set(prev); n.has(id) ? n.delete(id) : n.add(id); return n; });
  return (
    <div className={`${CARD} flex flex-wrap items-end gap-5`}>
      <label className="flex flex-col gap-1">
        <span className={LABEL}>Sanding trucks available</span>
        <input type="number" min={0} max={200} value={t} onChange={(e) => setT(Math.max(0, Number(e.target.value)))}
          className="w-28 rounded border border-line px-2 py-1.5 text-[0.95rem]" />
      </label>
      <fieldset className="flex flex-col gap-1">
        <legend className={LABEL}>Shelters unavailable</legend>
        <div className="flex flex-wrap gap-3">
          {shelters.map((s) => (
            <label key={s.id} className="flex items-center gap-1.5 text-[0.85rem]">
              <input type="checkbox" checked={c.has(s.id)} onChange={() => toggle(s.id)} />
              {s.name}
            </label>
          ))}
        </div>
      </fieldset>
      <div className="flex gap-2">
        <button type="button" disabled={busy} onClick={() => onApply(t, [...c])}
          className="cursor-pointer rounded bg-accent px-3.5 py-2 text-[0.85rem] font-semibold text-white hover:bg-accent-dark">
          {busy ? "Re-planning…" : "Re-plan"}
        </button>
        <button type="button" disabled={busy} onClick={() => { setT(50); setC(new Set()); onReset(); }}
          className="cursor-pointer rounded border border-line px-3.5 py-2 text-[0.85rem] font-semibold text-navy hover:bg-canvas">
          Reset
        </button>
      </div>
    </div>
  );
}

export default function DallasPlanner({ overview: initial, agentId = null }) {
  const [overview, setOverview] = useState(initial);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState(null);
  const { plan, diff, assets, alert, districts } = overview;

  async function replan(trucks, closed) {
    setBusy(true);
    setError("");
    try {
      setOverview(await fetchOverview({ max_trucks: trucks, closed }, agentId));
    } catch (e) {
      setError(`Re-plan failed: ${e.message}`);
    } finally {
      setBusy(false);
    }
  }

  const change = Object.fromEntries((diff?.district_changes ?? []).map((c) => [c.district, c.change]));
  const trucksBy = Object.fromEntries(plan.truck_allocation.map((a) => [a.district, a.trucks]));
  const dem = plan.shelter_demand;
  const staff = assets.department_staff.rows;

  return (
    <section className={PAGE}>
      <PageTitle>Resource Planner — Dallas County</PageTitle>
      <p className="mb-4 text-[0.85rem] text-muted">
        {alert.kind === "scenario" ? "Planning scenario" : "Live alert"} • {plan.trucks_available} trucks •{" "}
        {plan.shelters_closed.length ? `closed: ${plan.shelters_closed.join(", ")}` : "all shelters open"}
      </p>

      <WhatIf shelters={assets.shelters} trucks={plan.trucks_available} closed={plan.shelters_closed} busy={busy}
        onApply={replan} onReset={() => replan(undefined, [])} />
      {error && <p className="mt-2 rounded bg-bad-bg px-3 py-2 text-[0.85rem] text-bad-text" role="alert">{error}</p>}

      <div className="mt-4 grid grid-cols-4 gap-3 max-[900px]:grid-cols-2">
        <div className={CARD}>
          <div className={LABEL}>Trucks available</div>
          <div className={BIG}>{fmt(plan.trucks_available)}</div>
          {diff && <div className={NOTE}>default plan: {fmt(diff.baseline.trucks_available)}</div>}
        </div>
        <div className={CARD}>
          <div className={LABEL}>Known shelter beds</div>
          <div className={BIG}>{fmt(plan.shelter_beds_known)}</div>
          {diff && <div className={NOTE}>default plan: {fmt(diff.shelter_beds_before)}</div>}
          {plan.shelters_unknown_capacity.length > 0 && (
            <div className={NOTE}>+ no published capacity: {plan.shelters_unknown_capacity.join(", ")}</div>
          )}
        </div>
        <div className={CARD}>
          <div className={LABEL}>Shelter demand (people/day)</div>
          <div className={BIG}>{dem ? `${fmt(dem.low)}–${fmt(dem.high)}` : "—"}</div>
          <div className={NOTE}>{dem ? `median ${fmt(dem.median)}, n=${dem.n}` : ""}</div>
        </div>
        <div className={`${CARD} ${plan.shelter_shortfall_at_median > 0 ? "border-risk-severe bg-risk-severe-bg" : ""}`}>
          <div className={LABEL}>Bed shortfall</div>
          <div className={BIG}>{fmt(plan.shelter_shortfall_at_median)}</div>
          <div className={NOTE}>at median demand • {fmt(plan.shelter_shortfall_at_high)} at high</div>
        </div>
      </div>

      <section className="mt-6">
        <SectionHeading title="Sanding trucks by council district" subtitle={plan.method} />
        <div className="mt-3.5 grid grid-cols-[3fr_2fr] gap-4 max-[900px]:grid-cols-1">
          <DistrictMap geojson={districts} values={trucksBy} format={(v) => fmt(v)} legendTitle="Trucks"
            selected={selected} onSelect={setSelected} />
          <div className={`${CARD} max-h-[430px] overflow-y-auto p-0`}>
            <table className="w-full">
              <thead className="sticky top-0 bg-surface">
                <tr><th className={TH}>District</th><th className={TH}>Trucks</th><th className={TH}>vs default</th><th className={TH}>Share</th></tr>
              </thead>
              <tbody>
                {plan.truck_allocation.map((a) => (
                  <tr key={a.district} onClick={() => setSelected(a.district)}
                    className={`cursor-pointer border-t border-line ${selected === a.district ? "bg-canvas" : ""}`}>
                    <td className={TD}>District {a.district}</td>
                    <td className={`${TD} font-semibold`}>{a.trucks}</td>
                    <td className={`${TD} ${change[a.district] < 0 ? "text-risk-severe" : "text-muted"}`}>
                      {change[a.district] ? (change[a.district] > 0 ? `+${change[a.district]}` : change[a.district]) : "—"}
                    </td>
                    <td className={`${TD} text-muted`}>{fmt(a.weight * 100, 1)}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </section>

      <section className="mt-6 grid grid-cols-2 gap-4 max-[900px]:grid-cols-1">
        <div>
          <SectionHeading title="Inclement weather shelters" subtitle="City-run winter shelters and published capacity" />
          <div className={`${CARD} mt-3.5 p-0`}>
            <table className="w-full">
              <thead><tr><th className={TH}>Shelter</th><th className={TH}>Capacity</th><th className={TH}>Status</th></tr></thead>
              <tbody>
                {assets.shelters.map((s) => {
                  const closed = plan.shelters_closed.includes(s.id);
                  return (
                    <tr key={s.id} className="border-t border-line" title={s.source}>
                      <td className={TD}>{s.name}<span className="block text-[0.72rem] text-muted">{s.capacity_note}</span></td>
                      <td className={TD}>{s.capacity == null ? "not published" : fmt(s.capacity)}</td>
                      <td className={TD}>
                        <span className={`rounded px-2 py-[2px] text-[0.72rem] font-semibold ${closed ? "bg-bad-bg text-bad-text" : "bg-ok-bg text-ok-text"}`}>
                          {closed ? "unavailable" : "open"}
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <p className={`${NOTE} mt-2`}>
            Demand range: {rangeText(dem)} people/day. Historic peak and costs:{" "}
            {assets.shelter_history.map((h) => `${h.metric.replaceAll("_", " ")} ${fmt(h.value)}`).join(" • ")}.
          </p>
        </div>
        <div>
          <SectionHeading title="Staff" subtitle={plan.staff_note} />
          <div className={`${CARD} mt-3.5 p-0`}>
            <table className="w-full">
              <thead><tr><th className={TH}>Department</th><th className={TH}>FTE FY2025-26</th><th className={TH}>FY2024-25</th></tr></thead>
              <tbody>
                {staff.map((r) => (
                  <tr key={r.department} className="border-t border-line">
                    <td className={TD}>{r.name}</td>
                    <td className={TD}>{r.fte_fy2026 == null ? "—" : fmt(r.fte_fy2026, 2)}</td>
                    <td className={`${TD} text-muted`}>{fmt(r.fte_fy2025, 2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className={`${NOTE} mt-2`}>{assets.department_staff.source}</p>
        </div>
      </section>
      <p className={`${NOTE} mt-6`}>Source: {plan.source}</p>
    </section>
  );
}
