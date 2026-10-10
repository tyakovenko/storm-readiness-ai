// Ask AI -> Simulate ("Learn how to get prepared"): a response-team hurricane exercise.
// Pick a role, a US county and a storm (live or hypothetical), then walk the timeline from 3 days out
// through recovery. Numbers come from backend/hurricane/simulator.py (real data + the trained model).
import { useEffect, useRef, useState } from "react";
import { fetchLiveStorms, fetchSimulateSetup, runSimulation, searchSimulateCounties } from "../../api.js";
import RiskBadge from "../RiskBadge.jsx";
import { getRiskLevel } from "../../utils/riskTier.js";

const n = (v) => (v == null ? "—" : Math.round(Number(v)).toLocaleString("en-US"));
const CARD = "rounded-2xl border border-[#DCE7F2] bg-white p-4 shadow-sm";
const LABEL = "text-[0.68rem] font-bold uppercase tracking-wide text-[#607d98]";
const PILL = (on) => `cursor-pointer rounded-full border px-3 py-1.5 text-[0.8rem] font-semibold transition ${
  on ? "border-[#2470d6] bg-[#2470d6] text-white shadow-xs" : "border-[#D5E4F4] bg-white text-[#31516e] hover:border-[#9cc3f2]"}`;
const SHORT = { t72: "3 days out", t48: "2 days out", t36: "36 h out", t12: "12 h out", t0: "Landfall", t24p: "Day after", t72p: "Recovery" };

