import { useEffect, useRef, useState } from "react";
import { askAgent } from "../api.js";
import AgentReply from "../components/AgentReply.jsx";

// The original chat screen. All logic lives in the backend: this sends a
// question to POST /api/chat and displays what comes back.

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

export default function AskAI({ health }) {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const endRef = useRef(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

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
      const result = await askAgent(question, history);
      setMessages((prev) => [...prev, { role: "assistant", result }]);
    } catch (e) {
      setError(`The agent failed: ${e.message}. Check the backend terminal for details.`);
    } finally {
      setLoading(false);
    }
  }

  const examples = health?.mock ? [...EXAMPLES, ...TRUST_DEMOS] : EXAMPLES;

  return (
    <div className="mx-auto flex max-w-[820px] flex-col gap-3">
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
    </div>
  );
}
