// Backend data for the screens. The Ask AI panel calls /api/chat itself.
import { useEffect, useState } from "react";

async function readJSON(r) {
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

// The same tool outputs the agent sees (advisory, impact, staging, assets...),
// validated against backend/agent/contracts.py. No LLM involved.
// params: { max_trucks, closed: [...], include_surge } for what-ifs; omitted = default plan.
// agentId: multi-agent service (/api/agents/{id}/overview); null = the single-agent /api/overview.
export function fetchOverview(params = {}, agentId = null) {
  const q = new URLSearchParams();
  if (params.max_trucks != null) q.set("max_trucks", params.max_trucks);
  for (const c of params.closed ?? []) q.append("closed", c);
  if (params.include_surge) q.set("include_surge", "true");
  const qs = q.toString();
  const base = agentId ? `/api/agents/${encodeURIComponent(agentId)}/overview` : "/api/overview";
  return fetch(qs ? `${base}?${qs}` : base).then(readJSON);
}

export function fetchAgents() {
  return fetch("/api/agents").then(readJSON);
}

export function fetchHealth() {
  return fetch("/api/health").then(readJSON);
}

// Research drafts (read-only): runs list, and one draft with the judge's verdicts.
export function fetchResearchRuns() {
  return fetch("/api/research").then(readJSON);
}

export function fetchResearchRun(hazard, fips, runId) {
  const p = [hazard, fips, runId].map(encodeURIComponent).join("/");
  return fetch(`/api/research/${p}`).then(readJSON);
}

export function chatUrl(agentId) {
  return agentId ? `/api/agents/${encodeURIComponent(agentId)}/chat` : "/api/chat";
}

// Data is tagged with the agent it belongs to and only returned for that agent: on an agent switch
// the old agent's data would otherwise render one frame in the new agent's pages (and crash them).
export function useOverview(agentId = null, enabled = true) {
  const [state, setState] = useState({ id: undefined, overview: null, error: "" });
  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    fetchOverview({}, agentId)
      .then((o) => !cancelled && setState({ id: agentId, overview: o, error: "" }))
      .catch((e) => !cancelled && setState({ id: agentId, overview: null, error: `Can't load this agent's data (${e.message}).` }));
    return () => { cancelled = true; };
  }, [agentId, enabled]);
  const current = state.id === agentId;
  return { overview: current ? state.overview : null, error: current ? state.error : "" };
}
