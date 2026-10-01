import { Card, Sources, Stat, TierBadge, WaitingOnData, formatUtc, pctRange } from "../components/ui.jsx";

// Screen 1: the storm, its forecast, and a summary of expected impacts.
// Every value shown comes straight from a tool output (/api/overview); nothing is computed here.

export default function StormOverview({ data, onOpenCounty }) {
  const { advisory: a, scenarios: s, enso: e, impact } = data;
  const counties = [...impact.counties].sort((x, y) => y.pct_customers_out.median - x.pct_customers_out.median);
  const highest = counties.filter((c) => c.risk_tier === "red");

  return (
    <div className="space-y-4">
      <Card>
        <div className="flex flex-wrap items-end gap-4">
          <label className="flex flex-col gap-1 text-sm font-medium text-slate-700">
            Storm event
            <select className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-base" value={a.storm_id} disabled>
              <option value={a.storm_id}>{a.storm_name} ({a.storm_id})</option>
            </select>
          </label>
          <p className="max-w-md text-sm text-slate-500">
            One storm loaded. Replaying past storms needs the historical NHC advisories (in progress).
          </p>
        </div>
      </Card>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Category" value={a.category === 0 ? "TS" : a.category} sub={a.category === 0 ? "Tropical storm" : "Saffir-Simpson"} />
        <Stat label="Max sustained wind" value={`${a.max_wind_kt} kt`} />
        <Stat label="Landfall in" value={`~${a.lead_time_to_landfall_h} h`} sub={a.forecast_landfall} />
        <Stat label={`Advisory ${a.advisory_number}`} value={a.basin === "AL" ? "Atlantic" : "E. Pacific"} sub={`Issued ${formatUtc(a.issued_utc)}`} />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <WaitingOnData
          title="Forecast track"
          needs="Forecast positions (lat/lon, wind) for each forecast hour. The data contract only has the landfall area as text."
          source="Historical NHC forecast advisories (Data Strategy, Source 2)"
        />
        <WaitingOnData
          title="Rainfall"
          needs="Forecast rainfall totals by county. Not in the data contract yet."
          source="NWS / WPC rainfall forecasts (free)"
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Track uncertainty">
          <ul className="space-y-1 text-sm text-slate-700">
            <li><strong>{s.n_scenarios}</strong> possible tracks around the official forecast</li>
            <li>Landfall spread: <strong>{s.landfall_spread_nm} nm</strong></li>
            <li><strong>{s.pct_scenarios_landfall_west_of_forecast}%</strong> of tracks make landfall west of the forecast</li>
          </ul>
          <p className="mt-2 text-xs text-slate-500">{s.method}</p>
        </Card>
        <Card title="El Niño context">
          <p className="text-sm text-slate-700">
            <strong>{e.phase}</strong> ({e.strength}), ONI {e.oni_c} °C in {e.season} {e.year}
          </p>
        </Card>
      </div>

      <Card title="Expected impacts">
        {highest.length > 0 && (
          <p className="mb-3 rounded-lg bg-red-50 p-3 text-sm text-red-900">
            <strong>Highest risk:</strong> {highest.map((c) => c.name).join(", ")}
          </p>
        )}
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-slate-200 text-xs uppercase text-slate-500">
              <tr>
                <th className="py-2 pr-3">County</th>
                <th className="py-2 pr-3">Risk</th>
                <th className="py-2 pr-3">Peak customers without power</th>
                <th className="py-2 pr-3">Customers served</th>
                <th className="py-2" />
              </tr>
            </thead>
            <tbody>
              {counties.map((c) => (
                <tr key={c.fips} className="border-b border-slate-100">
                  <td className="py-2 pr-3 font-medium">{c.name}, {c.state}</td>
                  <td className="py-2 pr-3"><TierBadge tier={c.risk_tier} /></td>
                  <td className="py-2 pr-3">{pctRange(c.pct_customers_out)}</td>
                  <td className="py-2 pr-3">{c.customers_served.toLocaleString()}</td>
                  <td className="py-2 text-right">
                    <button type="button" className="text-sm font-semibold text-blue-700 hover:underline" onClick={() => onOpenCounty(c.fips)}>
                      View on map
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="mt-2 text-xs text-slate-500">Impact model: {impact.model_version}</p>
      </Card>

      <Sources items={[a.source, s.source, e.source, impact.source]} />
    </div>
  );
}
