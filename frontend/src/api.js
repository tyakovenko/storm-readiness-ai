
// API communication layer for StormReady AI.
// Supports both single-agent and multi-agent modes.

import { useEffect, useState } from "react";

// Shared JSON response handler.
async function readJSON(response) {
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }

  return response.json();
}

// Fetch overview data for a storm agent.
// Optional parameters support resource planning what-ifs.
export function fetchOverview(
  params = {},
  agentId = null
) {
  const query = new URLSearchParams();

  if (params.max_trucks != null) {
    query.set("max_trucks", params.max_trucks);
  }

  for (const county of params.closed ?? []) {
    query.append("closed", county);
  }

  if (params.include_surge) {
    query.set("include_surge", "true");
  }

  if (params.horizon_h != null) {
    query.set("horizon_h", params.horizon_h);
  }

  const queryString = query.toString();

  const baseUrl = agentId
    ? `/api/agents/${encodeURIComponent(
        agentId
      )}/overview`
    : "/api/overview";

  const url = queryString
    ? `${baseUrl}?${queryString}`
    : baseUrl;

  return fetch(url).then(readJSON);
}

// Phase 2C: thin clients for the existing Human-in-the-Loop plan endpoints (backend/app.py,
// agent/plan_store.py) -- no new storage or approval logic, just reusing what's already there.
async function postJSON(url, body) {
  const res = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!res.ok) {
    const detail = await res.json().catch(() => null);
    throw new Error(detail?.detail || `HTTP ${res.status}`);
  }
  return res.json();
}

export function createPlan({ agentId, county, inputs, allocations, notes = "" }) {
  return postJSON("/api/plans", { agent_id: agentId, county, inputs, allocations, author: "Emergency Manager", notes });
}

export function approvePlan(planId, notes = "Approved for execution.") {
  return postJSON(`/api/plans/${encodeURIComponent(planId)}/approve`, { approver: "Incident Commander", notes });
}

// Fetch all available storm agents.
export function fetchAgents() {
  return fetch("/api/agents").then(readJSON);
}

// Detect backend operating mode.
export function fetchHealth() {
  return fetch("/api/health").then(readJSON);
}

// Fetch live storm monitoring status.
export function fetchLiveStatus() {
  return fetch("/api/live/status").then(readJSON);
}

// Return the correct AI chat endpoint.
export function chatUrl(agentId) {
  return agentId
    ? `/api/agents/${encodeURIComponent(
        agentId
      )}/chat`
    : "/api/chat";
}

// React hook for fetching agent overview data.
// Prevents stale data from a previous agent
// appearing when the selected agent changes.
export function useOverview(
  agentId = null,
  enabled = true,
  horizonH = null
) {
  const [state, setState] = useState({
    id: undefined,
    overview: null,
    error: "",
  });

  useEffect(() => {
    if (!enabled) {
      return;
    }

    let cancelled = false;

    fetchOverview({ horizon_h: horizonH }, agentId)
      .then((overview) => {
        if (!cancelled) {
          setState({
            id: agentId,
            overview,
            error: "",
          });
        }
      })
      .catch((error) => {
        if (!cancelled) {
          setState({
            id: agentId,
            overview: null,
            error: `Can't load this agent's data (${error.message}).`,
          });
        }
      });

    return () => {
      cancelled = true;
    };
  }, [agentId, enabled, horizonH]);

  const isCurrentAgent = state.id === agentId;

  return {
    overview: isCurrentAgent
      ? state.overview
      : null,

    error: isCurrentAgent
      ? state.error
      : "",
  };
}

// Live Operations uses the existing NOAA cache and stub staging endpoints.
export function fetchLiveStorms() {
  return fetch("/api/live/storms").then(readJSON);
}
export function fetchStaging(maxTrucks = null) {
  const query = maxTrucks == null ? "" : "?max_trucks=" + encodeURIComponent(maxTrucks);
  return fetch("/api/staging" + query).then(readJSON);
}

// Storm-wide, multi-county Risk Map data (Phase 1): the existing hurricane pack's own replayed
// storm, extended to its real neighboring counties, at a real forecast horizon (24h/48h/72h
// after the advisory's own issuance -- never a fabricated horizon; see backend/models/
// replay_track.py). horizonH omitted lets the backend pick its own real default.
export function fetchStormOverview(slug, horizonH = null) {
  const query = horizonH != null ? `?horizon_h=${encodeURIComponent(horizonH)}` : "";
  return fetch(`/api/storms/${encodeURIComponent(slug)}/overview${query}`).then(readJSON);
}

// React hook mirroring useOverview(): re-fetches whenever slug or horizonH changes, and ignores
// a stale response if the slug/horizon changed again before it arrived.
export function useStormOverview(slug, horizonH) {
  const [state, setState] = useState({ key: null, overview: null, error: "" });

  useEffect(() => {
    if (!slug) return;
    let cancelled = false;
    const key = `${slug}:${horizonH ?? ""}`;

    fetchStormOverview(slug, horizonH)
      .then((overview) => {
        if (!cancelled) setState({ key, overview, error: "" });
      })
      .catch((error) => {
        if (!cancelled) setState({ key, overview: null, error: `Can't load this storm's risk map (${error.message}).` });
      });

    return () => {
      cancelled = true;
    };
  }, [slug, horizonH]);

  const key = `${slug}:${horizonH ?? ""}`;
  const isCurrent = state.key === key;
  return { overview: isCurrent ? state.overview : null, error: isCurrent ? state.error : "" };
}
