import { useEffect, useMemo, useState } from "react";
import { PAGE, PageStatus, PageTitle } from "../components/Page.jsx";
import SectionHeading from "../components/SectionHeading.jsx";
import { fetchResearchRun, fetchResearchRuns } from "../api.js";
import { CARD, LABEL, NOTE, fmt } from "../dallas/format.js";

// Research drafts (read-only). A draft is what the research agent found for one county, with the judge's
// verdict on every fact. Nothing here is live: publishing is a reviewer step (python -m research.publish).
// No chat on this page by design (docs/decisions/20261005-research-offline-human-gate.md).

// Order = how much reviewer attention a fact needs; verified facts can be accepted at a glance.
const VERDICTS = [
  { id: "conflicting", label: "Conflicting", cls: "bg-bad-bg text-bad-text", note: "sources disagree on the value" },
  { id: "single_source", label: "Single source", cls: "bg-warn-bg text-warn-text", note: "one source; read it" },
  { id: "unchecked", label: "Unchecked", cls: "bg-canvas text-muted border border-line", note: "a check couldn't run" },
  { id: "verified", label: "Verified", cls: "bg-ok-bg text-ok-text", note: "2+ independent sources" },
  { id: "unsupported", label: "Unsupported", cls: "bg-bad-bg text-bad-text", note: "the source doesn't say this" },
];
const ORDER = Object.fromEntries(VERDICTS.map((v, i) => [v.id, i]));
const BY_ID = Object.fromEntries(VERDICTS.map((v) => [v.id, v]));
const TH = "px-3 py-2 text-left text-[0.72rem] font-semibold uppercase tracking-[0.4px] text-muted";
const TD = "px-3 py-2 align-top text-[0.82rem]";

function Badge({ verdict }) {
  const v = BY_ID[verdict] ?? { label: verdict ?? "not reviewed", cls: "bg-canvas text-muted border border-line" };
  return <span className={`whitespace-nowrap rounded px-2 py-[2px] text-[0.7rem] font-semibold ${v.cls}`}>{v.label}</span>;
}

