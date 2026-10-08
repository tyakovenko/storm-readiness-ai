
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
  enabled = true
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

    fetchOverview({}, agentId)
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
  }, [agentId, enabled]);

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
