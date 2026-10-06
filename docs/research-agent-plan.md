# Research agent + judge: plan

Branch `research-agent` (from `main` 8b458fc). Replaces Phase 5 of `execution-plan-county-agents.md`.
ADRs: `decisions/20261005-research-offline-human-gate.md`, `decisions/20261005-layered-judge.md`, `decisions/20261005-gemini-only-research.md`, `decisions/20261005-numbers-by-reference.md`, `decisions/20261005-typed-research-facts.md`.

Each phase ends with its gate passing, a commit, and a check-in. Work can stop after any phase. Later phases are then future improvements and the earlier ones still stand on their own.

## Flow

```
Target (county, hazard, aliases, cities, storms)
  │
  ▼
Number pass (numbers.py): spans N1..Nk, page tagged ⟦Nk⟧ (code, no LLM)
  │
  ▼
Researcher (ADK, gemini-3.8-flash)        tools: google_search, read_source, find_in_source, submit_fact,
  │  FactDrafts with value_ref (never a value)    report_gap, arcgis_search, legistar_search
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

### R2: fetch + researcher agent ✅ 2026-10-05
- `research/fetch.py`: `Fetcher` (per role, cache + cap) → `Page`. HTML → text (scripts dropped, table cells separated by `|`). JSON → one `KEY: value; …` line per record (ArcGIS features). Errors are returned as `Page.error`. HTML under 200 chars is flagged as a JS-rendered page. **PDFs → error until issue #8** (layout- and table-preserving extraction). No new dependency.
- `research/numbers.py` addition: field-aware kinds for structured rows (`CAPACITY: 1200` quantity, `OBJECTID`/`LAT`/`ZIP` label, `YEAR_*` year).
- `research/tools.py` `ResearchSession`: `read_source` (tagged, chunked), `find_in_source`, `submit_fact` (by reference; runs the layer-1 checks on the researcher's copy and returns refusals with reasons, all logged), `report_gap`, `arcgis_search` (+ `query_url` for feature layers), `legistar_search` (only configured clients).
- `research/targets.py`: Target from the published pack (storms, gaps) + per-county config (aliases, cities, portals). Portals probed 2026-10-05: Legistar only `miamidade`; **no Socrata for the three counties → Socrata tool dropped** (add with the Dallas/winter target).
- `research/researcher.py`: ADK `LlmAgent` (google_search + tools in one agent, per R0). `CallCap` before_model_callback stops at the cap with a partial draft. `run_log` in the DraftPack.
- `research/run.py`: CLI, checks the model at start, writes `data/processed/packs_draft/{hazard}/{fips}/{run_id}.json`, `--push` to GCS.
- Tests: `tests/test_research_tools.py` (offline).

**Gate:** offline tests pass. One live run on Harris → ≥ 10 schema-valid facts, every one with a resolvable URL.

### R3: judge L2 + L3 + planted-error eval ✅ 2026-10-05
- `research/judge.py` `Judge`: L1 (`verify`, own Fetcher) → L2 entailment (passage around the quote + claim in words; labels supports / wrong_metric / wrong_scope / wrong_time / not_enough; unparseable → UNCHECKED) → L3 for key metrics: own Google Search (grounded), candidate pages from other domains (max 3), **model picks a number tag, code compares** (±2 %). Copies are detected by in-order overlap ≥ 0.9 of the shorter sentence (a wire copy's new lead-in defeats plain similarity). A conflict always → CONFLICTING. `GeminiCalls` has its own call cap.
- **Added `place` to facts** (eval finding): a city's own figure (Houston shelters) is a fact about the city. Without it, every city figure was a scope error. The fixed check requires the place to be the county or one of its listed cities, and named on the page.
- `evals/research_planted_errors.py`: 10 planted errors + 4 controls on synthetic pages. Only web search is stubbed.
- `tests/test_research_judge.py`: verdict logic with a scripted model.

**Gate:** ✅ all three models 10/10 caught, 0 false verifications, 0/4 false alarms (table below). **The eval is at ceiling, so it doesn't pick the model.** The judge stays `gemini-3.1-pro-preview` (strongest available, as specified), but there's no evidence yet that it beats 3.8-flash. Harder cases come from real drafts (R5): a number in a table row, two figures in one sentence across two storms, a figure from a plan vs an after-action report.

### R4: job + API + Research page ✅ 2026-10-06 (app redeploy waits for Taya's go)
- [x] `research/store.py` (local, then GCS; path parts validated), `research/run.py` (research → save → judge → save; `--review RUN_ID` re-judges; `--no-judge`), wall-clock cap `MAX_RUN_SECONDS` with a partial draft instead of a kill.
- [x] `research/publish.py`: reviewer, `--accept verified,single_source`, `--reject ids`, `--also ids` (override, flagged). Writes `pack.json` `facts` + `research` provenance; `--push`.
- [x] API: `GET /api/research`, `GET /api/research/{hazard}/{fips}/{run_id}` (404 missing, 503 store down).
- [x] UI: `#/research` (runs) and `#/research/<hazard>/<fips>/<run_id>` (facts sorted conflicting → single → unchecked → verified → unsupported, verdict filters, quote + checks per fact, gaps, run log, partial banner). Landing card links to it. No chat (ADR).
- [x] Live Harris draft (20 facts, 677 s) + judge: 4 verified / 6 single / 10 unsupported. **2 of 4 verified were wrong** (CenterPoint workers as staff; a coincident "250" on an unrelated page). Fixes: `subject` + metric definitions (utility metrics split out), entailment required on corroborating passages, typed contract (ADR typed-research-facts), 429/503 retries, GET fallback for redirects.
- [x] Hang fixed: field-name regex backtracked catastrophically and `extract` was O(n²) (full-text rfind / slice per number). Now linear; regression test.
- [x] Cloud Run job `storm-research` + SA (write `processed/packs_draft/` only). IAM run by Taya 2026-10-05; job created (image `app:research-3b6435d`, to be updated). Same image as the app; the job overrides the command.

