# Agent demo (Workstream C)

A basic agent + trust layer with a React chat UI. All tools return **stub data** until the data and optimization engines land.

To run it, follow [Run the demo on your laptop](../README.md#run-the-demo-on-your-laptop) in the main README.

## How it fits together

```
React (frontend/src/App.jsx) ──POST /api/chat──► FastAPI (app.py)
                                                   └─ agent/loop.py      tool-calling loop, regenerate once on a trust block
                                                        ├─ agent/llm.py        LLM_MODEL config; LiteLLM or mock; fails loudly at startup
                                                        ├─ agent/tools.py      tool schemas + functions (stubbed)
                                                        ├─ agent/contracts.py  output shape per tool, validated on every call
                                                        ├─ agent/stub_data.py  fake data; replace with real engines
                                                        ├─ agent/trust.py      numbers (bound to places), places/facilities, required steps, confidence vs lead time
                                                        └─ agent/judge.py      actionable check (LLM judge, optional, non-blocking)
evals/planted_errors.py   plants known mistakes in clean answers, reports what the trust layer catches
```

To plug in a real engine, replace a function in `tools.py` and keep its output keys; `contracts.py` enforces them. Field-by-field sources: [`docs/data-contract.md`](../docs/data-contract.md).

Tests (mock mode, no key): `.venv/bin/pytest -q`
Planted-error report: `.venv/bin/python -m evals.planted_errors`

## Not built yet (to decide as a team)

- Agent framework: this is a plain loop; Google ADK is still an option
- Trust checks: calibrate confidence thresholds; validate the judge on a human-labeled sample; claim-level check for timing and relabels (not caught today)
- Resource types (water, generators, personnel) in `solve_staging`
- GCP deployment (Cloud Run + Gemini on Vertex; see `docs/agent-branch-notes.md`)
- Replay clock (only data known at advisory time)
- Map, three user views, review/approve flow (Workstream D)

## Research layer (`research/`)

Drafts local facts for a county (city shelters, staff, crews, staging, evacuees, 311, FEMA aid) from public sources. A stricter judge checks every fact. A person publishes what they accept, and only then do county agents see it (`get_local_facts`). Plan and results: `docs/research-agent-plan.md`. Decisions: `docs/decisions/20261005-*.md`.

| Step | Code |
|---|---|
| Number pass: every number on a page parsed by code into typed spans; the LLM cites `⟦N17⟧`, never types a value | `numbers.py` |
| Researcher: ADK agent on `gemini-3.8-flash` + Google Search, ArcGIS, Legistar, page reader | `researcher.py`, `tools.py`, `fetch.py` |
| Typed contract: closed metric vocabulary, unit, int counts / float USD, dates, URLs, storm and place from the target | `schema.py`, `policy.py` |
| Judge layer 1: fixed checks on the judge's own fetch (quote, value at source, unit, jurisdiction, subject, storm, staleness) | `verify.py` |
| Judge layers 2-3: entailment (unanimous ×3 for key metrics) and independent corroboration on `gemini-3.1-pro-preview` | `judge.py` |
| Drafts, publish, API | `store.py`, `publish.py`, `/api/research` |

```bash
# research + judge one county (writes data/processed/packs_draft/hurricane/<fips>/<run_id>.json)
python -m research.run --fips 48201            # --no-judge | --review <run_id> | --push (to GCS)
# publish reviewed facts into the county pack (a person's decision)
python -m research.publish --fips 48201 --run <run_id> --reviewer "<name>" --accept verified,single_source
# evals
python -m evals.research_planted_errors        # judge on planted errors (needs Vertex)
python -m evals.research_gold --fips 48201 --validate --run <run_id>
```
Vertex env as for the agents (`GOOGLE_GENAI_USE_VERTEXAI=TRUE`, `GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_LOCATION=global`). Cloud: job `storm-research` (same image, service account can only create objects under `processed/packs_draft/`).

Known limits: PDFs not read yet (issue #8); gold sets are drafts awaiting review; Lee's gold set is thin until PDFs work.
