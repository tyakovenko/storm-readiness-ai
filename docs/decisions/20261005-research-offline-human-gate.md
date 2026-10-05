# Research runs offline; new county agents are published packs, never new code or chats

**Status:** Accepted 2026-10-05

## Context
County agents are built from a hazard template (tools, contracts, trust profile, page set) plus a county pack (data). `agent/registry.py` builds them, and the URL `#/agents/<id>` picks one. The research agent finds local facts (shelters, staff, after-action numbers) for a new county. Its output has not been checked yet: the Dallas build had 5 wrong sources. The chat's trust layer checks answers against tool output, not tool output against the real world.

Options considered: (a) a page and chat written for each county, (b) one chat with a research on/off/select switch, (c) research as a separate offline job that produces a draft pack, which a human reviews and publishes.

## Decision
(c).
- The research agent runs as a Cloud Run job, outside any chat request. It writes `processed/packs_draft/{hazard}/{fips}/` (`DraftPack`, `backend/research/schema.py`).
- The judge adds a `FactReview` to every fact. Nothing is published automatically.
- One **Research page** (no chat): pick county + hazard → run status → table of draft facts with source, quote and verdict → reviewer accepts/rejects each fact → **Approve** writes the pack to `processed/packs/` and updates `index.json`.
- Once published, the registry lists the county. Its pages and its own chat come from the hazard template with no UI code. The URL is the "select switch".

## Rejected
- **(a) a page and chat per county:** N copies of the same code, and they drift apart. The template already gives every county its own pages and chat.
- **(b) research mode inside the county chat:** unchecked facts would reach answers that look trust-checked, and a 1–5 min research run doesn't fit in a chat turn.
- **Auto-publish when the judge says verified:** a false verification would go live with no human ever seeing it. The judge's false-verification rate isn't measured yet (see the layered-judge ADR).

## Consequences
- A county with a new hazard (not winter or hurricane) still needs a new template. Out of scope here.
- Publishing is human review time per county. The review table sorts facts by verdict so only single-source, conflicting, unsupported and unchecked facts need reading.
- The Research page needs write access to `processed/packs/` (approve). Until that has auth, Approve runs as a CLI command (`python -m research.publish`) and the page is read-only.
