import { useState } from "react";
import { PAGE, PageTitle } from "../components/Page.jsx";
import SectionHeading from "../components/SectionHeading.jsx";
import DistrictMap from "./DistrictMap.jsx";
import { BIG, CARD, LABEL, NOTE, SECTORS, fmt, rangeText } from "./format.js";

// Storm Overview for Dallas: the alert (or labeled scenario), what past storms
// like it caused, the demand range they imply, and where it concentrates.
// Everything comes from /api/overview = the same tools the agent calls.

function Metric({ label, value, note }) {
  return (
    <div className={CARD}>
      <div className={LABEL}>{label}</div>
      <div className={BIG}>{value}</div>
      {note && <div className={NOTE}>{note}</div>}
    </div>
  );
}

function AlertHeader({ alert, enso }) {
  const scenario = alert.kind === "scenario";
  return (
    <div className="mb-4 border-b border-line pb-4">
      <div className="flex flex-wrap items-center gap-2.5">
        <span
          className={`rounded px-2 py-[3px] text-[0.72rem] font-bold uppercase tracking-[0.3px] ${
            scenario ? "bg-warn-bg text-warn-text" : "bg-bad-bg text-bad-text"
          }`}
        >
          {scenario ? "Planning scenario" : "Live NWS alert"}
        </span>
        <h3 className="text-[1.3rem] font-bold text-navy">
          {alert.headline.replace(/^SCENARIO \(not a real alert\): /, "")}
        </h3>
      </div>
      <p className="mt-1 text-[0.85rem] text-muted">
        {alert.area} • onset {alert.onset_local} • {enso.phase} ({enso.strength}, ONI {fmt(enso.oni_c, 2)}, {enso.season}{" "}
        {enso.year})
      </p>
      <p className="mt-1 text-[0.78rem] text-muted">{alert.note} Live check: {alert.live_check}.</p>
    </div>
  );
}

function DemandCard({ title, range, unit, note }) {
  return (
    <div className={`${CARD} flex-[1_1_0] min-w-[220px]`}>
      <div className={LABEL}>{title}</div>
      <div className={BIG}>
        {range ? `${fmt(range.low, 1)}–${fmt(range.high, 1)}` : "—"}
        <span className="ml-1 text-[0.85rem] font-semibold text-muted">{unit}</span>
      </div>
      <div className={NOTE}>{range ? `median ${fmt(range.median, 1)} • from ${range.n} past storms` : "no data"}</div>
      {note && <div className={`${NOTE} mt-1`}>{note}</div>}
    </div>
  );
}

function StormCard({ s }) {
  const sectors = Object.entries(s.excess_311_by_sector).sort((a, b) => b[1] - a[1]);
  return (
    <article className={`${CARD} flex min-w-[240px] flex-[1_1_0] flex-col gap-2`}>
      <div className="flex items-start justify-between gap-2">
        <h4 className="text-base font-bold text-navy">{s.name}</h4>
        <span className="whitespace-nowrap rounded bg-[#e8ecf1] px-2 py-[2px] text-[0.72rem] font-semibold text-[#3b4452]">
          similarity {fmt(s.similarity, 3)}
        </span>
      </div>
      <div className={NOTE}>
        {s.event_dates.join(" to ")} • {s.enso_phase ?? "ENSO n/a"}
      </div>
      <div className="text-[0.82rem] text-ink">
        Ice {fmt(s.weather.ice_accretion_in, 2)} in • low {fmt(s.weather.min_temp_f, 1)}°F •{" "}
        {fmt(s.weather.hours_below_freezing)} h below freezing • snow {fmt(s.weather.snowfall_in, 1)} in
      </div>
      <div>
        <div className={LABEL}>Peak power outages</div>
        <div className="text-[1.05rem] font-bold text-navy">
          {s.peak_customers_out == null ? "no record" : `${fmt(s.peak_customers_out)} customers (${fmt(s.peak_pct_customers, 2)}%)`}
        </div>
      </div>
      <div>
        <div className={LABEL}>311 surge above normal</div>
        <div className="mt-1 flex flex-wrap gap-1.5">
          {sectors.length === 0 && <span className={NOTE}>none above threshold</span>}
          {sectors.map(([k, v]) => (
            <span key={k} className="rounded bg-risk-high-bg px-2 py-[2px] text-[0.75rem] font-semibold text-risk-high">
              {SECTORS[k] ?? k}: +{fmt(v)}
            </span>
          ))}
        </div>
      </div>
    </article>
  );
}

