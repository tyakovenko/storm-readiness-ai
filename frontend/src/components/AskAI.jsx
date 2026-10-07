import { useEffect, useRef, useState } from "react";
import { chatUrl } from "../api.js";

// All agent/trust logic lives in the backend. This panel only sends a
// question to POST /api/chat and displays what comes back. Moved out of
// App.jsx unchanged so the existing chat behavior keeps working as-is.

const EXAMPLES = [
  "What's the outage risk by county?",
  "Where should we stage trucks?",
  "We only have 6 trucks and Shelter 2 is closed. Re-plan.",
  "Were there similar storms before?",
  "What should residents do now?",
  "How does El Niño affect this season?",
];
const DALLAS_EXAMPLES = [
  "How should we prepare for this storm?",
  "What if we only have 30 trucks and Fair Park is closed?",
  "Has Dallas had a storm like this before?",
  "What happened during Winter Storm Uri?",
  "Does El Niño matter this winter?",
  "What should residents do if the power goes out?",
];
// Mock-only: the scripted client misbehaves once so the trust layer has something to block.
const TRUST_DEMOS = ["Trust demo: hallucinate a number", "Trust demo: overconfident outage risk"];
const DALLAS_TRUST_DEMOS = ["Trust demo: shelter demand without its range"];
const HURRICANE_EXAMPLES = [
  "How bad could the power outages be?",
  "Has this county had a storm like this before?",
  "What shelters do we have outside the surge zone?",
  "What if we include surge-zone shelters too?",
  "Does El Niño matter this season?",
  "What should residents do to evacuate?",
];
const HURRICANE_TRUST_DEMOS = ["Trust demo: outage estimate without its range"];
// Shown on the home page before any scenario is open. Phase 5: this used to silently fall back
// to the Dallas winter-storm banner/examples, which misrepresented what "Ask AI" would actually
// answer with for an unrelated hurricane question -- see backend/agent/landing_router.py.
const NONE_EXAMPLES = [
  "Which scenarios are available?",
  "Tell me about the Dallas winter storm scenario",
  "Tell me about Hurricane Beryl in Harris County",
  "Which areas are highest risk?",
];
const BANNER = {
  winter: "Past-storm numbers are real (NOAA, Dallas 311, EAGLE-I, FEMA, city records). The storm is a planning scenario, not a forecast; estimates are ranges from past storms.",
  hurricane: "Past-storm numbers are real (HURDAT2, EAGLE-I outages, NOAA, FEMA). The storm is a replay of a real past NHC forecast; outage ranges come from a trained model with its tested error shown.",
  stub: "Demo data only. Every number comes from stub tools, not a real forecast.",
  none: "No storm or county is selected yet. Name one (e.g. \"Dallas\" or \"Hurricane Beryl in Harris County\") or open it from the home page to get an area-specific answer.",
};

const BADGE = "inline-block rounded-full px-2.5 py-[3px] text-xs font-semibold";
const BADGE_OK = `${BADGE} bg-ok-bg text-ok-text`;
const BADGE_WARN = `${BADGE} bg-warn-bg text-warn-text`;
const BADGE_BAD = `${BADGE} bg-bad-bg text-bad-text`;
const BADGE_NEUTRAL = `${BADGE} bg-[#e8ecf1] text-[#3b4452]`;

const STATUS = {
  passed: { label: "Trust checks passed", className: BADGE_OK },
  regenerated: { label: "Regenerated after a trust block", className: BADGE_WARN },
  blocked: { label: "Blocked by trust layer", className: BADGE_BAD },
};

// The expandable Why / Sources / Trust checks / Tool calls sections under each answer.
const DETAILS = "border-t border-line py-1.5 text-[0.85rem]";
const SUMMARY = "cursor-pointer font-semibold text-accent";
const ANSWER = "my-2 whitespace-pre-wrap leading-normal";

// LLMs emit **bold** even when told not to; render just that, no markdown library.
function AnswerText({ text }) {
  return text.split(/(\*\*[^*]+\*\*)/g).map((part, i) =>
    part.startsWith("**") && part.endsWith("**") ? <strong key={i}>{part.slice(2, -2)}</strong> : part,
  );
}