```bash
P=uc3-storm-impact-intelligence; B=uc3-storm-impact-intelligence-data
SA=storm-research@$P.iam.gserviceaccount.com
gcloud iam service-accounts create storm-research --project=$P --display-name="Research job"
gcloud projects add-iam-policy-binding $P --member=serviceAccount:$SA --role=roles/aiplatform.user
gcloud projects add-iam-policy-binding $P --member=serviceAccount:$SA --role=roles/logging.logWriter
# read packs + national data; write drafts only (IAM condition on the object prefix)
gcloud storage buckets add-iam-policy-binding gs://$B --member=serviceAccount:$SA --role=roles/storage.objectViewer
gcloud storage buckets add-iam-policy-binding gs://$B --member=serviceAccount:$SA --role=roles/storage.objectCreator \
  --condition='expression=resource.name.startsWith("projects/_/buckets/'$B'/objects/processed/packs_draft/"),title=drafts-only'
# job (IMG = the app image already in Artifact Registry)
gcloud run jobs create storm-research --project=$P --region=us-central1 --image=$IMG --service-account=$SA \
  --command=python --args=-m,research.run,--fips,48201,--push --memory=2Gi --task-timeout=1800 --max-retries=0 \
  --set-env-vars=GOOGLE_GENAI_USE_VERTEXAI=TRUE,GOOGLE_CLOUD_PROJECT=$P,GOOGLE_CLOUD_LOCATION=global
gcloud run jobs execute storm-research --region=us-central1 --args=-m,research.run,--fips,12086,--push
```
`objectCreator` can create but not overwrite, and each run writes a new `<run_id>.json`. `--review` re-judging an existing draft writes the same path, so it runs locally (or with objectAdmin on that prefix if needed later).
- [x] Fetching from Cloud Run egress (moved from R0): works (job fetched ArcGIS + miamidade.gov, 2026-10-05).
- [x] Headless click-through of the Research pages (landing card, runs list, draft table + detail, 404 alert; no errors besides favicon).
- [x] County agents read published facts: hurricane tool `get_local_facts(metric?, storm_id?)` + `LocalFacts` contract + instruction line (say whose figure, which storm/date; single-source said as such; conflicting/unchecked never stated as settled). Quote + URL under `source` (trust citation key), so numbers inside a quote can't vouch for a claim. Sources registry on pages = issue #7.
- [x] Judge: key-metric entailment must be unanimous over 3 calls (Harris f3 flipped between runs); JSON list responses unwrapped. Re-judge after typed contract: f8 (utility workers) now unsupported; f7 re-checked by hand: the governor's "250 bed medical shelter" and PBS's "as many as 250 people" area are very likely the same facility → legitimate corroboration, not a false verification.

