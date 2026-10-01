// The only place the frontend talks to the backend.

async function readJSON(r) {
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export function fetchHealth() {
  return fetch("/api/health").then(readJSON);
}

// Tool outputs for the dashboard screens (no LLM). maxTrucks/closed are what-ifs for solve_staging.
export function fetchOverview({ maxTrucks, closed = [] } = {}) {
  const params = new URLSearchParams();
  if (maxTrucks !== undefined && maxTrucks !== null) params.set("max_trucks", maxTrucks);
  closed.forEach((id) => params.append("closed", id));
  const qs = params.toString();
  return fetch(`/api/overview${qs ? `?${qs}` : ""}`).then(readJSON);
}

// Runs the agent + trust layer. Costs money with a real LLM; free in mock mode.
export function askAgent(message, history = []) {
  return fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, history }),
  }).then(readJSON);
}
