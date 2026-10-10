
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
import StormShell from "./hurricane/StormShell.jsx";

import AgentLanding from "./AgentLanding.jsx";
import LiveOperations from "./pages/LiveOperations.jsx";

import {
  fetchAgents,
  fetchHealth,
  useOverview,
} from "./api.js";

import { PageStatus } from "./components/Page.jsx";

// Global visual theme.
// Navy is reserved for the main application header.
const THEME = {
  background: "#F2F7FC",
  surface: "#FFFFFF",
  border: "#DCE7F2",
  primary: "#2878E8",
  navy: "#102845",
  text: "#163451",
  muted: "#60758C",
};

// Shared page styling.
// Keeps all application screens on a light blue canvas.
const APP_STYLE = {
  minHeight: "100vh",
  backgroundColor: THEME.background,
  color: THEME.text,
};

const MAIN_STYLE = {
  flex: 1,
  width: "100%",
  minWidth: 0,
  backgroundColor: THEME.background,
};

// Existing single-agent fallback pages.
const STUB_PAGES = {
  "storm-overview": StormOverview,
  "resource-planner": ResourcePlanner,
};

// Preserve all existing agent templates and navigation.
const TEMPLATE_PAGES = {
  winter: {
    nav: [
      {
        id: "storm-overview",
        label: "Storm Overview",
      },
      {
        id: "resource-planner",
        label: "Resource Planner",
      },
    ],
    pages: {
      "storm-overview": DallasOverview,
      "resource-planner": DallasPlanner,
    },
  },

  hurricane: {
    nav: [
      {
        id: "storm-overview",
        label: "Storm Overview",
      },
      {
        id: "risk-map",
        label: "Risk Map",
      },
      {
        id: "shelters",
        label: "Shelter Planning",
      },
    ],
    pages: {
      "storm-overview": HurricaneOverview,
      "risk-map": HurricaneRiskMap,
      shelters: HurricaneShelters,
    },
  },
};

// Phase 1: the storm-wide hurricane experience's three tabs (replaces the single-county
// "Shelter Planning" tab's nav entry -- Resource Planner is the same screen, reused unchanged).
const STORM_NAV = [
  { id: "storm-overview", label: "Storm Overview" },
  { id: "risk-map", label: "Risk Map" },
  { id: "resource-planner", label: "Resource Planner" },
];

