import { useEffect, useState } from "react";
import { fetchLiveStatus } from "./api.js";
import { fmt } from "./dallas/format.js";
import OperationalCountyScenarios from "./components/OperationalCountyScenarios.jsx";

// Decorative photography is not used as a source of live storm information.
// Vite serves public/images at /images in development and copies it into the build.
const HURRICANE_IMAGE = "/images/hurricane-satellite.png";
const WINTER_IMAGE = "https://images.unsplash.com/photo-1517299321609-52687d1bc55a?auto=format&fit=crop&w=1000&q=80";
const QUESTIONS = ["Which areas are highest risk?", "Where should we stage resources?", "Will this storm cause power outages?", "What shelters might be needed?"];

function Icon({ name, size = 15 }) {
  const common = { width: size, height: size, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 1.8, strokeLinecap: "round", strokeLinejoin: "round", "aria-hidden": true };
  if (name === "search") return <svg {...common}><circle cx="10.8" cy="10.8" r="7"/><path d="m16 16 5 5"/></svg>;
  if (name === "arrow") return <svg {...common}><path d="M4 12h16m-7-7 7 7-7 7"/></svg>;
  if (name === "pin") return <svg {...common}><path d="M20 10c0 5-8 12-8 12S4 15 4 10a8 8 0 1 1 16 0Z"/><circle cx="12" cy="10" r="2.5"/></svg>;
  if (name === "bolt") return <svg {...common}><path d="m13 2-9 12h7l-1 8 10-12h-7z"/></svg>;
  if (name === "chart") return <svg {...common}><path d="M4 20V12m5 8V7m5 13V10m5 10V4"/></svg>;
  if (name === "scenario") return <svg {...common}><path d="M3 17 9 11l4 4 8-9"/></svg>;
  if (name === "shelter") return <svg {...common}><path d="m3 10 9-7 9 7v11H3zM9 21v-8h6v8"/></svg>;
  return null;
}

