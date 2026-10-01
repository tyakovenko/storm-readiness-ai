import { useEffect, useRef, useState } from "react";
import "./AskAI.css";

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
// Mock-only: the scripted client misbehaves once so the trust layer has something to block.
const TRUST_DEMOS = ["Trust demo: hallucinate a number", "Trust demo: overconfident outage risk"];

const STATUS = {
  passed: { label: "Trust checks passed", className: "badge ok" },
  regenerated: { label: "Regenerated after a trust block", className: "badge warn" },
  blocked: { label: "Blocked by trust layer", className: "badge bad" },
};

// LLMs emit **bold** even when told not to; render just that, no markdown library.
function AnswerText({ text }) {
  return text.split(/(\*\*[^*]+\*\*)/g).map((part, i) =>
    part.startsWith("**") && part.endsWith("**") ? <strong key={i}>{part.slice(2, -2)}</strong> : part,
  );
}

function CheckList({ checks }) {
  return (
    <ul className="checks">
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
    <div className="reply">
      <span className={status.className}>{status.label}</span>
      {result.answer ? (
        <p className="answer"><AnswerText text={result.answer} /></p>
      ) : (
        <p className="answer muted">This answer was blocked, so it is not shown. See the trust checks below.</p>
      )}

      {result.why.length > 0 && (
        <details>
          <summary>Why</summary>
          <ul>
            {result.why.map((w) => (
              <li key={w.county}>
                <strong>{w.county}:</strong> {w.reasons.join("; ")}
              </li>
            ))}
          </ul>
        </details>
      )}
      <details>
        <summary>Sources</summary>
        <ul>{result.sources.map((s) => <li key={s}>{s}</li>)}</ul>
      </details>
      <details>
        <summary>Trust checks</summary>
        <CheckList checks={result.checks} />
        {blockedDrafts.map((a, i) => (
          <div key={i} className="draft">
            <p><strong>Blocked draft (never shown to users):</strong></p>
            <CheckList checks={a.checks.filter((c) => c.passed === false)} />
            <p className="answer muted">{a.text}</p>
          </div>
        ))}
      </details>
      <details>
        <summary>Tool calls ({result.tool_calls.length})</summary>
        <ol>
          {result.tool_calls.map((t, i) => (
            <li key={i}><code>{t.name}({JSON.stringify(t.arguments)})</code></li>
          ))}
        </ol>
      </details>
    </div>
  );
}

export default function AskAI({ open, onClose }) {
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
      const r = await fetch("/api/chat", {
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

  const examples = health?.mock ? [...EXAMPLES, ...TRUST_DEMOS] : EXAMPLES;

  return (
    <>
      {open && <div className="ask-ai-backdrop" onClick={onClose} aria-hidden="true" />}
      <aside className={`ask-ai-panel${open ? " is-open" : ""}`} aria-hidden={!open} aria-label="Ask AI">
        <div className="ask-ai-panel__header">
          <div>
            <h2>Ask AI</h2>
            {health && (
              <div className="badges">
                <span className={health.mock ? "badge warn" : "badge ok"}>
                  {health.mock ? "Mock mode: scripted, no LLM" : `Model: ${health.model}`}
                </span>
                <span className="badge neutral">{health.judge ? `Judge: ${health.judge}` : "Judge: off"}</span>
              </div>
            )}
          </div>
          <button type="button" className="ask-ai-panel__close" onClick={onClose} aria-label="Close Ask AI">
            &times;
          </button>
        </div>

        <p className="banner" role="note">
          Demo data only. Every number comes from stub tools, not a real forecast.
        </p>

        <main className="chat" aria-live="polite">
          {messages.length === 0 && (
            <p className="muted">Ask about the storm's impact, the staging plan, or a what-if.</p>
          )}
          {messages.map((m, i) =>
            m.role === "user" ? (
              <div key={i} className="msg user">{m.content}</div>
            ) : (
              <div key={i} className="msg agent"><AgentReply result={m.result} /></div>
            ),
          )}
          {loading && <p className="muted">Agent is working…</p>}
          {error && <p className="error" role="alert">{error}</p>}
          <div ref={endRef} />
        </main>

        <div className="examples">
          {examples.map((q) => (
            <button key={q} type="button" onClick={() => send(q)} disabled={loading}>{q}</button>
          ))}
        </div>

        <form
          className="composer"
          onSubmit={(e) => {
            e.preventDefault();
            send(input);
          }}
        >
          <label htmlFor="question" className="sr-only">Ask the agent</label>
          <input
            id="question"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask a question, e.g. What if Shelter 4 is closed?"
            disabled={loading}
          />
          <button type="submit" disabled={loading || !input.trim()}>Send</button>
        </form>
      </aside>
    </>
  );
}
