import { PAGE, PageStatus, PageTitle } from "../components/Page.jsx";
import { useOverview, useStormOverview } from "../api.js";
import HurricaneOverview from "./HurricaneOverview.jsx";
import HurricaneShelters from "./HurricaneShelters.jsx";
import StormRiskMap from "./StormRiskMap.jsx";

// Storm-wide hurricane experience (Phase 1): one shell, three tabs, sharing {slug, county,
// horizon} state that the caller (App.jsx) keeps in the URL so it persists across tab changes
// and page reloads (requirement: storm/county/horizon stay consistent across all three screens).
//
// Storm Overview and Resource Planner are untouched, existing, single-county components
// (HurricaneOverview.jsx / HurricaneShelters.jsx) fed by the existing, unmodified
// /api/agents/{slug}/overview -- they only ever show the storm's home county. Risk Map is the
// only screen that is actually storm-wide (GET /api/storms/{slug}/overview). If the shared
// `county` state names a real neighboring county that has no local pack, Storm Overview and
// Resource Planner show CountyGate's unavailable message instead of silently showing the home
// county's data under a different county's selection -- never a silent switch back to home.

function CountyGate({ stormOverview, selectedFips, onSelectCounty, children }) {
  if (!stormOverview) {
    // Risk Map's own fetch hasn't resolved yet (or failed) -- nothing to gate on yet, so don't
    // block Storm Overview/Resource Planner's independent data on it.
    return children;
  }
  const selected = selectedFips ? stormOverview.counties.find((c) => c.fips === selectedFips) : null;
  if (!selected || selected.has_local_pack) return children;

  const supported = stormOverview.counties.filter((c) => c.has_local_pack);
  return (
    <section className={PAGE}>
      <div className="rounded-md border border-line bg-surface px-5 py-7 text-center">
        <p className="text-[0.95rem] font-semibold text-navy">
          Shelter and resource-planning data isn&rsquo;t available yet for {selected.name}, {selected.state}.
        </p>
        <p className="mx-auto mt-1.5 max-w-[520px] text-[0.82rem] text-muted">
          {selected.name} has a real outage prediction on the Risk Map (this storm's own forecast, same
          trained model), but no published shelter inventory or resource plan yet. Pick a county that has one:
        </p>
        <div className="mt-4 flex flex-wrap justify-center gap-2">
          {supported.map((c) => (
            <button key={c.fips} type="button" onClick={() => onSelectCounty(c.fips)}
              className="cursor-pointer rounded-full border border-accent px-4 py-1.5 text-[0.85rem] font-semibold text-accent hover:bg-[#e8f0f8]">
              View {c.name}
            </button>
          ))}
        </div>
      </div>
    </section>
  );
}

export default function StormShell({ agents, slug, page, county, horizon, onSelectCounty, onSelectHorizon, onOpenCountyDetail, onAsk }) {
  const agent = agents?.find((a) => a.id === slug) ?? null;
  const { overview: stormOverview, error: stormError } = useStormOverview(slug, horizon);
  // Phase 2A: until the user explicitly picks a horizon, mirror Risk Map's own backend-resolved
  // default (stormOverview.horizon_h) instead of falling back to Storm Overview's unrelated
  // peak/closest-approach snapshot -- otherwise the two screens show two different questions
  // ("worst case" vs "+48h") under the same "nothing selected yet" state and look inconsistent.
  const effectiveHorizon = horizon ?? stormOverview?.horizon_h ?? null;
  // Phase 2B: Storm Overview's prediction is horizon-dependent, so it must not fetch (and
  // flash) a value before the default horizon is known. Hold its fetch off -- showing the
  // existing PageStatus loading placeholder below -- until either the user has explicitly
  // picked a horizon, or the storm-wide default has resolved (success or failure; never hang
  // forever on a Risk Map outage). Resource Planner shows nothing horizon-dependent, so it's
  // never held back by this.
  const horizonKnown = horizon != null || stormOverview != null || Boolean(stormError);
  const homeEnabled = page !== "storm-overview" || horizonKnown;
  const { overview: homeOverview, error: homeError } = useOverview(slug, homeEnabled, effectiveHorizon);
  // StormRiskMap renders its own error state directly; CountyGate only needs stormOverview.

  if (agents && !agent) {
    return <PageStatus title="Hurricane" error={`Unknown storm ${slug}.`} />;
  }

  if (page === "risk-map") {
    return (
      <StormRiskMap overview={stormOverview} error={stormError} selectedFips={county}
        track={homeOverview?.alert?.forecast}
        onSelectCounty={onSelectCounty} onSelectHorizon={onSelectHorizon} onOpenCounty={onOpenCountyDetail} onAsk={onAsk} />
    );
  }

  const title = page === "resource-planner" ? "Resource Planner" : "Storm Overview";
  // Mirrors App.jsx's existing MultiAgentApp rendering exactly: the per-county screens below
  // never receive a null overview (neither handles that), so they only mount once it's loaded.
  if (!homeOverview) return <PageStatus title={title} error={homeError} />;
  return (
    <CountyGate stormOverview={stormOverview} selectedFips={county} onSelectCounty={onSelectCounty}>
      {page === "resource-planner" ? (
        <HurricaneShelters overview={homeOverview} agentId={slug} />
      ) : (
        <HurricaneOverview overview={homeOverview} agent={agent} onAsk={onAsk}
          stormOverview={stormOverview} onSelectHorizon={onSelectHorizon} onOpenCounty={onOpenCountyDetail} />
      )}
    </CountyGate>
  );
}