function CountyPicker({ value, onChange }) {
  const [q, setQ] = useState(value ? `${value.name}, ${value.state}` : "");
  const [hits, setHits] = useState([]);
  const [open, setOpen] = useState(false);
  const timer = useRef();
  useEffect(() => {
    clearTimeout(timer.current);
    if (q.trim().length < 2 || (value && q === `${value.name}, ${value.state}`)) { setHits([]); return; }
    timer.current = setTimeout(() => searchSimulateCounties(q).then(setHits).catch(() => setHits([])), 250);
    return () => clearTimeout(timer.current);
  }, [q, value]);
  return (
    <div className="relative">
      <input
        className="w-full rounded-xl border border-[#D5E4F4] bg-white px-3 py-2 text-[0.9rem] outline-none focus:border-[#9cc3f2]"
        placeholder="Search a US county, e.g. Miami-Dade or Harris, TX"
        value={q}
        onChange={(e) => { setQ(e.target.value); setOpen(true); onChange(null); }}
        onFocus={() => setOpen(true)}
        aria-label="County"
      />
      {open && hits.length > 0 && (
        <ul className="absolute inset-x-0 top-full z-10 mt-1 max-h-60 overflow-y-auto rounded-xl border border-[#D5E4F4] bg-white py-1 shadow-lg" role="listbox">
          {hits.map((h) => (
            <li key={h.fips}>
              <button type="button" role="option" aria-selected={false}
                className="flex w-full justify-between gap-3 px-3 py-1.5 text-left text-[0.85rem] hover:bg-[#EEF5FF]"
                onClick={() => { onChange(h); setQ(`${h.name}, ${h.state}`); setOpen(false); }}>
                <span>{h.name}, {h.state}</span>
                <span className="text-[#8495a7]">{h.population ? `${n(h.population)} people` : ""}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function Setup({ setup, form, setForm, liveStorms, onStart, busy, error }) {
  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }));
  const canStart = form.role && form.county && (form.mode === "hypothetical" || form.storm_id);
  return (
    <div className="flex flex-col gap-4">
      <div className={CARD}>
        <p className={LABEL}>1 · Your team</p>
        <div className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-2">
          {setup.roles.map((r) => (
            <button key={r.id} type="button" onClick={() => set("role", r.id)} aria-pressed={form.role === r.id}
              className={`rounded-xl border px-3 py-2 text-left transition ${form.role === r.id
                ? "border-[#2470d6] bg-[#EEF5FF] ring-1 ring-[#2470d6]" : "border-[#D5E4F4] bg-white hover:border-[#9cc3f2]"}`}>
              <span className="block text-[0.88rem] font-semibold text-[#112f4d]">{r.label}</span>
              <span className="block text-[0.74rem] text-[#607d98]">{r.blurb}</span>
            </button>
          ))}
        </div>
      </div>

      <div className={CARD}>
        <p className={LABEL}>2 · Your county</p>
        <div className="mt-2"><CountyPicker value={form.county} onChange={(c) => set("county", c)} /></div>
        <p className="mt-1.5 text-[0.72rem] text-[#8495a7]">{setup.coverage}</p>
      </div>

      <div className={CARD}>
        <p className={LABEL}>3 · The storm</p>
        <div className="mt-2 flex flex-wrap gap-1.5">
          <button type="button" className={PILL(form.mode === "hypothetical")} onClick={() => set("mode", "hypothetical")}>Hypothetical hurricane</button>
          <button type="button" className={PILL(form.mode === "live")} onClick={() => set("mode", "live")} disabled={!liveStorms?.length}>
            Live storm{liveStorms ? ` (${liveStorms.length})` : ""}
          </button>
        </div>
        {form.mode === "live" ? (
          <div className="mt-3 flex flex-wrap gap-1.5">
            {(liveStorms ?? []).map((s) => (
              <button key={s.storm_id} type="button" className={PILL(form.storm_id === s.storm_id)} onClick={() => set("storm_id", s.storm_id)}>
                {s.name} · {Math.round(s.intensity_kt)} kt
              </button>
            ))}
            <p className="w-full text-[0.72rem] text-[#8495a7]">Uses NHC&apos;s official forecast; phases are timed from the storm&apos;s closest approach to your county.</p>
          </div>
        ) : (
          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            <div className="sm:col-span-2">
              <span className="text-[0.75rem] font-semibold text-[#31516e]">Strength</span>
              <div className="mt-1 flex flex-wrap gap-1.5">
                {setup.categories.map((c) => (
                  <button key={c.id} type="button" className={PILL(form.category === c.id)} onClick={() => set("category", c.id)}>{c.label}</button>
                ))}
              </div>
            </div>
            <label className="text-[0.75rem] font-semibold text-[#31516e]">Approach
              <select className="mt-1 w-full rounded-xl border border-[#D5E4F4] bg-white px-2 py-1.5 text-[0.85rem] font-normal" value={form.approach} onChange={(e) => set("approach", e.target.value)}>
                {setup.approaches.map((a) => <option key={a.id} value={a.id}>{a.label}</option>)}
              </select>
            </label>
            <label className="text-[0.75rem] font-semibold text-[#31516e]">Start the exercise
              <select className="mt-1 w-full rounded-xl border border-[#D5E4F4] bg-white px-2 py-1.5 text-[0.85rem] font-normal" value={form.hours_to_landfall} onChange={(e) => set("hours_to_landfall", Number(e.target.value))}>
                {setup.lead_times_h.map((h) => <option key={h} value={h}>{h} hours before landfall</option>)}
              </select>
            </label>
            <label className="text-[0.75rem] font-semibold text-[#31516e] sm:col-span-2">Track
              <select className="mt-1 w-full rounded-xl border border-[#D5E4F4] bg-white px-2 py-1.5 text-[0.85rem] font-normal" value={form.offset} onChange={(e) => set("offset", e.target.value)}>
                {setup.offsets.map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}
              </select>
            </label>
          </div>
        )}
      </div>

      {error && <p className="rounded-xl bg-bad-bg px-3 py-2 text-[0.85rem] text-bad-text" role="alert">{error}</p>}
      <button type="button" disabled={!canStart || busy} onClick={onStart}
        className="rounded-full bg-gradient-to-br from-[#3b8cf0] to-[#2470d6] px-5 py-2.5 text-[0.95rem] font-semibold text-white shadow-[0_4px_12px_rgba(40,120,232,0.25)] transition hover:brightness-110 disabled:cursor-default disabled:opacity-50">
        {busy ? "Building your exercise… (the first run can take up to a minute)" : "Start the exercise"}
      </button>
    </div>
  );
}

function Decision({ decision, picked, onPick }) {
  return (
    <div className="rounded-2xl border border-[#c9defa] bg-[#f3f8ff] p-4">
      <p className={LABEL}>Decision drill</p>
      <p className="mt-1 font-semibold text-[#112f4d]">{decision.question}</p>
      <div className="mt-2 flex flex-col gap-1.5">
        {decision.options.map((o, i) => {
          const chosen = picked === i;
          const tone = picked == null ? "border-[#D5E4F4] bg-white hover:border-[#9cc3f2]"
            : o.correct ? "border-[#2e7d5b] bg-[#e7f6ee]" : chosen ? "border-[#c62828] bg-[#fdecec]" : "border-[#e3edf7] bg-white opacity-70";
          return (
            <button key={i} type="button" disabled={picked != null} onClick={() => onPick(i)}
              className={`rounded-xl border px-3 py-2 text-left text-[0.85rem] transition ${tone}`}>
              {o.text}
              {picked != null && (chosen || o.correct) && <span className="mt-1 block text-[0.78rem] text-[#31516e]">{o.correct ? "✓ " : "✗ "}{o.feedback}</span>}
            </button>
          );
        })}
      </div>
    </div>
  );
}

function Run({ sim, progress, setProgress, onRestart }) {
  const { idx, picks, done } = progress;
  const setIdx = (i) => setProgress((p) => ({ ...p, idx: i }));
  const setPicks = (f) => setProgress((p) => ({ ...p, picks: f(p.picks) }));
  const setDone = (f) => setProgress((p) => ({ ...p, done: f(p.done) }));
  const [copied, setCopied] = useState(false);
  const ph = sim.phases[idx];
  const im = sim.impact;
  const answered = Object.keys(picks).length;
  const right = Object.entries(picks).filter(([k, i]) => sim.phases.find((p) => p.key === k).decision.options[i].correct).length;
  const s = ph.situation;

  return (
    <div className="flex flex-col gap-4">
      <div className={CARD}>
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div>
            <p className={LABEL}>{sim.role.label} exercise</p>
            <h3 className="text-[1.05rem] font-bold text-[#112f4d]">{sim.storm.label} · {sim.county.name}, {sim.county.state}</h3>
            <p className="text-[0.78rem] text-[#607d98]">
              {sim.storm.kind === "hypothetical" ? `${sim.storm.approach} · ${sim.storm.track}` : `Closest approach ${sim.storm.closest_approach_nm} nm`}
              {sim.county.population ? ` · ${n(sim.county.population)} residents` : ""}
              {sim.county.high_social_vulnerability ? " · high social vulnerability" : ""}
            </p>
          </div>
          <button type="button" onClick={onRestart} className="text-[0.8rem] font-semibold text-accent hover:underline">New exercise</button>
        </div>
        {im ? (
          <div className="mt-3 grid gap-3 sm:grid-cols-3">
            <div><p className={LABEL}>Predicted outages</p><p className="text-lg font-extrabold text-[#112f4d]">~{n(im.customers_out.median)}</p>
              <p className="text-[0.72rem] text-[#607d98]">range {n(im.customers_out.low)}–{n(im.customers_out.high)} customers</p></div>
            <div><p className={LABEL}>Risk</p><div className="mt-1"><RiskBadge level={getRiskLevel(im.risk_tier)} /></div>
              <p className="mt-1 text-[0.72rem] text-[#607d98]">{Number(im.pct_customers_out.median).toFixed(1)}% of {n(im.customers_served)}</p></div>
            <div><p className={LABEL}>Utility trucks</p><p className="text-lg font-extrabold text-[#112f4d]">{n(im.trucks_needed.median)}</p>
              <p className="text-[0.72rem] text-[#607d98]">range {n(im.trucks_needed.low)}–{n(im.trucks_needed.high)} (planning estimate)</p></div>
          </div>
        ) : <p className="mt-2 text-[0.8rem] text-[#607d98]">No model estimate for this county (missing source data).</p>}
        {sim.region.length > 0 && (
          <p className="mt-3 text-[0.75rem] text-[#4f6981]"><span className="font-semibold">Neighbors:</span>{" "}
            {sim.region.slice(0, 5).map((c) => `${c.name}, ${c.state} ~${n(c.customers_out.median)} out`).join(" · ")}</p>
        )}
        <p className="mt-1 text-[0.75rem] text-[#4f6981]">
          <span className="font-semibold">Live NWS alerts in {sim.alerts.state}:</span> {sim.alerts.count}
          {sim.alerts.items[0] ? ` (e.g. ${sim.alerts.items[0].event})` : ""}
        </p>
      </div>

      <nav className="flex gap-1 overflow-x-auto pb-1" aria-label="Exercise phases">
        {sim.phases.map((p, i) => (
          <button key={p.key} type="button" onClick={() => setIdx(i)} aria-current={i === idx ? "step" : undefined}
            className={`shrink-0 rounded-full border px-3 py-1 text-[0.75rem] font-semibold transition ${i === idx
              ? "border-[#2470d6] bg-[#2470d6] text-white" : picks[p.key] != null ? "border-[#9cc3f2] bg-[#EEF5FF] text-[#2470d6]" : "border-[#D5E4F4] bg-white text-[#4f6981]"}`}>
            {SHORT[p.key] ?? p.title}{p.status === "now" ? " · now" : ""}
          </button>
        ))}
      </nav>

      <div className={CARD}>
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h3 className="text-[1.05rem] font-bold text-[#112f4d]">{ph.title}</h3>
          {ph.when && <span className="text-[0.75rem] text-[#607d98]">{ph.when}{ph.status === "past" ? " (passed)" : ""}</span>}
        </div>
        <p className="mt-1 text-[0.85rem] text-[#4f6981]">{ph.stage}</p>
        {s && (
          <p className="mt-2 rounded-xl bg-[#f3f8ff] px-3 py-2 text-[0.82rem] text-[#31516e]">
            Storm center <strong>{n(s.distance_nm)} nm</strong> from {sim.county.name} · {s.storm_label} ({n(s.storm_wind_kt)} kt)
            {s.ts_winds_at_county != null && <> · tropical-storm winds {s.ts_winds_at_county ? <strong>reaching the county</strong> : "not yet at the county"}</>}
          </p>
        )}

        <div className="mt-4 grid gap-4 lg:grid-cols-2">
          <section>
            <p className={LABEL}>Your team&apos;s actions</p>
            <ul className="mt-1.5 space-y-1.5">
              {ph.actions.map((a) => {
                const k = `${ph.key}:${a}`;
                return (
                  <li key={a}>
                    <label className="flex cursor-pointer gap-2 text-[0.86rem] text-ink">
                      <input type="checkbox" className="mt-0.5 accent-[#2470d6]" checked={!!done[k]} onChange={() => setDone((d) => ({ ...d, [k]: !d[k] }))} />
                      <span className={done[k] ? "text-[#8495a7] line-through" : ""}>{a}</span>
                    </label>
                  </li>
                );
              })}
            </ul>
            {ph.resources.length > 0 && (
              <>
                <p className={`${LABEL} mt-4`}>Resources you have</p>
                <ul className="mt-1.5 list-disc space-y-1 pl-5 text-[0.82rem] text-[#31516e]">{ph.resources.map((r) => <li key={r}>{r}</li>)}</ul>
              </>
            )}
          </section>
          <section className="flex flex-col gap-4">
            <div>
              <p className={LABEL}>Tell the community</p>
              <blockquote className="mt-1.5 rounded-xl border-l-4 border-[#2470d6] bg-[#f3f8ff] px-3 py-2 text-[0.86rem] text-[#112f4d]">{ph.community_message}</blockquote>
              <button type="button" className="mt-1 text-[0.75rem] font-semibold text-accent hover:underline"
                onClick={() => { navigator.clipboard?.writeText(ph.community_message); setCopied(true); setTimeout(() => setCopied(false), 1500); }}>
                {copied ? "Copied" : "Copy message"}
              </button>
            </div>
            <div>
              <p className={LABEL}>Stay safe</p>
              <ul className="mt-1.5 list-disc space-y-1 pl-5 text-[0.82rem] text-[#31516e]">{ph.cautions.map((c) => <li key={c}>{c}</li>)}</ul>
            </div>
          </section>
        </div>

        <div className="mt-4">
          <Decision decision={ph.decision} picked={picks[ph.key]} onPick={(i) => setPicks((p) => ({ ...p, [ph.key]: i }))} />
        </div>

        <p className="mt-3 text-[0.72rem] text-[#8495a7]">
          Learn more: {ph.sources.map((src, i) => (
            <span key={src.url}>{i > 0 && " · "}<a href={src.url} target="_blank" rel="noreferrer" className="text-accent hover:underline">{src.label}</a></span>
          ))}
        </p>

        <div className="mt-4 flex items-center justify-between">
          <button type="button" disabled={idx === 0} onClick={() => setIdx(idx - 1)} className="rounded-full border border-[#D5E4F4] px-4 py-1.5 text-[0.85rem] font-semibold text-[#31516e] disabled:opacity-40">← Back</button>
          <span className="text-[0.75rem] text-[#607d98]">Drills: {right} of {answered} right · {sim.phases.length - answered} to go</span>
          <button type="button" disabled={idx === sim.phases.length - 1} onClick={() => setIdx(idx + 1)} className="rounded-full bg-[#2470d6] px-4 py-1.5 text-[0.85rem] font-semibold text-white disabled:opacity-40">Next →</button>
        </div>
      </div>

      <p className="text-[0.7rem] text-[#8495a7]">
        Outage figures: trained outage model on {sim.storm.kind === "live" ? "NHC's official forecast" : "a hypothetical storm track"}; shelters FEMA NSS, hospitals CMS, fire departments USFA registry.
        {" "}{sim.assumptions.join(" ")} Guidance is drawn from Ready.gov, NWS/NHC, OSHA and CDC; follow your agency&apos;s own procedures and local officials&apos; orders.
      </p>
    </div>
  );
}

// State lives in the Ask AI panel (via this hook) so expanding/collapsing the panel, which remounts
// <Simulator>, keeps the exercise in progress.
export function useSimulator() {
  const [setup, setSetup] = useState(null);
  const [liveStorms, setLiveStorms] = useState(null);
  const [form, setForm] = useState({ role: null, county: null, mode: "hypothetical", storm_id: null, category: "3", approach: "south", offset: "direct", hours_to_landfall: 72 });
  const [sim, setSim] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [progress, setProgress] = useState({ idx: 0, picks: {}, done: {} });

  useEffect(() => {
    fetchSimulateSetup().then(setSetup).catch(() => setError("The simulator isn't available right now."));
    fetchLiveStorms().then(setLiveStorms).catch(() => setLiveStorms([]));
  }, []);

  async function start() {
    setBusy(true);
    setError("");
    try {
      const { county, ...rest } = form;
      const result = await runSimulation({ ...rest, fips: county.fips });
      setProgress({ idx: Math.max(0, result.phases.findIndex((p) => p.key === result.start_phase)), picks: {}, done: {} });
      setSim(result);
    } catch (e) {
      setError(`Couldn't build the exercise: ${e.message}`);
    } finally {
      setBusy(false);
    }
  }

  return { setup, liveStorms, form, setForm, sim, setSim, busy, error, progress, setProgress, start };
}

export default function Simulator({ state }) {
  const { setup, liveStorms, form, setForm, sim, setSim, busy, error, progress, setProgress, start } = state;
  return (
    <div className="flex flex-col gap-4">
      {!sim && (
        <div>
          <h3 className="text-[1.15rem] font-bold text-[#112f4d]">Learn how to get prepared</h3>
          <p className="text-[0.85rem] text-[#4f6981]">
            Rehearse a hurricane with your team before it happens: what to do at each stage, what resources your county has,
            what to tell residents, and the safety steps that matter most.
          </p>
        </div>
      )}
      {!setup && !error && <p className="text-[0.85rem] text-[#607d98]">Loading…</p>}
      {setup && !sim && <Setup setup={setup} form={form} setForm={setForm} liveStorms={liveStorms} onStart={start} busy={busy} error={error} />}
      {sim && <Run sim={sim} progress={progress} setProgress={setProgress} onRestart={() => setSim(null)} />}
      {!setup && error && <p className="rounded-xl bg-bad-bg px-3 py-2 text-[0.85rem] text-bad-text" role="alert">{error}</p>}
    </div>
  );
}
