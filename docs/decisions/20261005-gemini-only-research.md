# Research layer runs only on Gemini (Vertex AI)

**Status:** Accepted 2026-10-05. Judge model id still to be confirmed on Vertex (plan R0).

## Context
Taya wants GCP credits used and everything on Gemini. The chat agents already run on Vertex Gemini through ADK (ADC, no API key). `agent/judge.py` also accepts LiteLLM model strings (Claude, used in early local runs).

## Decision
- **Researcher:** ADK agent on `gemini-3.8-flash` (location `global`, already confirmed working). Fast and cheap enough for many search and extraction steps.
- **Judge:** a stronger Gemini model (Pro tier, thinking on) for entailment and corroboration. The model id comes from env `RESEARCH_JUDGE_MODEL` and is checked with one ping when the job starts. A missing or unavailable model stops the run with an error; it never quietly falls back to Flash. If no Pro model is available on Vertex, the fallback is Flash with thinking on, recorded as `judge_model` in the draft and shown on the Research page.
- **Search:** Gemini Google Search grounding. ADK has historically not allowed the built-in `google_search` tool in the same agent as function tools, so search runs in a sub-agent called through `AgentTool`. To check against the installed ADK version (R0).
- **Grounding links** come back as Vertex redirect URLs. They are resolved to the final URL before being stored as `source_url`. An unresolved redirect is never stored.
- No LiteLLM or Anthropic code paths in `backend/research/`.

## Rejected
- **Claude as the judge** (a different model family, so errors less likely to overlap): conflicts with the Gemini-only requirement and credits. The independence the judge needs comes from different evidence (ADR layered-judge), not a different vendor.
- **The same Flash model for both roles:** the judge is the more important step and gets the stronger model.

## Consequences
- Researcher and judge are both Gemini, so their errors may overlap. This is covered by the fixed checks (layer 1) and the planted-error eval, not by the choice of model.
- Model ids live in env, read in one place (`research/config.py`), and are recorded in every DraftPack.