function host(url) {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

export function ResearchRuns({ onOpen }) {
  const [runs, setRuns] = useState(null);
  const [error, setError] = useState("");
  useEffect(() => {
    fetchResearchRuns().then(setRuns).catch((e) => setError(`Can't list research runs (${e.message}).`));
  }, []);
  if (!runs && !error) return <PageStatus title="Research" />;
  return (
    <section className={PAGE}>
      <PageTitle>Research drafts</PageTitle>
      <p className="mb-5 max-w-[760px] text-[0.9rem] text-muted">
        The research agent reads public sources for a county and drafts facts; a stricter judge checks each one
        against its source and looks for an independent second source. Drafts are never live: a reviewer
        publishes the facts they accept.
      </p>
      {error && <p className="rounded bg-bad-bg px-3 py-2 text-[0.88rem] text-bad-text" role="alert">{error}</p>}
      {runs && runs.length === 0 && <p className={NOTE}>No research runs yet. Start one with <code>python -m research.run --fips &lt;fips&gt;</code>.</p>}
      <div className="grid grid-cols-3 gap-4 max-[1000px]:grid-cols-2 max-[640px]:grid-cols-1">
        {(runs ?? []).map((r) => (
          <button key={`${r.fips}/${r.run_id}`} type="button" disabled={Boolean(r.error)}
            onClick={() => onOpen(r.hazard ?? "hurricane", r.fips, r.run_id)}
            className={`${CARD} flex cursor-pointer flex-col gap-2 text-left hover:border-accent disabled:cursor-not-allowed`}>
            <div className="flex items-center justify-between gap-2">
              <span className={LABEL}>{r.hazard} • run {r.run_id}</span>
              <span className={`rounded px-2 py-[2px] text-[0.7rem] font-semibold ${
                r.error ? "bg-bad-bg text-bad-text" : r.partial ? "bg-warn-bg text-warn-text" : "bg-canvas text-muted"}`}>
                {r.error ? "unreadable" : r.partial ? "partial" : "draft"}
              </span>
            </div>
            <span className="text-[1.1rem] font-bold text-navy">{r.county ?? r.fips}{r.state ? `, ${r.state}` : ""}</span>
            {r.error ? <span className={NOTE}>{r.error}</span> : (
              <>
                <span className={NOTE}>{fmt(r.facts)} facts • {fmt(r.gaps)} gaps • {r.reviewed ? `judged by ${r.judge_model}` : "not judged yet"}</span>
                {r.reviewed > 0 && (
                  <div className="flex flex-wrap gap-1">
                    {VERDICTS.filter((v) => r.verdicts?.[v.id]).map((v) => (
                      <span key={v.id} className={`rounded px-2 py-[2px] text-[0.7rem] font-semibold ${v.cls}`}>
                        {fmt(r.verdicts[v.id])} {v.label.toLowerCase()}
                      </span>
                    ))}
                  </div>
                )}
              </>
            )}
          </button>
        ))}
      </div>
    </section>
  );
}

export function ResearchRun({ hazard, fips, runId }) {
  const [draft, setDraft] = useState(null);
  const [error, setError] = useState("");
  const [show, setShow] = useState(() => new Set(VERDICTS.map((v) => v.id).concat("none")));
  const [open, setOpen] = useState(null);
  useEffect(() => {
    fetchResearchRun(hazard, fips, runId).then(setDraft).catch((e) => setError(`Can't load this draft (${e.message}).`));
  }, [hazard, fips, runId]);

  const rows = useMemo(() => {
    if (!draft) return [];
    const reviews = Object.fromEntries((draft.reviews ?? []).map((r) => [r.fact_id, r]));
    return draft.facts
      .map((f) => ({ fact: f, review: reviews[f.id] ?? null }))
      .sort((a, b) => (ORDER[a.review?.verdict] ?? 99) - (ORDER[b.review?.verdict] ?? 99));
  }, [draft]);

  if (error) return <PageStatus title="Research draft" error={error} />;
  if (!draft) return <PageStatus title="Research draft" />;
  const { target, run_log: log = {} } = draft;
  const storms = Object.fromEntries((target.storms ?? []).map((s) => [s.id, `${s.name} ${s.year}`]));
  const counts = rows.reduce((m, r) => ({ ...m, [r.review?.verdict ?? "none"]: (m[r.review?.verdict ?? "none"] ?? 0) + 1 }), {});
  const visible = rows.filter((r) => show.has(r.review?.verdict ?? "none"));
  const toggle = (id) => setShow((s) => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n; });

  return (
    <section className={PAGE}>
      <PageTitle>{target.county}, {target.state}: research draft</PageTitle>
      <p className="mb-3 rounded bg-warn-bg px-3 py-2 text-[0.85rem] text-warn-text">
        Draft, not published. The county agent doesn't use these facts until a reviewer publishes them.
      </p>
      {log.cap_hit && (
        <p className="mb-3 rounded bg-bad-bg px-3 py-2 text-[0.85rem] text-bad-text" role="alert">
          Partial run: stopped at the {log.time_cap_hit ? `time cap (${fmt(log.time_cap_s)} s)` : `model-call cap (${fmt(log.model_call_cap)})`}.
          Items not reached are missing, not absent.
        </p>
      )}
      <p className={`${NOTE} mb-4`}>
        Run {draft.run_id} • researcher {draft.researcher_model} • judge {draft.judge_model ?? "not run"} •
        {" "}{fmt(log.model_calls)} researcher calls, {fmt(log.judge_model_calls)} judge calls • {fmt(log.fetches)} pages read
        ({fmt(Object.keys(log.fetch_errors ?? {}).length)} unreadable) • {fmt((log.rejected_submissions ?? []).length)} submissions
        refused by fixed checks • {fmt(log.seconds)} s
      </p>

      <div className="mb-3 flex flex-wrap gap-2">
        {VERDICTS.concat([{ id: "none", label: "Not reviewed", cls: "bg-canvas text-muted border border-line" }])
          .filter((v) => counts[v.id]).map((v) => (
            <button key={v.id} type="button" onClick={() => toggle(v.id)} title={v.note}
              className={`rounded px-2 py-1 text-[0.75rem] font-semibold ${v.cls} ${show.has(v.id) ? "" : "opacity-40"}`}>
              {fmt(counts[v.id])} {v.label}
            </button>
          ))}
      </div>

      <div className={`${CARD} overflow-x-auto p-0`}>
        <table className="w-full border-collapse">
          <thead>
            <tr className="border-b border-line">
              <th className={TH}>Verdict</th><th className={TH}>Metric</th><th className={TH}>Value</th>
              <th className={TH}>Place / storm</th><th className={TH}>Source</th><th className={TH}>Why</th>
            </tr>
          </thead>
          <tbody>
            {visible.map(({ fact: f, review: r }) => {
              const failed = (r?.checks ?? []).filter((c) => c.ok === false);
              const why = failed[0]?.detail ?? r?.checks?.at(-1)?.detail ?? r?.notes ?? "";
              return [
                <tr key={f.id} className="cursor-pointer border-b border-line hover:bg-canvas" onClick={() => setOpen(open === f.id ? null : f.id)}>
                  <td className={TD}><Badge verdict={r?.verdict} />{r?.notes && <div className={NOTE}>{r.notes}</div>}</td>
                  <td className={TD}>{f.metric.replaceAll("_", " ")}</td>
                  <td className={`${TD} whitespace-nowrap font-semibold text-navy`}>
                    {f.value == null ? "—" : `${f.qualifier === "exact" ? "" : `${f.qualifier.replace("_", " ")} `}${f.value_raw}`}
                    <span className="font-normal text-muted"> {f.unit}</span>
                  </td>
                  <td className={TD}>{f.place ?? target.county}{f.storm_id ? ` • ${storms[f.storm_id] ?? f.storm_id}` : ""}{f.as_of ? ` • as of ${f.as_of}` : ""}</td>
                  <td className={TD}>
                    <a href={f.source_url} target="_blank" rel="noreferrer" className="text-accent underline" onClick={(e) => e.stopPropagation()}>
                      {host(f.source_url)}
                    </a>
                    {(r?.corroborating_urls ?? []).map((u) => (
                      <div key={u}><a href={u} target="_blank" rel="noreferrer" className="text-[0.75rem] text-accent underline"
                        onClick={(e) => e.stopPropagation()}>+ {host(u)}</a></div>
                    ))}
                  </td>
                  <td className={`${TD} max-w-[360px] text-muted`}>{why}</td>
                </tr>,
                open === f.id && (
                  <tr key={`${f.id}-detail`} className="border-b border-line bg-canvas">
                    <td colSpan={6} className="px-4 py-3 text-[0.8rem]">
                      <div className="mb-2"><span className={LABEL}>Quote</span><blockquote className="mt-1 border-l-2 border-accent pl-3">{f.quote}</blockquote></div>
                      <div className="mb-1"><span className={LABEL}>Source</span> {f.source}{f.publisher ? ` • ${f.publisher}` : ""}{f.published ? ` • ${f.published}` : ""} • retrieved {f.retrieved}</div>
                      <span className={LABEL}>Checks</span>
                      <ul className="mt-1 list-none p-0">
                        {(r?.checks ?? []).map((c, i) => (
                          <li key={i} className={c.ok === false ? "text-bad-text" : c.ok ? "text-ok-text" : "text-muted"}>
                            {c.ok === false ? "✗" : c.ok ? "✓" : "–"} {c.layer} / {c.name}: {c.detail}{c.severity === "flag" ? " (flag)" : ""}
                          </li>
                        ))}
                      </ul>
                    </td>
                  </tr>
                ),
              ];
            })}
          </tbody>
        </table>
        {visible.length === 0 && <p className={`${NOTE} px-3 py-3`}>No facts match the selected verdicts.</p>}
      </div>

      <div className="mb-2 mt-6">
        <SectionHeading title="Gaps" subtitle="What the researcher looked for and couldn't source, and where it looked." />
      </div>
      {draft.gaps.length === 0 ? <p className={NOTE}>The researcher reported no gaps.</p> : (
        <ul className="list-disc pl-5 text-[0.85rem]">
          {draft.gaps.map((g, i) => <li key={i}><span className="font-semibold">{g.metric.replaceAll("_", " ")}</span>: {g.reason}</li>)}
        </ul>
      )}
      <p className={`${NOTE} mt-4`}>
        To publish: <code>python -m research.publish --fips {target.fips} --run {draft.run_id} --reviewer "&lt;name&gt;" --accept verified,single_source</code>
      </p>
    </section>
  );
}
