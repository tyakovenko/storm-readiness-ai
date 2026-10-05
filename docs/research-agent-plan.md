# Research agent + judge: plan

Branch `research-agent` (from `main` 8b458fc). Replaces Phase 5 of `execution-plan-county-agents.md`.
ADRs: `decisions/20261005-research-offline-human-gate.md`, `decisions/20261005-layered-judge.md`, `decisions/20261005-gemini-only-research.md`, `decisions/20261005-numbers-by-reference.md`.

Each phase ends with its gate passing, a commit, and a check-in. Work can stop after any phase. Later phases are then future improvements and the earlier ones still stand on their own.

## Flow

```
Target (county, hazard, aliases, cities, storms)
  │
  ▼
Number pass (numbers.py): spans N1..Nk, page tagged ⟦Nk⟧ (code, no LLM)
  │
  ▼
Researcher (ADK, gemini-3.8-flash)        tools: search sub-agent (Google Search), socrata_catalog,
  │  FactDrafts with value_ref (never a value)    arcgis_hub_search, legistar_search, fetch_source
  ▼
Judge  L1 fixed checks (verify.py)  ──fail──► unsupported / unchecked
  │    L2 entailment (Pro)          ──fail──► unsupported
  │    L3 corroboration (Pro + search, key metrics only)
  ▼
DraftPack + FactReviews → gs://…/processed/packs_draft/{hazard}/{fips}/{run_id}.json
  │
  ▼
Research page (review) → human accept/reject per fact → publish → processed/packs/ + index.json
  │
  ▼
registry lists the county → template pages + its own chat (no new UI code)
```

## Phases

### R0: verify platform assumptions (no product code) ✅ 2026-10-05
- [x] Gemini on Vertex (`models.list`, project uc3-storm-impact-intelligence): Pro tier = `gemini-3.1-pro-preview` (global only), `gemini-2.5-pro` (global + us-central1). `gemini-3.8-flash` global only. No 3.5/3.8 Pro.
- [x] Scope-trap probe (FEMA PA applicant county vs damage site): 3.1-pro-preview, 2.5-pro and 3.8-flash all reject it (9–14 s). **Judge default `gemini-3.1-pro-preview`**. 2.5-pro is the GA alternative if the preview is withdrawn. Final pick by the R3 planted-error eval across all three, not by this one probe.
- [x] ADK 2.11.0 / google-genai 2.28.0: `google_search` **can** share an `LlmAgent` with function tools on 3.8-flash (grounded, 2 URLs). No `AgentTool` sub-agent needed.
- [x] Grounding sources = `vertexaisearch.cloud.google.com/grounding-api-redirect/…`, title = domain only. HEAD with a browser-like User-Agent resolves them (→ `https://mitigation.readyharris.org/`). `fetch.py` resolves before storing.
- [ ] Fetching from Cloud Run egress: moved to R4 (needs the job deployed).

Probe scripts are in the session scratchpad, not the repo.

