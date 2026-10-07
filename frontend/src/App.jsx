import { useEffect, useState } from "react";
import Header from "./components/Header.jsx";
import Navigation from "./components/Navigation.jsx";
import AskAI from "./components/AskAI.jsx";
import StormOverview from "./pages/StormOverview.jsx";
import ResourcePlanner from "./pages/ResourcePlanner.jsx";
import DallasOverview from "./dallas/DallasOverview.jsx";
import DallasPlanner from "./dallas/DallasPlanner.jsx";
import HurricaneOverview from "./hurricane/HurricaneOverview.jsx";
import HurricaneRiskMap from "./hurricane/HurricaneRiskMap.jsx";
import HurricaneShelters from "./hurricane/HurricaneShelters.jsx";
import AgentLanding from "./AgentLanding.jsx";
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
    nav: [{ id: "storm-overview", label: "Storm Overview" }, { id: "risk-map", label: "Risk Map" },
      { id: "shelters", label: "Shelter Planning" }],
    pages: { "storm-overview": HurricaneOverview, "risk-map": HurricaneRiskMap, shelters: HurricaneShelters },
  },
};

function parseHash() {
  const m = window.location.hash.match(/^#\/agents\/([^/]+)(?:\/([^/]+))?/);
  return m ? { agentId: decodeURIComponent(m[1]), page: m[2] ?? "storm-overview" } : { agentId: null, page: null };
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
      <main className="flex-1 bg-canvas pt-[116px]">
        {overview || error ? <PageComponent overview={overview} overviewError={error} /> : <PageStatus title="Loading" />}
      </main>
      <AskAI open={askAIOpen} onClose={() => setAskAIOpen(false)} />
    </div>
  );
}

function MultiAgentApp() {
  const { agentId, page } = useHashRoute();
  const [agents, setAgents] = useState(null);
  const [agentsError, setAgentsError] = useState("");
  const [askAIOpen, setAskAIOpen] = useState(false);
  const [pendingQuestion, setPendingQuestion] = useState("");
  useEffect(() => {
    fetchAgents().then(setAgents).catch((e) => setAgentsError(`Can't list agents (${e.message}).`));
  }, []);
  const agent = agents?.find((a) => a.id === agentId) ?? null;
  const template = agent ? TEMPLATE_PAGES[agent.hazard] : null;
  const { overview, error } = useOverview(agentId, Boolean(template));
  const PageComponent = template ? (template.pages[page] ?? template.pages["storm-overview"]) : null;

  function askWithQuestion(q) {
    setPendingQuestion(q);
    setAskAIOpen(true);
  }

  return (
    <div className="flex min-h-screen flex-col bg-canvas">
      <Header onAskAIClick={() => setAskAIOpen((v) => !v)} askAIOpen={askAIOpen} />
      {agent && (
        <Navigation
          items={template?.nav ?? []}
          activePage={page}
          onNavigate={(p) => go(agentId, p)}
          onHome={() => go(null)}
          title={`${agent.county}${agent.state ? `, ${agent.state}` : ""}`}
          agents={agents ?? []}
          currentAgentId={agentId}
          onSelectAgent={(id) => go(id, page)}
        />
      )}
      <main className={`flex-1 bg-canvas ${agent ? "pt-[116px]" : "pt-[64px]"}`}>
        {!agentId || !agent ? (
          agents || agentsError ? (
            <AgentLanding agents={agents} error={agentsError || (agentId && agents ? `Unknown agent ${agentId}` : "")}
              onOpen={(id) => go(id)} onAsk={askWithQuestion} />
          ) : (
            <PageStatus title="Loading agents" />
          )
        ) : overview || error ? (
          error ? <PageStatus title={agent.name} error={error} />
            : <PageComponent key={agentId} overview={overview} agentId={agentId} agent={agent} overviewError={error}
                onAsk={askWithQuestion} />
        ) : (
          <PageStatus title={agent.name} />
        )}
      </main>
      <AskAI key={agentId ?? "none"} open={askAIOpen} onClose={() => setAskAIOpen(false)}
        agentId={agent ? agentId : null} hazard={agent?.hazard ?? null} agentName={agent?.name}
        pendingQuestion={pendingQuestion} onPendingSent={() => setPendingQuestion("")} />
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
