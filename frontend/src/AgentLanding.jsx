import { useState } from "react";
import { PAGE } from "./components/Page.jsx";
import { CARD, LABEL, NOTE, fmt } from "./dallas/format.js";

// Storm home page: users pick a storm scenario or ask a question in plain language.
// agent ids/routing are unchanged (onOpen(a.id) drives the same #/agents/<id> hash routes), only
// how each one is presented to the user. "county" terminology stays in the data, not in the UI copy.
const HAZARD_LABEL = { winter: "Winter storm", hurricane: "Hurricane" };
const SCENARIO_BADGE = {
  winter: "Planning scenario",
  hurricane: "Replay",
};
const NEUTRAL_BADGE = "bg-[#e8ecf1] text-[#3b4452]";

const PROMPT_EXAMPLES = [
  "Which areas are highest risk?",
  "Where should we stage resources?",
  "Which areas may lose power?",
  "What shelters may be needed?",
];

function AskBox({ onAsk }) {
  const [value, setValue] = useState("");

  function submit(e) {
    e.preventDefault();
    const q = value.trim();
    if (!q) return;
    onAsk(q);
    setValue("");
  }

  return (
    <div className="rounded-lg border border-line bg-surface p-4 shadow-[0_1px_3px_rgba(15,39,68,0.08)]">
      <form className="flex gap-2 max-[520px]:flex-col" onSubmit={submit}>
        <label htmlFor="home-ask" className="sr-only">Ask AI about storm readiness</label>
        <input
          id="home-ask"
          className="min-w-0 flex-1 rounded border border-line px-3.5 py-3 text-[0.95rem]"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder="Ask about risk, impacts, or resources — e.g. Which areas are highest risk?"
        />
        <button type="submit" className="cursor-pointer whitespace-nowrap rounded bg-accent px-4 py-3 font-semibold text-white hover:bg-accent-dark">
          Ask AI
        </button>
      </form>
      <div className="mt-3 flex flex-wrap gap-1.5">
        {PROMPT_EXAMPLES.map((q) => (
          <button key={q} type="button" onClick={() => onAsk(q)}
            className="cursor-pointer rounded-full border border-line bg-canvas px-3 py-1.5 text-[0.8rem] text-accent hover:border-accent">
            {q}
          </button>
        ))}
      </div>
    </div>
  );
}

function ScenarioBadge({ broken, hazard }) {
  const label = broken ? "Unavailable" : SCENARIO_BADGE[hazard] ?? "Available";
  return (
    <span className={`rounded px-2 py-[2px] text-[0.7rem] font-semibold uppercase tracking-[0.3px] ${
      broken ? "bg-bad-bg text-bad-text" : NEUTRAL_BADGE}`}>
      {label}
    </span>
  );
}

export default function AgentLanding({ agents, error, onOpen, onAsk }) {
  const hurricaneAgents = (agents ?? []).filter(
    (a) => a.hazard === "hurricane" && !String(a.status ?? "").startsWith("error"),
  );
  const totalStorms = hurricaneAgents.reduce((sum, a) => sum + (a.storms ?? 0), 0);

  return (
    <section className={PAGE}>
      <div className="mb-8 max-w-[760px]">
        <h1 className="mb-2 text-[1.75rem] font-bold text-navy max-[640px]:text-[1.4rem]">
          Prepare for incoming storms
        </h1>
        <p className="mb-5 text-[0.95rem] text-muted">
          Explore forecasts, predicted impacts, high-risk locations, and preparedness recommendations for each
          storm scenario below — or ask a question in plain language to get started.
        </p>
        <AskBox onAsk={onAsk} />
      </div>

      {error && <p className="mb-5 rounded bg-bad-bg px-3 py-2 text-[0.88rem] text-bad-text" role="alert">{error}</p>}

      <h2 className="mb-3 text-[1.05rem] font-bold text-navy">Choose a storm scenario</h2>
      <div className="grid grid-cols-3 gap-4 max-[1000px]:grid-cols-2 max-[640px]:grid-cols-1">
        {(agents ?? []).map((a) => {
          const broken = String(a.status ?? "").startsWith("error");
          return (
            <button key={a.id} type="button" disabled={broken} onClick={() => onOpen(a.id)}
              className={`${CARD} flex cursor-pointer flex-col gap-2 text-left hover:border-accent disabled:cursor-not-allowed`}>
              <div className="flex items-center justify-between gap-2">
                <span className={LABEL}>{HAZARD_LABEL[a.hazard] ?? a.hazard}</span>
                <ScenarioBadge broken={broken} hazard={a.hazard} />
              </div>
              <span className="text-[1.1rem] font-bold text-navy">{a.county ?? a.name}{a.state ? `, ${a.state}` : ""}</span>
              {a.hazard === "hurricane" && !broken && a.replay && (
                <span className="text-[0.82rem] font-semibold text-accent">Replay: Hurricane {a.replay}</span>
              )}
              <span className={NOTE}>
                {a.hazard === "hurricane" && !broken
                  ? `${fmt(a.storms)} past storms • ${fmt(a.shelters)} FEMA shelters`
                  : a.hazard === "winter" ? "Winter storms 2021–2026 • 311, outages, city response" : a.status}
              </span>
            </button>
          );
        })}
      </div>

      {hurricaneAgents.length > 0 && (
        <div className={`${CARD} mt-6 max-w-[760px]`}>
          <span className={LABEL}>Historical storms</span>
          <p className="mt-1.5 text-[0.88rem] text-ink">
            These scenarios are grounded in {fmt(totalStorms)} real historical hurricanes (HURDAT2, EAGLE-I, NOAA,
            FEMA) across {hurricaneAgents.length} {hurricaneAgents.length === 1 ? "county" : "counties"}, plus Dallas
            winter storms from 2021–2026. Open a scenario above to see its past storms and outage history.
          </p>
        </div>
      )}
    </section>
  );
}
