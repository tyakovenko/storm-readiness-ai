import { useState } from "react";
import Header from "./components/Header.jsx";
import Navigation from "./components/Navigation.jsx";
import AskAI from "./components/AskAI.jsx";
import StormOverview from "./pages/StormOverview.jsx";
import ResourcePlanner from "./pages/ResourcePlanner.jsx";
import DallasOverview from "./dallas/DallasOverview.jsx";
import DallasPlanner from "./dallas/DallasPlanner.jsx";
import { useOverview } from "./api.js";
import { PageStatus } from "./components/Page.jsx";

// Two screens plus the Ask AI panel. The Risk Map lives inside Storm Overview.
const PAGES = {
  "storm-overview": StormOverview,
  "resource-planner": ResourcePlanner,
};
// The backend's AGENT_DOMAIN decides which set renders (no UI toggle, by design).
const DALLAS_PAGES = {
  "storm-overview": DallasOverview,
  "resource-planner": DallasPlanner,
};

export default function App() {
  const [activePage, setActivePage] = useState("storm-overview");
  const [askAIOpen, setAskAIOpen] = useState(false);
  // Loaded once and shared, so both screens show the same storm and advisory.
  const { overview, error } = useOverview();

  const pages = overview?.domain === "dallas" ? DALLAS_PAGES : PAGES;
  const PageComponent = pages[activePage] ?? pages["storm-overview"];

  return (
    <div className="flex min-h-screen flex-col bg-canvas">
      <Header onAskAIClick={() => setAskAIOpen((v) => !v)} askAIOpen={askAIOpen} />
      <Navigation activePage={activePage} onNavigate={setActivePage} />
      {/* Clears the fixed header (56px) + sub-nav (46px). */}
      <main className="flex-1 bg-canvas pt-[102px]">
        {overview || error ? (
          <PageComponent overview={overview} overviewError={error} />
        ) : (
          <PageStatus title="Loading" />
        )}
      </main>
      <AskAI open={askAIOpen} onClose={() => setAskAIOpen(false)} />
    </div>
  );
}
