// One agent answer with its trust badge and Why / Sources / Trust checks / Tool calls panels.
// Used by the Ask AI chat and the Resource Planner's per-recommendation explanations.

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

export default function AgentReply({ result }) {
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
