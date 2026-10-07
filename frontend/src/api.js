// Backend data for the screens. The Ask AI panel calls /api/chat itself.
import { useEffect, useState } from "react";

async function readJSON(r) {
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

// The same tool outputs the agent sees (advisory, impact, staging, assets...),
// validated against backend/agent/contracts.py. No LLM involved.
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

export function fetchLiveStatus() {
  return fetch("/api/live/status").then(readJSON);
}

export function fetchLiveStorms() {
  return fetch("/api/live/storms").then(readJSON);
}

export function fetchStaging(maxTrucks = null) {
  const url = maxTrucks != null ? `/api/staging?max_trucks=${maxTrucks}` : "/api/staging";
  return fetch(url).then(readJSON);
}

export function chatUrl(agentId) {
  return agentId ? `/api/agents/${encodeURIComponent(agentId)}/chat` : "/api/chat";
}

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
