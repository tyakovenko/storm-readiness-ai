import { useMemo, useState } from "react";
import { PAGE, PageTitle } from "../components/Page.jsx";
import SectionHeading from "../components/SectionHeading.jsx";
import { CARD, LABEL, NOTE, fmt } from "../dallas/format.js";
import { RISK_CLASSES, RISK_HEX, getRiskLevel, getRiskLabel } from "../utils/riskTier.js";
import CountyMap from "./CountyMap.jsx";
import { Metric, StormContextHeader, ImpactPanel, ktToMph, getForecastInputs, toRiskLocations } from "./shared.jsx";

// Risk Map for one hurricane county: where impact is highest, why, what's exposed, and what to
// prioritize — built on the same /api/agents/{id}/overview data as Storm Overview. The backend
// predicts for exactly one county (the agent's own), so this page never draws a multi-county
// choropleth or a ranked list of locations — see toRiskLocations() in shared.jsx for how the
// single real prediction is kept in a shape a future multi-location API can extend without a
// page redesign.
const NO_PREDICTION_HEX = "#9aa3ae";

const ASK_PROMPTS = [
  "Why is this area high risk?",
  "What should we prioritize?",
  "Which shelters are exposed?",
  "Explain the risk factors",
];

function LayerControls({ layers, setLayers, hasTrack }) {
  const toggle = (k) => setLayers((l) => ({ ...l, [k]: !l[k] }));
  return (
    <div className="mt-3.5 flex flex-wrap items-center gap-x-6 gap-y-2 rounded-md border border-line bg-surface px-4 py-2.5 text-[0.82rem]">
      <span className={LABEL}>Layers</span>
      <label className="inline-flex cursor-pointer items-center gap-1.5 font-semibold text-ink">
        <input type="checkbox" checked={layers.risk} onChange={() => toggle("risk")} />
        County risk shading
      </label>
      {hasTrack && (
        <label className="inline-flex cursor-pointer items-center gap-1.5 font-semibold text-ink">
          <input type="checkbox" checked={layers.track} onChange={() => toggle("track")} />
          Storm track
        </label>
      )}
      <label className="inline-flex cursor-pointer items-center gap-1.5 font-semibold text-ink">
        <input type="checkbox" checked={layers.shelters} onChange={() => toggle("shelters")} />
        Shelters
      </label>
      <label className="inline-flex cursor-pointer items-center gap-1.5 font-semibold text-ink">
        <input type="checkbox" checked={layers.surgeOnly} disabled={!layers.shelters}
          onChange={() => toggle("surgeOnly")} />
        Surge/floodplain exposure only
      </label>
    </div>
  );
}

// The "Priority Areas" card for one normalized location (see toRiskLocations). Rendered from a
// list so a future multi-location response just adds more cards here, unchanged.
function LocationCard({ loc }) {
  if (loc.error) {
    return (
      <div className={CARD}>
        <div className={LABEL}>Selected county</div>
        <div className="text-[1.05rem] font-bold text-navy">{loc.name}</div>
        <p className="mt-2 rounded bg-bad-bg px-2.5 py-2 text-[0.82rem] text-bad-text">{loc.error}</p>
      </div>
    );
  }
  const level = getRiskLevel(loc.risk_level);
  return (
    <div className={`${CARD} border-l-[3px] ${RISK_CLASSES[level].borderLeft}`}>
      <div className={LABEL}>Selected county — the modeled risk area</div>
      <div className="text-[1.05rem] font-bold text-navy">{loc.name}</div>
      <div className="mt-1 text-[0.95rem] font-semibold text-navy">
        {getRiskLabel(loc.risk_level)} • {fmt(loc.prediction_range.low)}–{fmt(loc.prediction_range.high)}% customers out
      </div>
      <div className={NOTE}>median {fmt(loc.customers_out.median)} customers • lead time {fmt(loc.forecast_horizon_h)} h</div>
      <ul className="mt-2 list-disc pl-4 text-[0.8rem]">{loc.risk_drivers.slice(0, 3).map((w) => <li key={w}>{w}</li>)}</ul>
    </div>
  );
}

