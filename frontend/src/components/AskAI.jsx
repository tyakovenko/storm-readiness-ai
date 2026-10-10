import { useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { chatUrl } from "../api.js";
import Simulator, { useSimulator } from "./simulate/Simulator.jsx";

// All agent/trust logic lives in the backend. This panel only sends a question to the chat endpoint
// and shows what comes back -- in plain language: no model names, no raw check or tool names.

const EXAMPLES = [
  "What's the outage risk by county?",
  "Where should we stage trucks?",
  "We only have 6 trucks and Shelter 2 is closed. Re-plan.",
  "What should residents do now?",
];

const DALLAS_EXAMPLES = [
  "How should we prepare for this storm?",
  "What if we only have 30 trucks and Fair Park is closed?",
  "Has Dallas had a storm like this before?",
  "What should residents do if the power goes out?",
];

// Mock-only: the scripted client misbehaves once so the trust layer has something to block.
const TRUST_DEMOS = ["Trust demo: hallucinate a number", "Trust demo: overconfident outage risk"];
const DALLAS_TRUST_DEMOS = ["Trust demo: shelter demand without its range"];

const HURRICANE_EXAMPLES = [
  "How bad could the power outages be?",
  "Has this county had a storm like this before?",
  "What shelters do we have outside the surge zone?",
  "What should residents do to evacuate?",
];
const HURRICANE_TRUST_DEMOS = ["Trust demo: outage estimate without its range"];

// The storms NHC is tracking now (backend/agent/live_adk.py). No storm names here: they change.
const LIVE_EXAMPLES = [
  "Which storms are active right now?",
  "Where are the active storms headed?",
  "Which counties are most at risk right now?",
  "Where should trucks be staged for the strongest storm?",
  "What hospitals and fire departments do the at-risk counties have?",
  "Are there hurricane warnings in effect?",
];

// Home page, nothing open yet (backend/agent/landing_router.py routes current-storm questions live).
const NONE_EXAMPLES = [
  "Which storms are active right now?",
  "Which counties are at risk from current storms?",
  "Tell me about Hurricane Beryl in Harris County",
  "Tell me about the Dallas winter storm scenario",
];

const INTRO = {
  live: "I can tell you where today's storms are headed, which counties are at risk, and what shelters, hospitals and fire crews they have.",
  hurricane: "I can walk you through this county's storm: expected outages, shelters, past storms, and what's happening live right now.",
  winter: "I can help you prepare for this winter storm: outages, shelters, crews, and what past storms looked like.",
  none: "Ask about the storms happening right now, or about a past-storm scenario like Hurricane Beryl in Harris County.",
  stub: "Ask about the storm's impact, the staging plan, or a what-if.",
};

const NOTE = {
  live: "Live NOAA storm data. Outage figures are model estimates shown as ranges.",
  hurricane: "A real past forecast replayed for practice. Live storms are available too: just ask.",
  winter: "A planning scenario built from real past storms. Estimates are ranges, not forecasts.",
  none: "Live storms and past-storm scenarios are both available.",
  stub: "Demo data only, not a real forecast.",
};

const PLACEHOLDER = {
  live: "Ask about today's storms, at-risk counties or resources…",
  none: "Ask about current storms or a past-storm scenario…",
};

// Plain-language names for what the assistant looked up. Unknown steps fall back to their words.
const STEP_LABELS = {
  get_live_storms: "Checked the storms NOAA is tracking now",
  get_forecast_track: "Read the official forecast track",
  get_counties_at_risk: "Scored the counties along the track",
  get_county_resources: "Looked up the county's shelters, hospitals and fire departments",
  get_nws_alerts: "Checked active weather warnings",
  get_storm_alert: "Read the storm alert",
  get_advisory: "Read the storm advisory",
  estimate_impact: "Ran the outage model",
  predict_impact: "Ran the outage model",
  find_similar_storms: "Compared with past storms",
  get_storm_impacts: "Looked up a past storm's impacts",
  query_assets: "Looked up shelters and facilities",
  plan_shelters: "Built a shelter plan",
  plan_response: "Built a response plan",
  solve_staging: "Worked out staging",
  diff_plans: "Compared the what-if with the default plan",
  get_enso_context: "Checked El Niño / La Niña conditions",
  retrieve_guidance: "Pulled official safety guidance",
  estimate_demand: "Estimated demand from past storms",
  generate_scenarios: "Looked at the range of possible tracks",
};
const stepLabel = (name) => STEP_LABELS[name] ?? name.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());

