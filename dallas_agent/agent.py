"""Dallas agent for `adk web` / `adk run` (from the repo root: `adk web`).

Same agent the API serves (backend/agent/dallas_adk.py). Note: `adk web` runs
the bare agent; the trust layer only runs through POST /api/chat.
Needs LLM_MODEL (e.g. gemini-3.8-flash) + GOOGLE_GENAI_USE_VERTEXAI=TRUE,
GOOGLE_CLOUD_PROJECT, GOOGLE_CLOUD_LOCATION=global.
"""

import sys
from pathlib import Path

_backend = str(Path(__file__).resolve().parent.parent / "backend")
if _backend not in sys.path:
    sys.path.insert(0, _backend)

from agent.dallas_adk import build_agent, build_model  # noqa: E402

root_agent = build_agent(build_model())
