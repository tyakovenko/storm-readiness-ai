import { Suspense, lazy, useCallback, useEffect, useState } from "react";
import { fetchHealth, fetchOverview } from "./api.js";
import AskAI from "./screens/AskAI.jsx";
import ResourcePlanner from "./screens/ResourcePlanner.jsx";
import StormOverview from "./screens/StormOverview.jsx";

// The map library is ~1 MB; load it only when the Risk Map tab is opened.
const RiskMap = lazy(() => import("./screens/RiskMap.jsx"));

// App shell: header, demo-data banner, tabs. All logic lives in the backend;
// screens only display tool outputs (/api/overview) and agent answers (/api/chat).

const TABS = [
  { id: "overview", label: "Storm Overview" },
  { id: "map", label: "Risk Map" },
  { id: "planner", label: "Resource Planner" },
  { id: "ask", label: "Ask AI" },
];
const tabFromHash = () => TABS.find((t) => `#${t.id}` === window.location.hash)?.id ?? "overview";

export default function App() {
  const [tab, setTab] = useState(tabFromHash);
  const [health, setHealth] = useState(null);
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [selectedCounty, setSelectedCounty] = useState(null);

  useEffect(() => {
    Promise.all([fetchHealth(), fetchOverview()])
      .then(([h, d]) => {
        setHealth(h);
        setData(d);
      })
      .catch(() => setError("Can't reach the backend. Is it running on port 8001?"));
  }, []);

  useEffect(() => {
    const onHash = () => setTab(tabFromHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  const go = (id) => {
    window.location.hash = id;
  };
  // Stable so the map isn't rebuilt on every render.
  const selectCounty = useCallback((fips) => setSelectedCounty(fips), []);
  const openCounty = (fips) => {
    setSelectedCounty(fips);
    go("map");
  };

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900">
      <header className="block border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-3 px-4 py-3">
          <h1 className="text-xl font-bold">Storm Readiness AI</h1>
          {health && (
            <div className="badges">
              <span className={health.mock ? "badge warn" : "badge ok"}>
                {health.mock ? "Mock mode: scripted, no LLM" : `Model: ${health.model}`}
              </span>
              <span className="badge neutral">{health.judge ? `Judge: ${health.judge}` : "Judge: off"}</span>
            </div>
          )}
        </div>
        <nav className="mx-auto max-w-7xl px-4" aria-label="Screens">
          <ul className="-mb-px flex gap-1 overflow-x-auto" role="tablist">
            {TABS.map((t) => (
              <li key={t.id}>
                <button
                  type="button" role="tab" aria-selected={tab === t.id} onClick={() => go(t.id)}
                  className={`whitespace-nowrap border-b-2 px-4 py-2.5 text-sm font-semibold ${
                    tab === t.id ? "border-blue-700 text-blue-800" : "border-transparent text-slate-600 hover:text-slate-900"
                  }`}
                >
                  {t.label}
                </button>
              </li>
            ))}
          </ul>
        </nav>
      </header>

      <main className="mx-auto max-w-7xl space-y-4 px-4 py-4">
        <p className="rounded-lg bg-amber-100 px-3 py-2 text-sm text-amber-900" role="note">
          Demo data only. Every number comes from stub tools, not a real forecast.
        </p>
        {error && <p className="rounded-lg bg-red-100 px-3 py-2 text-sm text-red-900" role="alert">{error}</p>}
        {!data && !error && <p className="text-sm text-slate-500">Loading…</p>}

        {data && tab === "overview" && <StormOverview data={data} onOpenCounty={openCounty} />}
        {data && tab === "map" && (
          <Suspense fallback={<p className="text-sm text-slate-500">Loading map…</p>}>
            <RiskMap data={data} selected={selectedCounty} onSelect={selectCounty} />
          </Suspense>
        )}
        {data && tab === "planner" && <ResourcePlanner base={data} health={health} />}
        {tab === "ask" && <AskAI health={health} />}
      </main>
    </div>
  );
}