function SearchBar({ onAsk }) {
  const [query, setQuery] = useState("");
  function submit(e) {
    e.preventDefault();
    if (!query.trim()) return;
    onAsk(query.trim());
    setQuery("");
  }
  return <div className="mt-3 max-w-[720px]">
    <form onSubmit={submit} className="flex items-center gap-3 rounded-full border border-[#d6e6f5] bg-white px-4 py-2 shadow-[0_5px_18px_rgba(16,49,88,0.12)]">
      <span className="shrink-0 text-[#247ddd]"><Icon name="search" size={18}/></span>
      <label className="sr-only" htmlFor="home-storm-question">Ask StormReady AI</label>
      <input id="home-storm-question" value={query} onChange={(e) => setQuery(e.target.value)} className="min-w-0 flex-1 border-0 bg-transparent py-1.5 text-[13px] text-[#123354] outline-none placeholder:text-[#8495a7]" placeholder="Ask about any storm, location, or action to take..." />
      <button type="submit" aria-label="Submit question" disabled={!query.trim()} className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-[#287fe0] text-white transition hover:bg-[#176bbf] disabled:opacity-60"><Icon name="arrow" size={19}/></button>
    </form>
    <div className="mt-3">
      <p className="mb-2 text-[11px] font-semibold text-[#526e88]">
        Try these questions:
      </p>
      
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        {QUESTIONS.map((q) => (
          <button
          key={q}
          type="button"
          onClick={() => onAsk(q)}
          className="min-h-[48px] rounded-md border border-[#d5e4f2] bg-white/75 px-3 py-2 text-left text-[11px] leading-snug text-[#31516e] shadow-sm transition hover:border-[#287fe0] hover:bg-white hover:text-[#1874ce]"
          >
            {q}
            </button>
          ))}
      </div>
</div>
  </div>;
}

function LivePanel({ status }) {
  const online = status?.status === "online";
  return <a href="#/live-operations" aria-label="Live Storm Updates — View Live Details" className="block text-left transition hover:ring-1 hover:ring-[#287fe0] w-full max-w-[280px] rounded-xl border border-white/70 bg-white/95 p-3 shadow-[0_12px_30px_rgba(16,47,78,0.16)] backdrop-blur-sm">
    <div className="flex items-center justify-between border-b border-[#e8eef6] pb-3">
      <span className="flex items-center gap-2 text-[13px] font-bold text-[#143350]"><span className={`h-2 w-2 rounded-full ${online ? "bg-[#22a86a]" : "bg-[#a3b0bf]"}`}/>Live Storm Updates</span>
      <span className="text-[11px] font-medium text-[#287fe0]">{online ? "Connected" : "Status unavailable"}</span>
    </div>
    <div className="mt-3 flex items-center justify-between gap-3 rounded-lg bg-[#f1f6fb] px-3 py-3">
      <div><div className="text-[12px] font-bold text-[#163554]">Active storms tracked</div><div className="mt-1 text-[11px] text-[#6b8197]">NOAA / NWS live feed</div></div>
      <span className="text-xl font-bold text-[#287fe0]">{status?.active_storms_count == null ? "–" : fmt(status.active_storms_count)}</span>
    </div>
    <div className="mt-2 flex items-center justify-between px-2 text-[11px] text-[#6b8197]"><span>Tropical alerts</span><strong className="text-[#163554]">{status?.active_tropical_alerts_count == null ? "–" : fmt(status.active_tropical_alerts_count)}</strong></div>
    <span className="mt-2 block text-right text-[11px] font-semibold text-[#287fe0]">View Live Details →</span>
  </a>;
}

export default function AgentLanding({ agents, error, onOpen, onAsk, chatHostRef, chatExpanded, hasChat, onResumeChat }) {
  const [live, setLive] = useState(null);
  useEffect(() => {
    let cancelled = false;
    fetchLiveStatus().then((result) => { if (!cancelled) setLive(result); }).catch(() => {});
    return () => { cancelled = true; };
  }, []);
  return <div className="min-h-screen bg-[#f4f8fc] text-[#123352]">
    <section className="landing-hero">
      <div className="landing-hero__image" aria-hidden="true"><img src={HURRICANE_IMAGE} alt="" /></div>
      <div
        className={`landing-hero__content mx-auto grid max-w-[1420px] grid-cols-1 items-center gap-4 px-6 lg:grid-cols-[minmax(0,1fr)_280px] lg:px-10 ${chatExpanded ? "landing-hero__content--collapsed" : ""}`}
        inert={chatExpanded}
        aria-hidden={chatExpanded}
      >
        <div className="min-w-0">
          <p className="text-[10px] font-bold uppercase tracking-[0.8px] text-[#607d98]">Real-time storms · Predicted impacts · Actionable plans</p>
          <h1 className="mt-1 text-[30px] font-extrabold leading-tight tracking-tight text-[#112f4d] sm:text-[36px]">Prepare for <span className="text-[#287fe0]">active storms</span></h1>
          <p className="mt-1 max-w-[680px] text-[13px] leading-relaxed text-[#4f6981]">Explore historical storm impacts, identify high-risk locations, and get AI-powered preparedness recommendations for your community.</p>
          <SearchBar onAsk={onAsk}/>
          {hasChat && !chatExpanded && <button type="button" onClick={onResumeChat} className="mt-2 text-xs font-semibold text-accent hover:underline" aria-controls="landing-chat">Resume conversation</button>}
        </div>
        <div className="landing-hero__live flex justify-start lg:justify-end"><LivePanel status={live}/></div>
      </div>
    </section>
    <div id="landing-chat" className={`landing-chat ${chatExpanded ? "landing-chat--expanded" : ""}`} inert={!chatExpanded} aria-hidden={!chatExpanded}>
      <div className="landing-chat__clip"><div ref={chatHostRef} /></div>
    </div>
    <div className="mx-auto max-w-[1420px] px-6 py-10 lg:px-10">
      {error && <div role="alert" className="mb-4 rounded-lg bg-red-50 p-3 text-sm text-red-700">{error}</div>}
      <OperationalCountyScenarios agents={agents} onOpen={onOpen} hurricaneImage={HURRICANE_IMAGE} winterImage={WINTER_IMAGE} />
    </div>
  </div>;
}
