import { useEffect, useState } from "react";
import Header from "./components/Header.jsx";
import Navigation from "./components/Navigation.jsx";
import AskAI from "./components/AskAI.jsx";
import StormOverview from "./pages/StormOverview.jsx";
import ResourcePlanner from "./pages/ResourcePlanner.jsx";
import DallasOverview from "./dallas/DallasOverview.jsx";
import DallasPlanner from "./dallas/DallasPlanner.jsx";
import HurricaneOverview from "./hurricane/HurricaneOverview.jsx";
import HurricaneShelters from "./hurricane/HurricaneShelters.jsx";
import AgentLanding from "./AgentLanding.jsx";
import { ResearchRun, ResearchRuns } from "./research/ResearchPage.jsx";
import { fetchAgents, fetchHealth, useOverview } from "./api.js";
import { PageStatus } from "./components/Page.jsx";

// Single-agent service (AGENT_DOMAIN=dallas|hurricane): two screens + Ask AI, as before.
// Multi-agent service (AGENT_DOMAIN=multi): landing page of county agents; each agent gets the page set
// of its hazard template, addressed by hash so links can be shared: #/agents/<id>/<page>.
const STUB_PAGES = { "storm-overview": StormOverview, "resource-planner": ResourcePlanner };
const TEMPLATE_PAGES = {
  winter: {
    nav: [{ id: "storm-overview", label: "Storm Overview" }, { id: "resource-planner", label: "Resource Planner" }],
    pages: { "storm-overview": DallasOverview, "resource-planner": DallasPlanner },
  },
  hurricane: {
    nav: [{ id: "storm-overview", label: "Storm Overview" }, { id: "shelters", label: "Shelters" }],
    pages: { "storm-overview": HurricaneOverview, shelters: HurricaneShelters },
  },
};

// #/agents/<id>/<page> | #/research | #/research/<hazard>/<fips>/<run_id>
function parseHash() {
  const h = window.location.hash;
  const r = h.match(/^#\/research(?:\/([^/]+)\/([^/]+)\/([^/]+))?/);
  if (r) return { agentId: null, page: null, research: r[1] ? r.slice(1, 4).map(decodeURIComponent) : [] };
  const m = h.match(/^#\/agents\/([^/]+)(?:\/([^/]+))?/);
  return m ? { agentId: decodeURIComponent(m[1]), page: m[2] ?? "storm-overview", research: null }
    : { agentId: null, page: null, research: null };
}

function useHashRoute() {
  const [route, setRoute] = useState(parseHash);
  useEffect(() => {
    const on = () => setRoute(parseHash());
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return route;
}

function go(agentId, page) {
  window.location.hash = agentId ? `#/agents/${encodeURIComponent(agentId)}/${page ?? "storm-overview"}` : "#/";
}

function goResearch(...parts) {
  window.location.hash = ["#/research", ...parts.map(encodeURIComponent)].join("/");
}

function SingleAgentApp() {
  const [activePage, setActivePage] = useState("storm-overview");
  const [askAIOpen, setAskAIOpen] = useState(false);
  const { overview, error } = useOverview();
  const pages = overview?.domain === "dallas" ? TEMPLATE_PAGES.winter.pages : STUB_PAGES;
  const PageComponent = pages[activePage] ?? pages["storm-overview"];
  return (
    <div className="flex min-h-screen flex-col bg-canvas">
      <Header onAskAIClick={() => setAskAIOpen((v) => !v)} askAIOpen={askAIOpen} />
      <Navigation activePage={activePage} onNavigate={setActivePage} />
      <main className="flex-1 bg-canvas pt-[102px]">
        {overview || error ? <PageComponent overview={overview} overviewError={error} /> : <PageStatus title="Loading" />}
      </main>
      <AskAI open={askAIOpen} onClose={() => setAskAIOpen(false)} />
    </div>
  );
}

function MultiAgentApp() {
  const { agentId, page, research } = useHashRoute();
  const [agents, setAgents] = useState(null);
  const [agentsError, setAgentsError] = useState("");
  const [askAIOpen, setAskAIOpen] = useState(false);
  useEffect(() => {
    fetchAgents().then(setAgents).catch((e) => setAgentsError(`Can't list agents (${e.message}).`));
  }, []);
  const agent = agents?.find((a) => a.id === agentId) ?? null;
  const template = agent ? TEMPLATE_PAGES[agent.hazard] : null;
  const { overview, error } = useOverview(agentId, Boolean(template));
  const PageComponent = template ? (template.pages[page] ?? template.pages["storm-overview"]) : null;

  return (
    <div className="flex min-h-screen flex-col bg-canvas">
      <Header onAskAIClick={() => setAskAIOpen((v) => !v)} askAIOpen={askAIOpen} />
      <Navigation
        items={template?.nav ?? []}
        activePage={page}
        onNavigate={(p) => go(agentId, p)}
        onHome={() => go(null)}
        title={agent ? `${agent.county}${agent.state ? `, ${agent.state}` : ""}` : research ? "Research" : null}
      />
      <main className="flex-1 bg-canvas pt-[102px]">
        {research ? (
          research.length ? <ResearchRun hazard={research[0]} fips={research[1]} runId={research[2]} />
            : <ResearchRuns onOpen={(...p) => goResearch(...p)} />
        ) : !agentId || !agent ? (
          agents || agentsError ? (
            <AgentLanding agents={agents} error={agentsError || (agentId && agents ? `Unknown agent ${agentId}` : "")}
              onOpen={(id) => go(id)} onResearch={() => goResearch()} />
          ) : (
            <PageStatus title="Loading agents" />
          )
        ) : overview || error ? (
          error ? <PageStatus title={agent.name} error={error} />
            : <PageComponent key={agentId} overview={overview} agentId={agentId} overviewError={error} />
        ) : (
          <PageStatus title={agent.name} />
        )}
      </main>
      {/* key: a new agent starts a new conversation */}
      <AskAI key={agentId ?? "none"} open={askAIOpen} onClose={() => setAskAIOpen(false)}
        agentId={agent ? agentId : null} hazard={agent?.hazard} agentName={agent?.name} disabled={!agent} />
    </div>
  );
}

export default function App() {
  const [mode, setMode] = useState(null);
  useEffect(() => {
    fetchHealth().then((h) => setMode(h.domain === "multi" ? "multi" : "single")).catch(() => setMode("single"));
  }, []);
  if (mode === null) return <div className="min-h-screen bg-canvas" />;
  return mode === "multi" ? <MultiAgentApp /> : <SingleAgentApp />;
}