export default function DallasOverview({ overview }) {
  const { alert, similar, demand, enso, districts } = overview;
  const [selected, setSelected] = useState(null);
  const h = alert.hazards;
  const byDistrict = Object.fromEntries(demand.by_district.map((d) => [d.district, d.transport_requests.median]));
  const top = [...demand.by_district].sort((a, b) => b.transport_requests.median - a.transport_requests.median).slice(0, 5);

  return (
    <section className={PAGE}>
      <PageTitle>Storm Overview — Dallas County</PageTitle>
      <AlertHeader alert={alert} enso={enso} />

      {h && (
        <div className="grid grid-cols-5 gap-3 max-[900px]:grid-cols-2">
          <Metric label="Ice accretion" value={`${fmt(h.ice_accretion_in, 2)} in`} />
          <Metric label="Minimum temp" value={`${fmt(h.min_temp_f, 1)}°F`} />
          <Metric label="Below freezing" value={`${fmt(h.hours_below_freezing)} h`} />
          <Metric label="Snow / sleet" value={`${fmt(h.snowfall_in, 1)} in`} />
          <Metric label="Lead time" value={`${fmt(alert.lead_time_h)} h`} />
        </div>
      )}

      <section className="mt-6">
        <SectionHeading
          title="Expected demand"
          subtitle={`Range over the ${demand.basis_storms.length} most similar past Dallas storms — not a forecast model`}
        />
        <div className="mt-3.5 flex flex-wrap gap-3.5">
          <DemandCard title="Shelter guests per day" range={demand.shelter_guests_per_day} unit="people"
            note="Documented headcounts: Jan 2025 average, Jan 2026 plan, 2023-24 peak" />
          <DemandCard title="Storm-driven street 311 requests" range={demand.transport_requests_storm_days} unit="requests"
            note="Sanding, flashing signals, street hazards above a normal week" />
          <DemandCard title="Peak customers without power" range={demand.peak_customers_out} unit="customers" />
        </div>
        <p className={`${NOTE} mt-2`}>{demand.caveat}</p>
      </section>

      <section className="mt-6">
        <SectionHeading title="Most similar past storms" subtitle="Ranked by DFW weather: ice, minimum temperature, hours below freezing, snow" />
        <div className="mt-3.5 flex flex-wrap gap-3.5">
          {similar.storms.slice(0, 3).map((s) => (
            <StormCard key={s.storm_id} s={s} />
          ))}
        </div>
        <p className={`${NOTE} mt-2`}>{similar.caveat}</p>
      </section>

      <section className="mt-6">
        <SectionHeading title="Where street demand concentrates" subtitle="Expected storm-driven street requests by council district (median)" />
        <div className="mt-3.5 grid grid-cols-[2fr_1fr] gap-4 max-[900px]:grid-cols-1">
          <DistrictMap geojson={districts} values={byDistrict} format={(v) => fmt(v, 1)}
            legendTitle="Requests (median)" selected={selected} onSelect={setSelected} />
          <div className={CARD}>
            <div className={LABEL}>Busiest districts</div>
            <ol className="mt-2 flex flex-col gap-2">
              {top.map((d) => (
                <li key={d.district}>
                  <button type="button" onClick={() => setSelected(d.district)}
                    className={`w-full cursor-pointer rounded px-2 py-1.5 text-left text-[0.85rem] hover:bg-canvas ${selected === d.district ? "bg-canvas font-semibold" : ""}`}>
                    District {d.district}
                    <span className="block text-[0.78rem] text-muted">{rangeText(d.transport_requests)} requests</span>
                  </button>
                </li>
              ))}
            </ol>
          </div>
        </div>
      </section>
      <p className={`${NOTE} mt-6`}>Sources: {[alert.source, similar.source, demand.source].join(" • ")}</p>
    </section>
  );
}