### R1: schema + number pass + fixed checks (no LLM) ✅ 2026-10-05
- `backend/research/schema.py`: Target, FactDraft (researcher output, `value_ref`), Fact (`value_raw` required with a value), Page, Check (`severity` block|flag), FactReview, Verdict, DraftPack.
- `backend/research/policy.py`: metric vocabulary (key / ages), unit synonyms, tolerances, staleness, caps, official domains.
- `backend/research/numbers.py`: `extract` → NumberSpan (kind, qualifier, scale, ranges), `tag`, `sentence_around`, `fact_from_ref`.
- `backend/research/verify.py`: `check_fact` → fetch, quote_in_source (offsets via normalized→original map, compact fallback for PDF hyphenation), value_at_source (judge's own parse; usable kind + same value + same qualifier), unit (sentence of the quote), jurisdiction, storm (name + year), stale (flag). `fixed_verdict`.
- Tests: `tests/test_research_numbers.py`, `tests/test_research_verify.py`.

**Gate:** ✅ 58 research tests; full suite 183 passed, 3 skipped (network-free). Note: `backend/.venv` is incomplete (no numpy/google), so the full suite was run in a fresh venv from `requirements.txt`.

### R2: fetch + researcher agent
- `research/fetch.py`: `fetch_source(url) -> Page(final_url, content_type, text, status, retrieved)`. HTML → text (stdlib parser), PDF → text (**adds pypdf: own ADR before merging**). Records redirects. Size and time caps. Errors return a Page with `error`, never raise into the agent silently.
- `research/tools.py`: `socrata_catalog(domain, q)`, `arcgis_hub_search(q, bbox)`, `legistar_search(client, q)`, plus the search sub-agent.
- `research/researcher.py`: ADK agent. Instruction is built from `Target` and the pack's `gaps` (the gaps list is the to-do list). Output is validated against `Fact` with pydantic. Invalid facts are dropped and **counted in the run log**.
- `research/run.py`: `python -m research.run --fips 48201 --hazard hurricane [--push]`. Writes a DraftPack locally and, with `--push`, to GCS.

**Gate:** offline tests with recorded pages (fixtures) for each tool. One live run on Harris produces ≥ 10 schema-valid facts, every one with a resolvable URL.

### R3: judge L2 + L3 + planted-error eval
- `research/judge.py`: `review(draft) -> DraftPack` with reviews filled in. L1 → L2 → L3 per fact, stopping at the first failure. Every call is logged (model, tokens, latency).
- `backend/evals/research_planted_errors.py`: start from a correct draft and inject one error per kind:

| Kind | Example |
|---|---|
| wrong value | 1,314 → 1,341 |
| wrong unit | beds → people/day |
| wrong county | neighboring county's shelter |
| applicant county | FEMA PA HQ county as damage county |
| aggregate vs unit | citywide total stated as one department |
| wrong storm / year | Ike figure labeled Harvey |
| quote not in page | paraphrase / invented quote |
| number only in citation | "FOX 4" |
| stale | 2012 capacity stated as current |
| syndicated "second source" | AP copy counted as independent |

**Gate:** every planted error is caught (not `verified`); false alarms on the correct facts are reported (target ≤ 10 %). Results table in this doc.

### R4: job + API + Research page
- Cloud Run job `storm-research` (same image, entrypoint `research.run`), SA with write access to `processed/packs_draft/` only.
- API: `POST /api/research` (start; returns run_id), `GET /api/research/{run_id}` (status + DraftPack), `GET /api/research` (runs list).
- UI: Research page (hash route `#/research`, a card on the landing page). Facts table sorted by verdict, each with quote, source link, the failed check's detail, and accept/reject. Labeled "draft, not published".
- Publish: `python -m research.publish --run <id>` merges the accepted facts into the pack, sets `status`, updates `index.json`. A UI Approve button only once the API has auth.

**Gate:** headless click-through of the Research page with no errors; a published test pack appears in `/api/agents` and its chat answers from it.

### R5: gold-set eval
- Hand-label the Harris, Miami-Dade and Lee local facts (the `gaps` metrics). Today's packs have **only national data**, so the gold set has to be built first (Taya + Claude, about 1–2 h per county).
- Metrics per county: fact recall vs gold, precision, **false-verification rate on key metrics (bar: 0)**, `unchecked` share, cost and time per run.

**Gate:** metrics table in this doc; the demo runs the 4th county (Palm Beach or Charleston) from a recorded run.

## Judge inputs
Defaults in brackets accepted by Taya 2026-10-05, encoded in `research/policy.py`.

1. **Key metrics:** which facts need 2 independent sources to be `verified`? [shelter capacity, peak outage, staff/crew counts, FEMA $ totals, evacuee counts]
2. **Value tolerance:** does the value in the quote have to match exactly, or can rounding pass ("about 1,300" for 1,314)? [exact for the quote match; rounding allowed only between corroborating sources, ≤ 2 %]
3. **Source tiers:** can one official document (a county after-action report, a budget book) count as `verified` on its own? [no: it becomes `single_source` marked "official", so the reviewer can accept it quickly]
4. **Staleness:** how old can capacity and staffing facts be before they're flagged? [older than 5 years → flagged "stale"; past-storm facts never go stale]
5. **Conflicts:** newest official source wins, or always shown to the reviewer? [always shown, never resolved automatically]
6. **Cost cap per run:** [≤ 150 Gemini calls and ≤ 40 fetches per county run; the run stops with a partial draft and the cap shown]
7. **Who labels the gold set (R5)?** [Taya reviews, Claude drafts]

## Related issues (UI, not this branch)
- #6 remove Ask AI from the landing page
- #7 Sources section at the bottom of each county page. Research facts feed it with `verdict`.

## Results
| Phase | Result |
|---|---|
| R0 | Judge `gemini-3.1-pro-preview` (alt `gemini-2.5-pro`); search + function tools mix in one ADK agent; grounding redirects resolve via HEAD |
| R1 | 58 tests (number kinds/qualifiers/ranges, every layer-1 check pass + fail, by-reference round trip). Known limits: "US 59" reads as a quantity; PDF table cells lose headers (ADR numbers-by-reference) |