function CheckList({ checks }) {
  return (
    <ul className="my-1.5">
      {checks.map((c) => (
        <li key={c.name}>
          <span aria-hidden="true">{c.passed === true ? "✔" : c.passed === false ? "✖" : "…"}</span>{" "}
          <strong>{c.name}</strong>: {c.detail}
        </li>
      ))}
    </ul>
  );
}

function AgentReply({ result }) {
  const status = STATUS[result.status];
  const blockedDrafts = result.attempts.filter((a) => a.checks.some((c) => c.passed === false));
  return (
    <div>
      <span className={status.className}>{status.label}</span>
      {result.answer ? (
        <p className={ANSWER}><AnswerText text={result.answer} /></p>
      ) : (
        <p className={`${ANSWER} text-muted`}>This answer was blocked, so it is not shown. See the trust checks below.</p>
      )}

      {result.why.length > 0 && (
        <details className={DETAILS}>
          <summary className={SUMMARY}>Why</summary>
          <ul className="my-1.5 list-disc pl-5">
            {result.why.map((w) => (
              <li key={w.county}>
                <strong>{w.county}:</strong> {w.reasons.join("; ")}
              </li>
            ))}
          </ul>
        </details>
      )}
      <details className={DETAILS}>
        <summary className={SUMMARY}>Sources</summary>
        <ul className="my-1.5 list-disc pl-5">{result.sources.map((s) => <li key={s}>{s}</li>)}</ul>
      </details>
      <details className={DETAILS}>
        <summary className={SUMMARY}>Trust checks</summary>
        <CheckList checks={result.checks} />
        {blockedDrafts.map((a, i) => (
          <div key={i} className="mt-2 rounded bg-bad-bg p-2">
            <p><strong>Blocked draft (never shown to users):</strong></p>
            <CheckList checks={a.checks.filter((c) => c.passed === false)} />
            <p className={`${ANSWER} text-muted`}>{a.text}</p>
          </div>
        ))}
      </details>
      <details className={DETAILS}>
        <summary className={SUMMARY}>Tool calls ({result.tool_calls.length})</summary>
        <ol className="my-1.5 list-decimal pl-5">
          {result.tool_calls.map((t, i) => (
            <li key={i}><code className="text-[0.8rem] [overflow-wrap:anywhere]">{t.name}({JSON.stringify(t.arguments)})</code></li>
          ))}
        </ol>
      </details>
    </div>
  );
}