function ShelterDetail({ shelter, onBack }) {
  return (
    <div className={CARD}>
      <button type="button" onClick={onBack}
        className="cursor-pointer bg-transparent p-0 text-[0.78rem] font-semibold text-accent hover:underline">
        &larr; Back to county
      </button>
      <div className="mt-2 text-[1.05rem] font-bold text-navy">{shelter.name}</div>
      {shelter.city && <div className={NOTE}>{shelter.city}</div>}
      <dl className="mt-2 grid grid-cols-2 gap-2 text-[0.82rem]">
        <div><dt className={LABEL}>Evacuation beds</dt><dd>{shelter.evacuation_capacity ?? "—"}</dd></div>
        <div><dt className={LABEL}>Post-impact beds</dt><dd>{shelter.post_impact_capacity ?? "—"}</dd></div>
        <div><dt className={LABEL}>Pets</dt><dd>{shelter.pets ?? "—"}</dd></div>
        <div><dt className={LABEL}>ADA accessible</dt><dd>{shelter.ada ? "Yes" : "No"}</dd></div>
        <div><dt className={LABEL}>Generator</dt><dd>{shelter.generator ? "Yes" : "No"}</dd></div>
        <div><dt className={LABEL}>Exposure</dt>
          <dd>{[shelter.in_surge_zone && "surge zone", shelter.in_100yr_floodplain && "100-yr floodplain"].filter(Boolean).join(", ") || "none mapped"}</dd>
        </div>
      </dl>
    </div>
  );
}

