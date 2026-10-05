"""Research model ids, read once (ADR gemini-only-research). Both are Vertex Gemini via ADC; both ids
below exist only at location=global (R0, 2026-10-05). Validated by a ping at job start, never on first use."""

import os

RESEARCH_MODEL = os.getenv("RESEARCH_MODEL", "gemini-3.8-flash")
JUDGE_MODEL = os.getenv("RESEARCH_JUDGE_MODEL", "gemini-3.1-pro-preview")


def vertex_env() -> None:
    """Defaults for a local run; Cloud Run sets these explicitly."""
    os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "TRUE")
    os.environ.setdefault("GOOGLE_CLOUD_PROJECT", "uc3-storm-impact-intelligence")
    os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "global")