### R5: gold-set eval ✅ 2026-10-06 (gold sets await Taya's review)
- [x] `evals/research_gold.py`: gold facts are **specs** (metric, storm, place, subject, URL, number as written), built by reference from the live page and held to the same fixed checks as the researcher (`--validate`). Scores: recall (`same_as` merges two sources of one fact), verdicts on matched facts, **false verifications** (verified facts matching a decoy, or contradicting a gold fact with the same metric/storm/place/subject), unscored count.
- [x] Gold sets (drafts, **need Taya's review**): `evals/gold/48201.json` (Harris: 7 facts, 3 decoys, 1 pending PDF), `12086.json` (Miami-Dade: 5 facts incl. two syndicated AP copies, 2 decoys), `12071.json` (Lee: 1 fact, 1 decoy; Ian AAR + Milton figures are in PDFs → #8). All gold facts pass `--validate` live.
- Two candidate gold facts were dropped because their sentence names no unit ("sheltered more than 2,000 from Hurricane Irma", "We had room for 40,000."). The strict unit rule stays: it refuses unclear numbers, at the cost of these.
- [x] Fresh runs, current code (2026-10-06, `7f538de`, judge 4 workers, Flash picker):

| County | Facts | Verdicts (V / S / U) | Gold recall | False verified | Research | Judge | Unreadable sources |
|---|---|---|---|---|---|---|---|
| Harris 48201 | 20 | 0 / 14 / 6 | 4/6 (missed NRG capacity + peak) | **0** | 557 s | 280 s | 21/40 (9 PDF) |
| Miami-Dade 12086 | 8 | 1 / 6 / 1 | 3/3 | **0** | 1020 s (hung call → hard stop) | 134 s | 18/25 (12 PDF) |
| Lee 12071 | 16 | 2 / 7 / 7 | 1/1 | **0** | 931 s (time cap) | 151 s | 22/33 (8 PDF) |

  All 3 verified facts were checked by hand: MD capacity 100,000 (Irma; WLRN ×2), Lee capacity 40,000 + sheltered 4,000 (Ian; WUSF / NACo quoting the county manager). Planted errors: 12/12, 0 false verifications, 0/4 false alarms.
- [x] Gating: **0 false verifications** on all three counties and the planted set.
- Fix after the batch: per-call timeout (120 s) on the researcher's model requests via `generate_content_config`; 408/504 added to retried codes.
- Limits: recall on small, partly self-sourced gold sets (Lee: 1 fact). Biggest lever is PDFs (#8): about a third of unreadable sources, and Lee's best sources.

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

### R3 planted-error eval (2026-10-05)
#### gemini-3.1-pro-preview: caught 10/10, false verifications 0, false alarms 0/4, 15 calls
| case | verdict | ok | layer (expected) | detail |
|---|---|---|---|---|
| control: evacuees by reference | single_source | ✓ | entailment (entailment) | supports: The passage explicitly states that during Hurricane Beryl in 2024, Harris County shelters reached a  |
| control: capacity, independent 2nd source | verified | ✓ | corroboration (corroboration) | https://www.houstonchronicle.com/news/beryl-shelters: 2,000 |
| control: city figure with place=Houston | single_source | ✓ | entailment (entailment) | supports: The passage states that the City of Houston deployed 3,000 employees for the storm response, matchin |
| control: shelter count (non-key) | single_source | ✓ | entailment (entailment) | supports: The passage explicitly states that Harris County opened 12 shelters ahead of Hurricane Beryl's landf |
| wrong value | unsupported | ✓ | fixed (fixed) | 1341 not a value in the quote (numbers there: 1,314 (quantity), July 9 (date)) |
| wrong unit | unsupported | ✓ | fixed (fixed) | metric evacuee_count is counted in people, fact says customers |
| wrong county | unsupported | ✓ | fixed (fixed) | page never mentions Harris County or its cities |
| quote not in page | unsupported | ✓ | fixed (fixed) | quote not in the fetched page |
| number only in citation | unsupported | ✓ | fixed (fixed) | 26 not a value in the quote - present but not a value (numbers there: 26 (label)) |
| applicant county (FEMA PA) | unsupported | ✓ | entailment (entailment) | wrong_scope: The $4.2 million was for emergency protective measures at a facility in Galveston County, not Har |
| city figure as county | unsupported | ✓ | entailment (entailment) | wrong_scope: The passage attributes the 3,000 deployed employees to the City of Houston, not Harris County. |
| wrong storm (Ike figure as Harvey) | unsupported | ✓ | entailment (entailment) | wrong_time: The passage states that 4,100 evacuees were housed during Hurricane Ike in 2008, not Hurricane Har |
| occupancy as capacity | unsupported | ✓ | entailment (entailment) | wrong_metric: The passage states that 1,314 was the peak occupancy of evacuees, not the shelter capacity, whic |
| syndicated copy as 2nd source | single_source | ✓ | corroboration (corroboration) | https://www.ksat.com/news/ap-beryl-shelters: same sentence as the cited source (syndicated copy), not counted |

#### gemini-2.5-pro: caught 10/10, false verifications 0, false alarms 0/4, 15 calls
| case | verdict | ok | layer (expected) | detail |
|---|---|---|---|---|
| control: evacuees by reference | single_source | ✓ | entailment (entailment) | supports: The passage states that for Hurricane Beryl, occupancy in Harris County shelters peaked at 1,314 eva |
| control: capacity, independent 2nd source | verified | ✓ | corroboration (corroboration) | https://www.houstonchronicle.com/news/beryl-shelters: 2,000 |
| control: city figure with place=Houston | single_source | ✓ | entailment (entailment) | supports: The passage states that citywide, the City of Houston deployed 3,000 employees for storm response du |
| control: shelter count (non-key) | single_source | ✓ | entailment (entailment) | supports: The passage states 'Harris County opened 12 shelters ahead of landfall on July 8, 2024' in a report  |
| wrong value | unsupported | ✓ | fixed (fixed) | 1341 not a value in the quote (numbers there: 1,314 (quantity), July 9 (date)) |
| wrong unit | unsupported | ✓ | fixed (fixed) | metric evacuee_count is counted in people, fact says customers |
| wrong county | unsupported | ✓ | fixed (fixed) | page never mentions Harris County or its cities |
| quote not in page | unsupported | ✓ | fixed (fixed) | quote not in the fetched page |
| number only in citation | unsupported | ✓ | fixed (fixed) | 26 not a value in the quote - present but not a value (numbers there: 26 (label)) |
| applicant county (FEMA PA) | unsupported | ✓ | entailment (entailment) | wrong_scope: The passage states the $4.2 million was for emergency measures at a hospital in Galveston County, |
| city figure as county | unsupported | ✓ | entailment (entailment) | wrong_scope: The passage states the 3,000 employees were deployed by the City of Houston, not Harris County. |
| wrong storm (Ike figure as Harvey) | unsupported | ✓ | entailment (entailment) | wrong_time: The passage states the 4,100 evacuee figure is for Hurricane Ike in 2008, not Hurricane Harvey in  |
| occupancy as capacity | unsupported | ✓ | entailment (entailment) | wrong_metric: The passage states that 1,314 was the peak shelter occupancy, not the shelter capacity. |
| syndicated copy as 2nd source | single_source | ✓ | corroboration (corroboration) | https://www.ksat.com/news/ap-beryl-shelters: same sentence as the cited source (syndicated copy), not counted |

#### gemini-3.8-flash: caught 10/10, false verifications 0, false alarms 0/4, 15 calls
| case | verdict | ok | layer (expected) | detail |
|---|---|---|---|---|
| control: evacuees by reference | single_source | ✓ | entailment (entailment) | supports: The passage confirms that Harris County shelter occupancy peaked at 1,314 evacuees during Hurricane  |
| control: capacity, independent 2nd source | verified | ✓ | corroboration (corroboration) | https://www.houstonchronicle.com/news/beryl-shelters: 2,000 |
| control: city figure with place=Houston | single_source | ✓ | entailment (entailment) | supports: The passage confirms that the City of Houston deployed 3,000 employees for storm response during Hur |
| control: shelter count (non-key) | single_source | ✓ | entailment (entailment) | supports: The passage confirms that Harris County opened 12 shelters ahead of Hurricane Beryl's landfall in Ju |
| wrong value | unsupported | ✓ | fixed (fixed) | 1341 not a value in the quote (numbers there: 1,314 (quantity), July 9 (date)) |
| wrong unit | unsupported | ✓ | fixed (fixed) | metric evacuee_count is counted in people, fact says customers |
| wrong county | unsupported | ✓ | fixed (fixed) | page never mentions Harris County or its cities |
| quote not in page | unsupported | ✓ | fixed (fixed) | quote not in the fetched page |
| number only in citation | unsupported | ✓ | fixed (fixed) | 26 not a value in the quote - present but not a value (numbers there: 26 (label)) |
| applicant county (FEMA PA) | unsupported | ✓ | entailment (entailment) | wrong_scope: The funding was for a facility located in Galveston County, rather than Harris County, where the  |
| city figure as county | unsupported | ✓ | entailment (entailment) | wrong_scope: The 3,000 deployed employees were for the City of Houston, not Harris County as a whole. |
| wrong storm (Ike figure as Harvey) | unsupported | ✓ | entailment (entailment) | wrong_time: The passage attributes the 4,100 evacuee figure to Hurricane Ike in 2008 rather than Hurricane Har |
| occupancy as capacity | unsupported | ✓ | entailment (entailment) | wrong_metric: The passage states that 1,314 was the peak shelter occupancy, whereas shelter capacity was 2,000 |
| syndicated copy as 2nd source | single_source | ✓ | corroboration (corroboration) | https://www.ksat.com/news/ap-beryl-shelters: metric not stated |

### Summary
| Phase | Result |
|---|---|
| R0 | Judge `gemini-3.1-pro-preview` (alt `gemini-2.5-pro`); search + function tools mix in one ADK agent; grounding redirects resolve via HEAD |
| R3 (after fixes) | 12/12 caught, 0 false verifications, 0/4 false alarms (gemini-3.1-pro-preview) |
| R3 | 10/10 caught, 0 false verifications, 0/4 false alarms on all 3 models (at ceiling) |
| R1 | 58 tests (number kinds/qualifiers/ranges, every layer-1 check pass + fail, by-reference round trip). Known limits: "US 59" reads as a quantity; PDF table cells lose headers (ADR numbers-by-reference) |