export default function HurricaneRiskMap({ overview, agent, onAsk }) {
  const { alert, impact, geo, shelters, assets, county } = overview;
  const locations = useMemo(() => toRiskLocations(overview), [overview]);
  const { windKt, distNm, rightOfTrack } = getForecastInputs(alert, impact);

  const [layers, setLayers] = useState({ risk: true, track: true, shelters: true, surgeOnly: false });
  const [selectedShelterId, setSelectedShelterId] = useState(null);

  const exposedShelters = shelters.filter((s) => s.in_surge_zone || s.in_100yr_floodplain);
  const mapShelters = layers.shelters ? (layers.surgeOnly ? exposedShelters : shelters) : [];
  const selectedShelter = selectedShelterId ? shelters.find((s) => s.id === selectedShelterId) : null;

  const riskColor = impact.error ? NO_PREDICTION_HEX : RISK_HEX[getRiskLevel(impact.risk_tier)];
  const riskLegend = layers.risk
    ? { color: riskColor, label: impact.error ? "County risk: no prediction" : `County risk: ${getRiskLabel(impact.risk_tier)}` }
    : null;

  return (
    <section className={PAGE}>
      <PageTitle>Risk Map — {county}{agent?.state ? `, ${agent.state}` : ""}</PageTitle>
      <StormContextHeader alert={alert} county={county} state={agent?.state} />
      <p className="-mt-2 mb-4 text-[0.88rem] text-muted">
        Identify high-risk locations and understand the factors driving expected impacts.
      </p>

      <section>
        <SectionHeading title="Risk map" subtitle={
          impact.error
            ? "No outage prediction is available — showing the county boundary, forecast track and shelters only."
            : "Shaded by the model's predicted outage risk for this county. The backend predicts one county at a time, so this is not a multi-county choropleth."
        } />
        <LayerControls layers={layers} setLayers={setLayers} hasTrack={alert.forecast?.length > 0} />
        <div className="mt-3.5 grid grid-cols-[3fr_2fr] gap-4 max-[900px]:grid-cols-1">
          <div>
            <CountyMap geo={geo} track={layers.track ? alert.forecast : []} shelters={mapShelters}
              fillColor={riskColor} fillOpacity={layers.risk ? 0.4 : 0.08} riskLegend={riskLegend}
              trackLabel={alert.kind} height="h-[480px]"
              onShelterClick={(s) => setSelectedShelterId(s.id)} selectedShelterId={selectedShelterId} />
          </div>
          <div>
            <h3 className="mb-2 text-[0.95rem] font-bold text-navy">Priority areas</h3>
            {selectedShelter ? (
              <ShelterDetail shelter={selectedShelter} onBack={() => setSelectedShelterId(null)} />
            ) : (
              <div className="flex flex-col gap-3">
                {locations.map((loc) => <LocationCard key={loc.id} loc={loc} />)}
                <p className={NOTE}>
                  Only one location is modeled today — the selected county. Click a shelter on the map for its details.
                </p>
              </div>
            )}
          </div>
        </div>
      </section>

      <section className="mt-6">
        <SectionHeading title="Impact summary" subtitle={impact.source ?? "Impact model unavailable"} />
        <div className="mt-3.5"><ImpactPanel impact={impact} /></div>
      </section>

      <section className="mt-6">
        <SectionHeading title="Why is this area high risk?" subtitle="Model prediction drivers, separate from county exposure/planning context" />
        <div className="mt-3.5 grid grid-cols-2 gap-4 max-[900px]:grid-cols-1">
          <div>
            <div className={LABEL}>Model prediction drivers</div>
            <p className={`${NOTE} mb-2`}>What the outage model used for this forecast — the only fields the model itself cites as inputs.</p>
            {impact.error ? (
              <p className="rounded bg-bad-bg px-3 py-2 text-[0.85rem] text-bad-text">{impact.error}</p>
            ) : (
              <>
                {impact.inputs?.wind_estimate_method === "vmax_decay_fallback" && (
                  <p className={`${NOTE} mb-2`}>
                    Wind exposure is a distance-decay estimate from peak intensity, not this replay's own
                    wind-radius field — treat it as approximate.
                  </p>
                )}
                <div className="grid grid-cols-2 gap-3">
                  <Metric label="Wind exposure" value={`${fmt(windKt)} kt`} note={`~${fmt(ktToMph(windKt))} mph`} />
                  <Metric label="Side of track" value={rightOfTrack ? "Right" : "Left"} note={rightOfTrack ? "stronger side" : "weaker side"} />
                </div>
                <ul className="mt-2 list-disc pl-4 text-[0.85rem]">{impact.why.map((w) => <li key={w}>{w}</li>)}</ul>
                {impact.model_version && (
                  <p className={`${NOTE} mt-2`}>Model {impact.model_version} • calibration: {impact.calibration?.status}</p>
                )}
              </>
            )}
          </div>
          <div>
            <div className={LABEL}>Exposure & planning context</div>
            <p className={`${NOTE} mb-2`}>County vulnerability and exposure — useful context, not claimed here as a causal driver.</p>
            <div className="grid grid-cols-2 gap-3">
              <Metric label="Storm proximity" value={`${fmt(distNm)} nm`} note="closest forecast distance" />
              <Metric label="Hurricane risk score" value={fmt(overview.profile.nri_hurricane_risk_score, 1)} note="FEMA NRI, 0–100" />
              <Metric label="Social vulnerability" value={fmt(overview.profile.svi_overall, 2)} note="CDC/ATSDR SVI, 0–1" />
              <Metric label="Tree canopy" value={`${fmt(overview.profile.tree_canopy_pct, 1)}%`} note="USFS" />
            </div>
          </div>
        </div>
      </section>

      <section className="mt-6">
        <SectionHeading title="Exposed shelters & assets"
          subtitle="FEMA shelters in a mapped surge zone or 100-year floodplain — exposure context, not a model-predicted outage risk" />
        <p className={`${NOTE} mt-2`}>
          {fmt(exposedShelters.length)} of {fmt(assets.shelters_total)} shelters are in a surge zone or floodplain •{" "}
          {fmt(assets.safe_shelters)} shelters ({fmt(assets.safe_evacuation_capacity)} beds) are outside both.
        </p>
        {exposedShelters.length === 0 ? (
          <p className={`${NOTE} mt-2`}>No shelters are flagged in a surge zone or floodplain for {county}.</p>
        ) : (
          <ul className="mt-3 grid grid-cols-3 gap-3 max-[900px]:grid-cols-1">
            {exposedShelters.slice(0, 15).map((s) => (
              <li key={s.id}>
                <button type="button" onClick={() => setSelectedShelterId(s.id)}
                  className={`${CARD} w-full cursor-pointer text-left hover:border-accent ${selectedShelterId === s.id ? "border-accent" : ""}`}>
                  <div className="font-bold text-navy">{s.name}</div>
                  <div className={NOTE}>{s.city}</div>
                  <div className="mt-1 text-[0.8rem]">
                    {fmt(s.evacuation_capacity)} beds •{" "}
                    {[s.in_surge_zone && "surge zone", s.in_100yr_floodplain && "floodplain"].filter(Boolean).join(", ")}
                  </div>
                </button>
              </li>
            ))}
          </ul>
        )}
        {exposedShelters.length > 15 && <p className={`${NOTE} mt-2`}>Showing the first 15 of {exposedShelters.length}.</p>}
      </section>

      <section className="mt-6">
        <SectionHeading title="Ask AI about this county" subtitle="Opens the same Ask AI panel, scoped to this storm and county" />
        <div className="mt-3 flex flex-wrap gap-1.5">
          {ASK_PROMPTS.map((q) => (
            <button key={q} type="button" onClick={() => onAsk?.(q)}
              className="cursor-pointer rounded-full border border-line bg-surface px-3 py-1.5 text-[0.8rem] text-accent hover:border-accent">
              {q}
            </button>
          ))}
        </div>
      </section>

      <section className="mt-6">
        <SectionHeading title="Sources & explainability" subtitle="Where this page's numbers come from" />
        <ul className="mt-2 list-disc pl-5 text-[0.82rem] text-muted">
          <li>Forecast: {alert.source}</li>
          {!impact.error && <li>Outage model: {impact.source} (run {impact.model_run})</li>}
          <li>Shelters & exposure: {assets.source}</li>
          <li>County vulnerability & context: FEMA National Risk Index, CDC/ATSDR Social Vulnerability Index, USFS Tree Canopy Cover</li>
        </ul>
      </section>
    </section>
  );
}