// The models answer in light markdown: headings, * / - bullets (nested by indent), numbered
// lists, **bold** and `code`. Render that subset; anything else stays plain text. No library.
function Inline({ text }) {
  return text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g).map((part, i) =>
    part.startsWith("**") && part.endsWith("**") && part.length > 4 ? <strong key={i}>{part.slice(2, -2)}</strong>
      : part.startsWith("`") && part.endsWith("`") && part.length > 2 ? <code key={i} className="text-[0.85em]">{part.slice(1, -1)}</code>
        : part,
  );
}

const HEADING_RE = /^#{1,6}\s+(.*)$/;
const LIST_RE = /^(\s*)([*-]|\d+[.)])\s+(.*)$/;

// Lines -> blocks: heading, list (items with depth and number, if any), paragraph.
function toBlocks(text) {
  const blocks = [];
  for (const line of text.split("\n")) {
    const heading = line.trim().match(HEADING_RE);
    const item = line.match(LIST_RE);
    const last = blocks[blocks.length - 1];
    if (heading) {
      blocks.push({ type: "heading", text: heading[1] });
    } else if (item) {
      const entry = { depth: Math.min(Math.floor(item[1].replace(/\t/g, "  ").length / 2), 3),
        marker: /\d/.test(item[2]) ? item[2] : null, text: item[3] };
      if (last?.type === "list") last.items.push(entry);
      else blocks.push({ type: "list", items: [entry] });
    } else if (!line.trim()) {
      blocks.push({ type: "break" });
    } else if (last?.type === "paragraph") {
      last.lines.push(line.trim());
    } else {
      blocks.push({ type: "paragraph", lines: [line.trim()] });
    }
  }
  return blocks.filter((b) => b.type !== "break");
}

function AnswerText({ text }) {
  return (
    <div className="my-2 flex flex-col gap-2 leading-normal">
      {toBlocks(text).map((b, i) => {
        if (b.type === "heading") return <p key={i} className="mt-1 font-bold text-ink"><Inline text={b.text} /></p>;
        if (b.type === "paragraph") {
          return <p key={i}>{b.lines.map((l, j) => <span key={j}>{j > 0 && <br />}<Inline text={l} /></span>)}</p>;
        }
        return (
          <ul key={i} className="flex flex-col gap-1">
            {b.items.map((it, j) => (
              <li key={j} className="flex gap-1.5" style={{ marginLeft: `${it.depth * 1.1}rem` }}>
                <span aria-hidden="true" className="shrink-0 text-muted">{it.marker ?? (it.depth ? "◦" : "•")}</span>
                <span><Inline text={it.text} /></span>
              </li>
            ))}
          </ul>
        );
      })}
    </div>
  );
}

function SparkIcon({ className = "size-4" }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M12 3l1.8 4.7L18.5 9.5l-4.7 1.8L12 16l-1.8-4.7L5.5 9.5l4.7-1.8z" />
      <path d="M19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8z" />
    </svg>
  );
}

function AgentReply({ result, quiet = false }) {
  const blocked = result.status === "blocked" || !result.answer;
  const steps = [...new Set(result.tool_calls.map((t) => t.name))];
  return (
    <div>
      {blocked ? (
        <p className="my-1 leading-relaxed text-[#4f6981]">
          I couldn&apos;t give you a reliable answer to that one, so I&apos;m not showing a guess.
          Try asking it a little differently, or about a specific storm or county.
        </p>
      ) : (
        <div className="leading-relaxed text-ink"><AnswerText text={result.answer} /></div>
      )}

      {!blocked && !quiet && (
        <p className="mt-2 inline-flex items-center gap-1 text-[0.72rem] font-medium text-[#2e7d5b]">
          <span aria-hidden="true">✓</span> Checked against the data
        </p>
      )}

      {(result.sources.length > 0 || steps.length > 0 || result.why.length > 0) && (
        <details className="group mt-2 border-t border-[#e3edf7] pt-2 text-[0.8rem]">
          <summary className="cursor-pointer list-none font-semibold text-accent [&::-webkit-details-marker]:hidden">
            <span className="inline-block transition-transform group-open:rotate-90" aria-hidden="true">›</span> How I got this
          </summary>
          {steps.length > 0 && (
            <ol className="mt-1.5 list-decimal space-y-0.5 pl-5 text-[#4f6981]">
              {steps.map((s) => <li key={s}>{stepLabel(s)}</li>)}
            </ol>
          )}
          {result.why.length > 0 && (
            <ul className="mt-1.5 list-disc space-y-0.5 pl-5 text-[#4f6981]">
              {result.why.map((w) => <li key={w.county}><strong>{w.county}:</strong> {w.reasons.join("; ")}</li>)}
            </ul>
          )}
          {result.sources.length > 0 && (
            <>
              <p className="mt-2 font-semibold text-[#31516e]">Sources</p>
              <ul className="mt-0.5 list-disc space-y-0.5 pl-5 text-[#4f6981]">{result.sources.map((s) => <li key={s}>{s}</li>)}</ul>
            </>
          )}
        </details>
      )}
    </div>
  );
}