// agentId/hazard/agentName come from the multi-agent app; the single-agent app passes none.
// pendingQuestion/onPendingSent let the storm home page's search box hand off a question to this
// same panel instead of a second chat implementation.
export default function AskAI({ open, onClose, agentId = null, hazard = null, agentName = null, disabled = false,
  pendingQuestion = "", onPendingSent }) {
  const [health, setHealth] = useState(null);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const endRef = useRef(null);

  useEffect(() => {
    fetch("/api/health")
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then(setHealth)
      .catch(() => setError("Can't reach the backend. Is it running on port 8001?"));
  }, []);

  useEffect(() => {
    if (!open) return;
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading, open]);

  useEffect(() => {
    if (!open) return;
    function onKeyDown(e) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open, onClose]);

  useEffect(() => {
    if (open && pendingQuestion) {
      send(pendingQuestion);
      onPendingSent?.();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, pendingQuestion]);

  async function send(text) {
    const question = text.trim();
    if (!question || loading) return;
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
    } catch (e) {
      setError(`The agent failed: ${e.message}. Check the backend terminal for details.`);
    } finally {
      setLoading(false);
    }
  }

  // Which template answers: the open agent's hazard (multi), else the single service's domain.
  // Phase 5: on the multi-agent home page with no agent open yet, hazard is passed as null and
  // health.domain is "multi" -- that's "none", not a silent fallback to Dallas's "winter".
  const kind = hazard ?? (health?.domain === "multi" ? "none" : health?.domain === "dallas" ? "winter" : "stub");
  const base = { winter: DALLAS_EXAMPLES, hurricane: HURRICANE_EXAMPLES, none: NONE_EXAMPLES }[kind] ?? EXAMPLES;
  const demos = { winter: DALLAS_TRUST_DEMOS, hurricane: HURRICANE_TRUST_DEMOS, none: [] }[kind] ?? TRUST_DEMOS;
  const examples = disabled ? [] : health?.mock ? [...base, ...demos] : base;

  return (
    <>
      {/* Backdrop and panel sit above the fixed header (z 100) and sub-nav (z 90). */}
      {open && <div className="fixed inset-0 z-110 bg-[rgba(15,39,68,0.15)]" onClick={onClose} aria-hidden="true" />}
      <aside
        className={`fixed right-0 top-0 z-120 flex h-screen w-[420px] max-w-full flex-col gap-3 overflow-y-auto border-l border-line bg-surface p-4 shadow-[-2px_0_8px_rgba(15,39,68,0.08)] transition-transform duration-[180ms] ease-[ease] max-[640px]:w-full ${
          open ? "translate-x-0" : "translate-x-full"
        }`}
        aria-hidden={!open}
        aria-label="Ask AI"
      >
        <div className="flex items-start justify-between gap-3">
          <div>
            <h2 className="mb-1.5 text-[1.05rem] font-bold text-ink">Ask AI{agentName ? ` — ${agentName}` : ""}</h2>
            {health && (
              <div className="mt-1 flex flex-wrap gap-1.5">
                <span className={health.mock ? BADGE_WARN : BADGE_OK}>
                  {health.mock ? "Mock mode: scripted, no LLM" : `Model: ${health.model}`}
                </span>
                <span className={BADGE_NEUTRAL}>{health.judge ? `Judge: ${health.judge}` : "Judge: off"}</span>
              </div>
            )}
          </div>
          <button type="button" className="size-7 shrink-0 cursor-pointer rounded border border-line bg-transparent text-base leading-none text-muted hover:border-muted hover:text-ink" onClick={onClose} aria-label="Close Ask AI">
            &times;
          </button>
        </div>

        <p className="rounded bg-warn-bg px-3 py-2 text-[0.85rem] text-warn-text" role="note">
          {disabled ? "Open a county agent to ask questions about it." : BANNER[kind]}
        </p>

        <div className="flex min-h-[120px] flex-1 flex-col gap-3 overflow-y-auto" aria-live="polite">
          {messages.length === 0 && (
            <p className="text-muted">Ask about the storm's impact, the staging plan, or a what-if.</p>
          )}
          {messages.map((m, i) =>
            m.role === "user" ? (
              <div key={i} className="max-w-[85%] self-end rounded-md bg-accent px-3.5 py-3 text-white">{m.content}</div>
            ) : (
              <div key={i} className="rounded-md border border-line bg-canvas px-3.5 py-3"><AgentReply result={m.result} /></div>
            ),
          )}
          {loading && <p className="text-muted">Agent is working…</p>}
          {error && <p className="rounded bg-bad-bg px-3 py-2 text-bad-text" role="alert">{error}</p>}
          <div ref={endRef} />
        </div>

        <div className="flex flex-wrap gap-1.5">
          {examples.map((q) => (
            <button
              key={q}
              type="button"
              onClick={() => send(q)}
              disabled={loading}
              className="cursor-pointer rounded-full border border-line bg-surface px-3 py-1.5 text-[0.8rem] text-accent"
            >
              {q}
            </button>
          ))}
        </div>

        <form
          className="flex gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            send(input);
          }}
        >
          <label htmlFor="question" className="sr-only">Ask the agent</label>
          <input
            id="question"
            className="min-w-0 flex-1 rounded border border-line px-3 py-2.5 text-[0.95rem]"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask a question, e.g. What if Shelter 4 is closed?"
            disabled={loading}
          />
          <button
            type="submit"
            disabled={loading || !input.trim()}
            className="cursor-pointer rounded bg-accent px-4 py-2.5 font-semibold text-white"
          >
            Send
          </button>
        </form>
      </aside>
    </>
  );
}
