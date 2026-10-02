// Backend data for the screens. The Ask AI panel calls /api/chat itself.
import { useEffect, useState } from "react";

async function readJSON(r) {
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

// The same tool outputs the agent sees (advisory, impact, staging, assets...),
// validated against backend/agent/contracts.py. No LLM involved.
export function fetchOverview() {
  return fetch("/api/overview").then(readJSON);
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