// Hash-based routing. #/storms/{slug}/{page}?county=&horizon= is new (Phase 1): one storm's
// multi-county experience, with the selected county and forecast horizon carried in the URL so
// they persist across tab navigation and page reloads. #/agents/{id}/{page} and #/live-operations
// are unchanged -- existing deep links to a single county agent (or Dallas) keep working exactly
// as before.
function parseHash() {
  if (/^#\/live-operations\/?$/.test(window.location.hash)) {
    return { kind: "live-operations", agentId: null, page: "live-operations", slug: null, county: null, horizon: null };
  }

  const stormMatch = window.location.hash.match(/^#\/storms\/([^/?]+)(?:\/([^/?]+))?(?:\?(.*))?/);
  if (stormMatch) {
    const params = new URLSearchParams(stormMatch[3] ?? "");
    const horizonRaw = params.get("horizon");
    const countyRaw = params.get("county");
    return {
      kind: "storm",
      agentId: null,
      slug: decodeURIComponent(stormMatch[1]),
      page: stormMatch[2] ?? "storm-overview",
      county: countyRaw ? decodeURIComponent(countyRaw) : null,
      horizon: horizonRaw ? Number(horizonRaw) : null,
    };
  }

  const match = window.location.hash.match(/^#\/agents\/([^/]+)(?:\/([^/]+))?/);
  if (match) {
    return {
      kind: "agent",
      agentId: decodeURIComponent(match[1]),
      page: match[2] ?? "storm-overview",
      slug: null, county: null, horizon: null,
    };
  }

  return { kind: "home", agentId: null, page: null, slug: null, county: null, horizon: null };
}

function useHashRoute() {
  const [route, setRoute] = useState(parseHash);

  useEffect(() => {
    const handleHashChange = () => {
      setRoute(parseHash());
    };

    window.addEventListener("hashchange", handleHashChange);

    return () => {
      window.removeEventListener(
        "hashchange",
        handleHashChange
      );
    };
  }, []);

  return route;
}

function go(agentId, page) {
  window.location.hash = agentId
    ? `#/agents/${encodeURIComponent(agentId)}/${
        page ?? "storm-overview"
      }`
    : "#/";
}

// Phase 1: navigate within the storm-wide experience, preserving (or changing) the selected
// county/horizon. Always writes both the destination page and the current county/horizon into
// the URL, so switching tabs never loses or silently resets either (requirement: storm, county
// and horizon stay consistent across all three screens; never silently fall back to the home
// county).
function goStorm(slug, page, { county, horizon } = {}) {
  const params = new URLSearchParams();
  if (county) params.set("county", county);
  if (horizon != null) params.set("horizon", String(horizon));
  const qs = params.toString();
  window.location.hash = `#/storms/${encodeURIComponent(slug)}/${page ?? "storm-overview"}${qs ? `?${qs}` : ""}`;
}

// Existing single-agent application.
function SingleAgentApp() {
  const [activePage, setActivePage] = useState(
    "storm-overview"
  );

  const [askAIOpen, setAskAIOpen] = useState(false);

  const { overview, error } = useOverview();

  const pages =
    overview?.domain === "dallas"
      ? TEMPLATE_PAGES.winter.pages
      : STUB_PAGES;

  const PageComponent =
    pages[activePage] ?? pages["storm-overview"];

  return (
    <div
      className="flex min-h-screen flex-col"
      style={APP_STYLE}
    >
      <Header
        onAskAIClick={() =>
          setAskAIOpen((previous) => !previous)
        }
        askAIOpen={askAIOpen}
      />

      <Navigation
        activePage={activePage}
        onNavigate={setActivePage}
      />

      <main
        className="flex-1 pt-[102px]"
        style={MAIN_STYLE}
      >
        {overview || error ? (
          <PageComponent
            overview={overview}
            overviewError={error}
          />
        ) : (
          <PageStatus title="Loading" />
        )}
      </main>

      <AskAI
        open={askAIOpen}
        onClose={() => setAskAIOpen(false)}
      />
    </div>
  );
}

// Multi-agent application.
function MultiAgentApp() {
  const { kind, agentId, page, slug, county, horizon } = useHashRoute();

  const [agents, setAgents] = useState(null);
  const [agentsError, setAgentsError] = useState("");

  const [askAIOpen, setAskAIOpen] = useState(false);
  const [askAIMode, setAskAIMode] = useState("panel");
  const [landingChatHost, setLandingChatHost] = useState(null);
  const [hasLandingChat, setHasLandingChat] = useState(false);
  const [pendingQuestion, setPendingQuestion] =
    useState("");

  useEffect(() => {
    fetchAgents()
      .then(setAgents)
      .catch((error) => {
        setAgentsError(
          `Can't list agents (${error.message}).`
        );
      });
  }, []);

  const agent =
    agents?.find((item) => item.id === agentId) ??
    null;

  const template = agent
    ? TEMPLATE_PAGES[agent.hazard]
    : null;

  const { overview, error } = useOverview(
    agentId,
    Boolean(template)
  );

  const PageComponent = template
    ? template.pages[page] ??
      template.pages["storm-overview"]
    : null;

  // Phase 1: the storm-wide experience's own agent metadata lookup (reuses the same /api/agents
  // list -- no new catalog). stormAgent is null while agents is still loading, or if slug is
  // unknown; StormShell reports that itself rather than App.jsx guessing at a loading/error UI.
  const isStorm = kind === "storm";
  const stormAgent = isStorm ? agents?.find((item) => item.id === slug) ?? null : null;

  // Shared Ask AI handler.
  // Landing searches use the same conversation in a normal-flow workspace.
  function askWithQuestion(question, mode = "panel") {
    setPendingQuestion(question);
    setAskAIMode(mode);
    if (mode === "inline") setHasLandingChat(true);
    setAskAIOpen(true);
  }

  function handleHeaderAskAI() {
    setAskAIMode("panel");
    setAskAIOpen((previous) => askAIMode !== "panel" || !previous);
  }

  // Hurricane cards open the new storm-wide experience by default; Dallas keeps opening its
  // existing single-agent screens exactly as before.
  function openAgent(id) {
    const target = agents?.find((a) => a.id === id);
    if (target?.hazard === "hurricane") goStorm(id, "storm-overview");
    else go(id);
  }

  const isLiveOperations = kind === "live-operations";
  const isLandingPage = kind === "home" || (kind === "agent" && !agent);

  // Live Operations asks the live-storms agent (backend/agent/live_adk.py): the storms NHC is tracking now.
  const chatAgentId = isLiveOperations ? "live-storms" : isStorm ? (stormAgent ? slug : null) : agent ? agentId : null;
  const chatHazard = isLiveOperations ? "live" : isStorm ? "hurricane" : agent?.hazard ?? null;
  const chatAgentName = isLiveOperations ? "Live storms · NOAA National Hurricane Center" : isStorm ? stormAgent?.name : agent?.name;

  return (
    <div
      className="flex min-h-screen flex-col"
      style={APP_STYLE}
    >
      {/* Main header remains dark navy. The landing page has its own inline Ask AI, so the
          header shortcut to the side-drawer version only shows on every other page. */}
      <Header
        onAskAIClick={handleHeaderAskAI}
        askAIOpen={askAIOpen}
        showAskAI={!isLandingPage}
      />

      {/* Secondary navigation only appears
          after selecting a storm agent. */}
      {agent && (
        <Navigation
          items={template?.nav ?? []}
          activePage={page}
          onNavigate={(nextPage) =>
            go(agentId, nextPage)
          }
          onHome={() => go(null)}
          title={`${agent.county}${
            agent.state ? `, ${agent.state}` : ""
          }`}
        />
      )}
      {isStorm && stormAgent && (
        <Navigation
          items={STORM_NAV}
          activePage={page}
          onNavigate={(nextPage) => goStorm(slug, nextPage, { county, horizon })}
          onHome={() => go(null)}
        />
      )}

      {/* All page backgrounds are light blue. */}
      <main
        className={`flex-1 ${
          agent || (isStorm && stormAgent) ? "pt-[102px]" : "pt-14"
        }`}
        style={MAIN_STYLE}
      >
        {isLiveOperations ? (
          <LiveOperations agents={agents} error={agentsError} onOpen={openAgent} onBack={() => go(null)} />
        ) : isLandingPage ? (
          agents || agentsError ? (
            <AgentLanding
              agents={agents}
              error={
                agentsError ||
                (agentId && agents
                  ? `Unknown agent ${agentId}`
                  : "")
              }
              onOpen={openAgent}
              onAsk={(question) =>
                askWithQuestion(question, "inline")
              }
              chatHostRef={setLandingChatHost}
              chatExpanded={askAIOpen && askAIMode === "inline"}
              hasChat={hasLandingChat}
              onResumeChat={() => { setAskAIMode("inline"); setAskAIOpen(true); }}
            />
          ) : (
            <PageStatus title="Loading agents" />
          )
        ) : isStorm ? (
          <StormShell
            agents={agents}
            slug={slug}
            page={page}
            county={county}
            horizon={horizon}
            onNavigate={(nextPage) => goStorm(slug, nextPage, { county, horizon })}
            onSelectCounty={(fips) => goStorm(slug, page, { county: fips, horizon })}
            onSelectHorizon={(h) => goStorm(slug, page, { county, horizon: h })}
            onOpenCountyDetail={(fips) => goStorm(slug, "storm-overview", { county: fips, horizon })}
            onAsk={askWithQuestion}
          />
        ) : overview || error ? (
          error ? (
            <PageStatus
              title={agent.name}
              error={error}
            />
          ) : (
            <PageComponent
              key={agentId}
              overview={overview}
              agentId={agentId}
              agent={agent}
              overviewError={error}
              onAsk={askWithQuestion}
            />
          )
        ) : (
          <PageStatus title={agent.name} />
        )}
      </main>

      {/* Single Ask AI instance.
          A new agent resets the conversation; the home page and Live Operations share one, so a
          conversation started on the home page carries over to the live-storms agent and back. */}
      <AskAI
        key={isLiveOperations ? "none" : chatAgentId ?? "none"}
        open={askAIOpen && (!isLiveOperations || askAIMode !== "inline")}
        onClose={() => {
          setAskAIOpen(false);
          // The hero search input is `inert` while the chat is expanded (see AgentLanding);
          // that attribute only clears after this state update commits, so focusing it has to
          // wait a tick -- an immediate call here would silently no-op on an inert element.
          if (askAIMode === "inline") setTimeout(() => document.getElementById("home-storm-question")?.focus({ preventScroll: true }), 0);
        }}
        fullScreen={askAIMode === "full"}
        inlineHost={isLandingPage && askAIMode === "inline" ? landingChatHost : null}
        agentId={chatAgentId}
        hazard={chatHazard}
        agentName={chatAgentName}
        pendingQuestion={pendingQuestion}
        onPendingSent={() =>
          setPendingQuestion("")
        }
      />
    </div>
  );
}

// Detect backend mode automatically.
export default function App() {
  const [mode, setMode] = useState(null);

  useEffect(() => {
    fetchHealth()
      .then((health) => {
        setMode(
          health.domain === "multi"
            ? "multi"
            : "single"
        );
      })
      .catch(() => {
        setMode("single");
      });
  }, []);

  if (mode === null) {
    return (
      <div
        className="min-h-screen"
        style={{
          backgroundColor: THEME.background,
        }}
      />
    );
  }

  return mode === "multi" ? (
    <MultiAgentApp />
  ) : (
    <SingleAgentApp />
  );
}
