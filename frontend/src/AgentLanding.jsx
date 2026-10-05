import { PAGE, PageTitle } from "./components/Page.jsx";
import { CARD, LABEL, NOTE, fmt } from "./dallas/format.js";

// Landing page of the multi-agent service: one card per county agent (hazard template x county pack).
const HAZARD_LABEL = { winter: "Winter storm", hurricane: "Hurricane" };

export default function AgentLanding({ agents, error, onOpen }) {
  return (
    <section className={PAGE}>
      <PageTitle>Storm Readiness agents</PageTitle>
      <p className="mb-5 max-w-[760px] text-[0.9rem] text-muted">
        Each agent is one county with one hazard. It answers from that county's data only, and every answer is
        checked against its tools before you see it.
      </p>
      {error && <p className="rounded bg-bad-bg px-3 py-2 text-[0.88rem] text-bad-text" role="alert">{error}</p>}
      <div className="grid grid-cols-3 gap-4 max-[1000px]:grid-cols-2 max-[640px]:grid-cols-1">
        {(agents ?? []).map((a) => {
          const broken = String(a.status ?? "").startsWith("error");
          return (
            <button key={a.id} type="button" disabled={broken} onClick={() => onOpen(a.id)}
              className={`${CARD} flex cursor-pointer flex-col gap-2 text-left hover:border-accent disabled:cursor-not-allowed`}>
              <div className="flex items-center justify-between gap-2">
                <span className={LABEL}>{HAZARD_LABEL[a.hazard] ?? a.hazard}</span>
                <span className={`rounded px-2 py-[2px] text-[0.7rem] font-semibold ${
                  broken ? "bg-bad-bg text-bad-text" : "bg-ok-bg text-ok-text"}`}>
                  {broken ? "unavailable" : "live"}
                </span>
              </div>
              <span className="text-[1.1rem] font-bold text-navy">{a.county ?? a.name}{a.state ? `, ${a.state}` : ""}</span>
              <span className={NOTE}>
                {a.hazard === "hurricane" && !broken
                  ? `${fmt(a.storms)} past storms • ${fmt(a.shelters)} FEMA shelters • replay: ${a.replay}`
                  : a.hazard === "winter" ? "Winter storms 2021–2026 • 311, outages, city response" : a.status}
              </span>
            </button>
          );
        })}
        <div className={`${CARD} flex flex-col gap-2 border-dashed opacity-80`}>
          <span className={LABEL}>Research layer</span>
          <span className="text-[1.1rem] font-bold text-navy">Research a new county</span>
          <span className={NOTE}>Coming next: an agent drafts a county pack from public sources for review before it goes live.</span>
        </div>
      </div>
    </section>
  );
}
