// Backend data for the screens. The Ask AI panel calls /api/chat itself.
import { useEffect, useState } from "react";

async function readJSON(r) {
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

// The same tool outputs the agent sees (advisory, impact, staging, assets...),
// validated against backend/agent/contracts.py. No LLM involved.
// params: { max_trucks, closed: [...] } for the planner's what-if; omitted = default plan.
export function fetchOverview(params = {}) {
  const q = new URLSearchParams();
  if (params.max_trucks != null) q.set("max_trucks", params.max_trucks);
  for (const c of params.closed ?? []) q.append("closed", c);
  const qs = q.toString();
  return fetch(qs ? `/api/overview?${qs}` : "/api/overview").then(readJSON);
}

export function useOverview() {
  const [overview, setOverview] = useState(null);
  const [error, setError] = useState("");
  useEffect(() => {
    fetchOverview()
      .then(setOverview)
      .catch(() => setError("Can't reach the backend. Is it running on port 8001?"));
  }, []);
  return { overview, error };
}