function TypingDots() {
  return (
    <div className="flex items-center gap-2 self-start rounded-2xl rounded-tl-sm border border-[#DCE7F2] bg-white px-4 py-3 text-[0.85rem] text-[#4f6981] shadow-sm" role="status">
      <span className="flex gap-1" aria-hidden="true">
        {[0, 1, 2].map((i) => (
          <span key={i} className="size-1.5 animate-bounce rounded-full bg-[#287fe0] motion-reduce:animate-none" style={{ animationDelay: `${i * 150}ms` }} />
        ))}
      </span>
      Looking up the latest data…
    </div>
  );
}

// agentId/hazard/agentName come from the multi-agent app; the single-agent app passes none.
// pendingQuestion/onPendingSent let the storm home page's search box hand off a question to this
// same panel instead of a second chat implementation.
// fullScreen: the landing page's "submit a question" flow expands this same panel/state into a
// full-workspace view (below the global header) instead of the narrow side drawer used everywhere
// else -- same messages/health/input state either way, just a different wrapper around it.
export default function AskAI({ open, onClose, agentId = null, hazard = null, agentName = null, disabled = false,
  pendingQuestion = "", onPendingSent, fullScreen = false, inlineHost = null }) {
  const inputId = useId();
  const messageListRef = useRef(null);
  const inputRef = useRef(null);
  const sendingRef = useRef(false);
  const [health, setHealth] = useState(null);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [tab, setTab] = useState("ask"); // "ask" | "simulate"
  const [expanded, setExpanded] = useState(false);
  const endRef = useRef(null);
  const full = fullScreen || expanded;
  const simState = useSimulator();

  useEffect(() => {
    fetch("/api/health")
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then(setHealth)
      .catch(() => setError("I can't reach the server right now. Please make sure the backend is running."));
  }, []);

  useEffect(() => {
    if (!open) return;
    if (inlineHost) {
      const list = messageListRef.current;
      list?.scrollTo({ top: list.scrollHeight, behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth" });
    } else endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading, open, inlineHost]);

  useEffect(() => {
    if (open && inlineHost) inputRef.current?.focus({ preventScroll: true });
  }, [open, inlineHost]);

  useEffect(() => {
    if (!open) return;
    function onKeyDown(e) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open, onClose]);

  useEffect(() => {
    if (open && pendingQuestion && !loading && !sendingRef.current) {
      send(pendingQuestion);
      onPendingSent?.();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, pendingQuestion, loading]);

  async function send(text) {
    const question = text.trim();
    if (!question || sendingRef.current) return;
    sendingRef.current = true;
    // Only answers that were shown go back as history; blocked ones are dropped.
    const history = messages
      .filter((m) => m.role === "user" || m.result?.answer)
      .map((m) => ({ role: m.role, content: m.role === "user" ? m.content : m.result.answer }));
    setMessages((prev) => [...prev, { role: "user", content: question }]);
    setInput("");
    setError("");
    setLoading(true);
    try {
      const r = await fetch(chatUrl(agentId), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: question, history }),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const result = await r.json();
      setMessages((prev) => [...prev, { role: "assistant", result }]);
    } catch {
      setError("Something went wrong getting that answer. Please try again in a moment.");
    } finally {
      sendingRef.current = false;
      setLoading(false);
    }
  }

  // Which template answers: the open agent's hazard (multi), else the single service's domain.
  // On the multi-agent home page with no agent open yet, hazard is null and health.domain is
  // "multi" -- that's "none", not a silent fallback to Dallas's "winter".
  const kind = hazard ?? (health?.domain === "multi" ? "none" : health?.domain === "dallas" ? "winter" : "stub");
  const base = { winter: DALLAS_EXAMPLES, hurricane: HURRICANE_EXAMPLES, live: LIVE_EXAMPLES, none: NONE_EXAMPLES }[kind] ?? EXAMPLES;
  const demos = { winter: DALLAS_TRUST_DEMOS, hurricane: HURRICANE_TRUST_DEMOS, live: [], none: [] }[kind] ?? TRUST_DEMOS;
  const examples = disabled ? [] : health?.mock ? [...base, ...demos] : base;
  const subtitle = agentName ?? (kind === "none" ? "Live storms and past-storm scenarios" : null);

  const backButton = (
    <button type="button" onClick={onClose}
      className="inline-flex shrink-0 cursor-pointer items-center gap-1.5 rounded-full border border-white/80 bg-white/70 px-3 py-1.5 text-[0.85rem] font-semibold text-accent shadow-xs hover:bg-white">
      <span aria-hidden="true">&larr;</span> Back to Overview
    </button>
  );

  // The landing page's own chat keeps the hero's kicker + headline: it continues the hero the user
  // just searched from, not a separate tool panel.
  const headerRow = inlineHost ? (
    <div className="grid grid-cols-[1fr_auto_1fr] items-start gap-3">
      <div aria-hidden="true" />
      <div className="text-center">
        <p className="text-[10px] font-bold uppercase tracking-[0.8px] text-[#607d98]">Real-time storms · Predicted impacts · Actionable plans</p>
        <h1 className="mt-1 text-[28px] font-extrabold leading-tight tracking-tight text-[#112f4d] sm:text-[34px]">Prepare for <span className="text-[#287fe0]">active storms</span></h1>
        <p className="mx-auto mt-1 max-w-[560px] text-[13px] leading-relaxed text-[#4f6981]">Explore historical storm impacts, identify high-risk locations, and get AI-powered preparedness recommendations for your community.</p>
      </div>
      <div className="justify-self-end">{backButton}</div>
    </div>
  ) : (
    <div className="flex items-start justify-between gap-3">
      <div className="flex min-w-0 items-center gap-3">
        <span className="flex size-10 shrink-0 items-center justify-center rounded-2xl bg-white/80 text-[#287fe0] shadow-[0_4px_14px_rgba(40,127,224,0.18)]">
          <SparkIcon className="size-5" />
        </span>
        <div className="min-w-0">
          <h2 className="text-[1.08rem] font-bold leading-tight text-[#112f4d]">Ask StormReady AI</h2>
          {subtitle && <p className="truncate text-[0.8rem] text-[#4f6981]">{subtitle}</p>}
        </div>
      </div>
      {fullScreen ? backButton : (
        <div className="flex shrink-0 gap-1.5">
          <button type="button" className="flex size-8 cursor-pointer items-center justify-center rounded-full bg-white/70 text-[#4f6981] hover:bg-white hover:text-ink"
            onClick={() => setExpanded((e) => !e)} aria-label={expanded ? "Collapse Ask AI" : "Expand Ask AI"} aria-pressed={expanded}>
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              {expanded ? <path d="M9 4v5H4M15 4v5h5M9 20v-5H4M15 20v-5h5" /> : <path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5" />}
            </svg>
          </button>
          <button type="button" className="flex size-8 cursor-pointer items-center justify-center rounded-full bg-white/70 text-lg leading-none text-[#4f6981] hover:bg-white hover:text-ink" onClick={onClose} aria-label="Close Ask AI">
            &times;
          </button>
        </div>
      )}
    </div>
  );

  const note = (
    <p className="inline-flex items-start gap-1.5 text-[0.75rem] leading-snug text-[#4f6981]" role="note">
      <span aria-hidden="true" className="mt-px text-[#287fe0]">ⓘ</span>
      {disabled ? "Open a county to ask questions about it." : NOTE[kind]}
    </p>
  );

  const tabs = (
    <div className="flex gap-1 rounded-full bg-white/60 p-1 shadow-xs" role="tablist" aria-label="Ask AI mode">
      {[["ask", "Ask", "Questions about storms, risk and resources"], ["simulate", "Simulate", "Learn how to get prepared"]].map(([id, label, sub]) => (
        <button key={id} type="button" role="tab" aria-selected={tab === id} onClick={() => setTab(id)}
          className={`flex-1 cursor-pointer rounded-full px-4 py-1.5 text-left transition ${tab === id ? "bg-white text-[#112f4d] shadow-sm" : "text-[#4f6981] hover:text-[#112f4d]"}`}>
          <span className="block text-[0.85rem] font-bold">{label}</span>
          <span className="block truncate text-[0.68rem] font-medium opacity-80">{sub}</span>
        </button>
      ))}
    </div>
  );

  const header = (
    <div className="shrink-0 bg-gradient-to-br from-[#cfe5ff] via-[#e3f0ff] to-[#f5faff] px-5 pb-4 pt-5 sm:px-6">
      {headerRow}
      <div className="mt-3">
        {tab === "ask" ? note : (
          <p className="text-[0.75rem] text-[#4f6981]">A practice exercise for response teams: fire, police, EMS, transportation, council, emergency management and utilities.</p>
        )}
      </div>
      <div className="mx-auto mt-3 max-w-[820px]">{tabs}</div>
    </div>
  );
  const simBody = <Simulator state={simState} />;

  const messageList = (
    <div ref={messageListRef} className="flex min-h-[120px] flex-1 flex-col gap-3 overflow-y-auto [overflow-wrap:anywhere]" aria-live="polite">
      {messages.length === 0 && !inlineHost && (
        <div className="flex gap-2.5">
          <span className="flex size-7 shrink-0 items-center justify-center rounded-full bg-[#e3f0ff] text-[#287fe0]"><SparkIcon /></span>
          <div className="rounded-2xl rounded-tl-sm border border-[#DCE7F2] bg-white px-4 py-3 text-[0.9rem] leading-relaxed text-ink shadow-sm">
            <p className="font-semibold text-[#112f4d]">Hi! How can I help?</p>
            <p className="mt-0.5 text-[#4f6981]">{INTRO[kind] ?? INTRO.stub}</p>
          </div>
        </div>
      )}
      {messages.map((m, i) =>
        m.role === "user" ? (
          <div key={i} className="max-w-[85%] self-end rounded-2xl rounded-tr-sm bg-gradient-to-br from-[#3b8cf0] to-[#2470d6] px-4 py-2.5 text-white shadow-[0_4px_12px_rgba(40,120,232,0.25)]">{m.content}</div>
        ) : inlineHost ? (
          <div key={i} className="max-w-[92%]"><AgentReply result={m.result} quiet /></div>
        ) : (
          <div key={i} className="flex max-w-[96%] gap-2.5">
            <span className="flex size-7 shrink-0 items-center justify-center rounded-full bg-[#e3f0ff] text-[#287fe0]"><SparkIcon /></span>
            <div className="min-w-0 rounded-2xl rounded-tl-sm border border-[#DCE7F2] bg-white px-4 py-3 text-[0.9rem] shadow-sm"><AgentReply result={m.result} /></div>
          </div>
        ),
      )}
      {loading && <TypingDots />}
      {error && <p className="rounded-xl bg-bad-bg px-3 py-2 text-[0.85rem] text-bad-text" role="alert">{error}</p>}
      <div ref={endRef} />
    </div>
  );

  // Landing-page chat (inlineHost) reuses the hero search bar's look; the drawer and full screen
  // show suggestions as soft chips, only until the conversation starts.
  const exampleChips = inlineHost ? (
    <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
      {examples.map((q) => (
        <button
          key={q}
          type="button"
          onClick={() => send(q)}
          disabled={loading}
          className="min-h-[48px] rounded-md border border-[#d5e4f2] bg-white/75 px-3 py-2 text-left text-[11px] leading-snug text-[#31516e] shadow-sm transition hover:border-[#287fe0] hover:bg-white hover:text-[#1874ce] disabled:opacity-55"
        >
          {q}
        </button>
      ))}
    </div>
  ) : messages.length === 0 && examples.length > 0 ? (
    <div>
      <p className="mb-1.5 text-[0.72rem] font-semibold uppercase tracking-wide text-[#607d98]">Try asking</p>
      <div className="flex flex-wrap gap-1.5">
        {examples.map((q) => (
          <button
            key={q}
            type="button"
            onClick={() => send(q)}
            disabled={loading}
            className="cursor-pointer rounded-full border border-[#D5E4F4] bg-white px-3 py-1.5 text-left text-[0.8rem] text-[#2470d6] shadow-xs transition hover:border-[#9cc3f2] hover:bg-[#EEF5FF]"
          >
            {q}
          </button>
        ))}
      </div>
    </div>
  ) : null;

  // Enter (native form submit) and clicking the button both call this same handler.
  const placeholder = PLACEHOLDER[kind] ?? "Ask a question, e.g. What if Shelter 4 is closed?";
  const inputForm = (
    <form
      className={inlineHost
        ? "flex items-center gap-3 rounded-full border border-[#d6e6f5] bg-white px-4 py-2 shadow-[0_5px_18px_rgba(16,49,88,0.12)]"
        : "flex items-center gap-2 rounded-full border border-[#d6e6f5] bg-white py-1.5 pl-4 pr-1.5 shadow-[0_5px_18px_rgba(16,49,88,0.10)] focus-within:border-[#9cc3f2]"}
      onSubmit={(e) => {
        e.preventDefault();
        send(input);
      }}
    >
      <label htmlFor={inputId} className="sr-only">Ask a question</label>
      <input
        id={inputId}
        ref={inputRef}
        className="min-w-0 flex-1 border-0 bg-transparent py-1.5 text-[0.92rem] text-[#123354] outline-none placeholder:text-[#8495a7]"
        value={input}
        onChange={(e) => setInput(e.target.value)}
        placeholder={placeholder}
        disabled={loading}
      />
      <button
        type="submit"
        aria-label="Send question"
        disabled={loading || !input.trim()}
        className="flex size-9 shrink-0 cursor-pointer items-center justify-center rounded-full bg-gradient-to-br from-[#3b8cf0] to-[#2470d6] text-white transition hover:brightness-110 disabled:cursor-default disabled:opacity-50"
      >
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M4 12h16m-7-7 7 7-7 7"/></svg>
      </button>
    </form>
  );

  if (inlineHost) {
    return createPortal(
      <section className="landing-chat__workspace" aria-label="Ask StormReady AI">
        {headerRow}
        <div className="mx-auto w-full max-w-[560px]">{tabs}</div>
        <div className={tab === "ask" ? "contents" : "hidden"}>
          <div className="text-center">{note}</div>
          {messageList}
          {exampleChips}
          {inputForm}
        </div>
        <div className={tab === "simulate" ? "min-h-0 flex-1 overflow-y-auto" : "hidden"}>{simBody}</div>
      </section>, inlineHost,
    );
  }

  if (full) {
    return (
      <aside
        className={`fixed inset-x-0 bottom-0 z-120 flex flex-col overflow-hidden bg-[#F5F9FE] transition-opacity duration-[180ms] ease-[ease] ${
          fullScreen ? "top-14" : "top-0"} ${open ? "opacity-100" : "pointer-events-none opacity-0"}`}
        aria-hidden={!open}
        aria-label={fullScreen ? "Ask StormReady AI" : "Ask AI"}
      >
        {header}
        <div className={`mx-auto flex min-h-0 w-full max-w-[820px] flex-1 flex-col gap-3 overflow-hidden px-5 py-5 sm:px-8 ${tab === "ask" ? "" : "hidden"}`}>
          {messageList}
          {exampleChips && <div className="shrink-0">{exampleChips}</div>}
          <div className="shrink-0">{inputForm}</div>
        </div>
        <div className={tab === "simulate" ? "min-h-0 flex-1 overflow-y-auto" : "hidden"}>
          <div className="mx-auto w-full max-w-[1100px] px-5 py-5 sm:px-8">{simBody}</div>
        </div>
      </aside>
    );
  }

  return (
    <>
      {/* Backdrop and panel sit above the fixed header (z 100) and sub-nav (z 90). */}
      {open && <div className="fixed inset-0 z-110 bg-[rgba(15,39,68,0.15)]" onClick={onClose} aria-hidden="true" />}
      <aside
        className={`fixed right-0 top-0 z-120 flex h-screen ${tab === "simulate" ? "w-[900px]" : "w-[520px]"} max-w-full flex-col overflow-hidden border-l border-line bg-[#F5F9FE] shadow-[-2px_0_8px_rgba(15,39,68,0.08)] transition-[transform,width] duration-[180ms] ease-[ease] max-[640px]:w-full ${
          open ? "translate-x-0" : "translate-x-full"
        }`}
        aria-hidden={!open}
        aria-label="Ask AI"
      >
        {header}
        <div className={`flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto p-4 ${tab === "ask" ? "" : "hidden"}`}>
          {messageList}
          {exampleChips}
        </div>
        <div className={`shrink-0 border-t border-[#e3edf7] bg-white/60 p-3 ${tab === "ask" ? "" : "hidden"}`}>{inputForm}</div>
        <div className={tab === "simulate" ? "min-h-0 flex-1 overflow-y-auto p-4" : "hidden"}>{simBody}</div>
      </aside>
    </>
  );
}
