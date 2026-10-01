import { useState } from "react";
import Header from "./components/Header.jsx";
import Navigation from "./components/Navigation.jsx";
import AskAI from "./components/AskAI.jsx";
import StormOverview from "./pages/StormOverview.jsx";
import RiskMap from "./pages/RiskMap.jsx";
import ResourcePlanner from "./pages/ResourcePlanner.jsx";

const PAGES = {
  "storm-overview": StormOverview,
  "risk-map": RiskMap,
  "resource-planner": ResourcePlanner,
};

export default function App() {
  const [activePage, setActivePage] = useState("storm-overview");
  const [selectedCounty, setSelectedCounty] = useState(null);
  const [askAIOpen, setAskAIOpen] = useState(false);

  // Shared navigation handler so any page can switch tabs the same way the
  // sub-nav does. An optional county is carried along for when Risk Map
  // later wants to know which county a user came from (e.g. Expected
  // Impacts "View details"); Risk Map doesn't use it yet.
  function navigateTo(pageId, county) {
    setActivePage(pageId);
    if (county !== undefined) setSelectedCounty(county);
  }

  const PageComponent = PAGES[activePage] ?? StormOverview;

  return (
    <div className="app-shell">
      <Header onAskAIClick={() => setAskAIOpen((v) => !v)} askAIOpen={askAIOpen} />
      <Navigation activePage={activePage} onNavigate={navigateTo} />
      <main className="page-content">
        <PageComponent onNavigate={navigateTo} selectedCounty={selectedCounty} />
      </main>
      <AskAI open={askAIOpen} onClose={() => setAskAIOpen(false)} />
    </div>
  );
}
