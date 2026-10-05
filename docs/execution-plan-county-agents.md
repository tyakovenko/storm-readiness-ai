# Execution plan: county agents + research layer

Branch `hurricane-extension`. Written 2026-10-05. Large change (new architecture, new public interface, migration of the Dallas agent), so each phase ends with tests, a commit and a check-in.

## Terms

- **Template** = one set of agent tools + contracts + trust rules + UI pages for a hazard. There are two: **winter** (today's Dallas tools) and **hurricane** (to build).
- **Pack** = one county's data for one hazard: processed tables + sourced facts (what Dallas has in `backend/dallas/` + `processed/dallas/` today).
- **County agent** = template + pack. Adding a county adds a pack, not code. Harris, Miami-Dade and Lee all run the same hurricane tools with different packs.

## Goal

One deployed link with:

| Agent | Hazard | County | State at demo |
|---|---|---|---|
| Dallas winter storm | winter | Dallas County, TX (48113) | live (exists today) |
| Harris hurricane | hurricane | Harris County, TX (48201) | live |
| Miami-Dade hurricane | hurricane | Miami-Dade County, FL (12086) | live |
| Lee hurricane | hurricane | Lee County, FL (12071) | live |
| 4th county | hurricane | Palm Beach FL (12099) or Charleston SC (45019), see open questions | **research demo**: the research agent drafts a pack live; it is not published |

Harris, Miami-Dade and Lee are the top 3 by FEMA NRI hurricane risk (HRCN_RISKS 100 / 100 / 99.9). All three have open-data portals and recent storms to check against: Harvey and Beryl (Harris), Irma (Miami-Dade), Ian (Lee).

## Current state (2026-10-05)

| Piece | State |
|---|---|
| Dallas winter agent | Live on Cloud Run: ADK + trust layer, real data, UI pages |
| Hurricane agent | **Stub only**: fictional storm, 4 Florida counties, plain loop |
| Hurricane national data | Staged in `raw/national/` (NOAA events, ATCF 2014–2025, FEMA NSS + PA, tree canopy, MCC, gazetteer) |
| Hurricane impact model | Real retrain pipeline built; Vertex smoke job running; full run pending. Inference pipeline still uses placeholder inputs |
| Research agent | Does not exist. Designed in `hurricane-extension.md` §4 |

## Architecture

```
           ┌──────────────── one Cloud Run service, one link ────────────────┐
 browser → │ React UI: landing (agent cards) → per-agent pages               │
           │ FastAPI: /api/agents, /api/agents/{id}/overview|chat|health     │
           │ Agent registry ── hazard template (tools + contracts + trust     │
           │                    profile + instruction) × county pack (data)  │
           └──────────────────────────────┬──────────────────────────────────┘
                                          │ reads approved packs
 gs://…/processed/packs/{hazard}/{fips}/   ▼
   pack.json (facts with sources) · storms.json · assets.json · geo.geojson · review.json
                                          ▲ publishes after human approval
 Research agent (Vertex / Cloud Run job) ─┘ drafts → processed/packs_draft/{hazard}/{fips}/
```

**Key decisions**

| Decision | Why | Rejected |
|---|---|---|
| "Creating a county agent" = publishing an approved **pack** for an existing **hazard template**; no new code per county | Dallas showed the agent code is reusable and the work is data + review | Generating agent code per county (unreviewable, unmaintainable) |
| One service, agent chosen by URL (`/api/agents/{id}/…`) | One link, one deploy, packs loaded on demand | One Cloud Run service per county (cost, N deploys, N links) |
| Research runs as an offline job, never inside chat | Research output is candidate facts; the trust layer checks answers against tools, not tools against reality (5 bad sources in the Dallas build alone) | Live research in chat |
| Human approval gate between draft and published pack | Same reason | Auto-publish when triangulation passes |
| Hazard template owns tools, contracts, trust profile, instruction, UI page set | Winter and hurricane genuinely differ (weather inputs, sanding vs evacuee sheltering/staging) | One generic "disaster" tool set (too vague to plan with) |

**Pack schema** (both hazards share the shape; contents differ):

```
pack.json     county, fips, hazard, status (draft|approved|live), built_utc, reviewer,
              facts: [{id, metric, value, unit, storm_id?, quote, source, source_url, retrieved, verified_by: [...]}],
              gaps: [{metric, reason}]
storms.json   past events with weather/track, outages (EAGLE-I), 311 or equivalent surges, NOAA, FEMA
assets.json   shelters (local + FEMA NSS), resources, department staff
geo.geojson   sub-county units for maps (council districts / ZIP / census tracts)
review.json   per fact: verified (2+ sources) | single-source | conflicting, with notes; reviewer decision
```

`processed/packs/index.json` lists every pack with hazard, county, status and URL slug. The registry reads it at startup.

## Phases

Each phase has a test gate and ends with a commit and check-in. Estimates are working days.

### Phase 0: finish Dallas (this week, before anything below)
Dallas step 6 (docs pass): README, run/redeploy steps, demo script, eval results. No architecture change.
**Gate:** README matches the deployed app; demo script runs end to end on the live link.

### Phase 1: generalize Dallas into a template + pack (1–2 days)
1. Define the pack schema (pydantic) and `processed/packs/index.json`.
2. Convert Dallas: `backend/dallas/*` output → `processed/packs/winter/48113/`. `sources.py` facts become `pack.json` facts (each already has a source).
3. Winter template: `agent/templates/winter/{tools,contracts,instruction}.py` reading a pack by fips (from today's `dallas_tools.py`, `dallas_contracts.py`). Trust profile per template (today's `trust.DALLAS` becomes `trust.WINTER`).
4. Agent registry: `agent/registry.py` builds `(template, pack) → ADK agent` lazily and caches it.

**Gate:** all Dallas tests pass unchanged against the pack-backed template; Dallas planted-error eval still 23/23 with 0 false alarms.

### Phase 2: hurricane template (2–3 days; impact tool depends on the retrain)
Tools (national data + the pack):

| Tool | Data |
|---|---|
| `get_storm_alert` | Live NHC advisory if one threatens the county, else **replay** of a past advisory from ATCF a-decks (labeled "replay"), else a labeled scenario |
| `find_similar_storms` | HURDAT2 tracks that passed within 150 nm + their EAGLE-I peak outages for this county |
| `estimate_impact` | Retrained quantile XGBoost: low/median/high % customers out, from the same features as training. **Requires** the real retrain + the inference-feature fix (`models/pipeline.py` placeholders) |
| `get_storm_impacts` | Past storm detail: NOAA events/narratives, FEMA PA by category, outages |
| `query_assets` | FEMA NSS shelters in the county (lat/lon swaps fixed) + pack's local shelters, staging sites, staff |
| `plan_response` / `diff_plans` | Shelter beds vs demand range; staging resources from the pack; what-ifs (shelter closed, fewer crews) |
| `get_enso_context`, `retrieve_guidance` | As Dallas; hurricane guidance from NWS/NHC |

Trust: today's `trust.HURRICANE` profile, updated for the real tools (version key = advisory id; lead-time rule from NHC 48 h).
**Gate:** contract tests per tool, a hurricane planted-error eval with the Dallas cases (unit, wrong county/sub-unit, invented shelter, bare median, certainty), live Gemini run on 6 questions per county.

### Phase 3: three hurricane packs, assembled by hand with the research checklist (3–4 days, ~1 per county)
For each of Harris, Miami-Dade, Lee:
1. National baseline automatically (storms, outages, NOAA, FEMA, NSS, canopy, NRI/SVI).
2. Local research following the checklist the research agent will automate: open-data catalog search, 311 dataset + storm windows, ArcGIS/Legistar after-action reports, budget-book FTEs, shelter/evacuation plans, staging sites.
3. Triangulate key numbers (2 sources or a published figure), record gaps, write `review.json`.
4. Taya reviews → publish.

These three packs are the **gold set** the research agent is evaluated against in Phase 5.
**Gate:** each pack passes schema validation; every fact has source + quote; `review.json` signed off.

### Phase 4: multi-agent app + UI, one link (2 days)
**API**
- `GET /api/agents` → cards: id, name, hazard, county, status, last updated.
- `GET /api/agents/{id}/overview`, `POST /api/agents/{id}/chat`, `GET /api/agents/{id}/health`.
- `GET /api/research/{run_id}` → draft pack + review report (read-only, for the demo).
- Old routes (`/api/overview`, `/api/chat`) keep working for Dallas during migration, then removed.

**UI** (same Tailwind components; no new framework)
- **Landing page:** one card per agent (county, hazard, live/draft badge, last storm in data), plus a "Research a new county" card.
- **Hash routing** (`#/agents/harris-hurricane/overview`): shareable deep links without adding a router dependency. The current app switches pages with state only.
- **Per-agent pages by hazard template:**
  - Winter: today's Dallas Overview + Planner, parameterized by pack.
  - Hurricane: Storm Overview (advisory/replay header, track + cone on map, county impact range, similar storms), Shelters & Staging (NSS + local shelters on map, demand vs beds, what-ifs), History (past storms, FEMA aid, outages).
- **Ask AI panel** scoped to the open agent (sends `agent_id`; examples per hazard; header shows which county agent is answering).
- **Research page (demo):** pick county → run status → draft pack with each fact's source and verification state (verified / single-source / conflicting) and the gaps list. Clearly labeled "draft, not published".
- Fixes from issue #4 (hide suggested questions after the first message) folded in here.

**Gate:** headless click-through of every agent's pages with no browser errors; chat on each agent passes trust checks; deep links load directly.

### Phase 5: research agent (separate session, 3–5 days)
**Superseded by `docs/research-agent-plan.md` (2026-10-05).**
- ADK agent running as a Vertex AI / Cloud Run job, not in chat. Tools: Socrata catalog + SoQL, ArcGIS Hub search, Legistar search, fetch + PDF text, Gemini with Google Search grounding for discovery, structured extraction to the pack schema (pydantic), and triangulation rules.
- Output: draft pack + review report in `processed/packs_draft/…`, never auto-published.
- **Evaluation against the gold set:** run the agent on Harris, Miami-Dade, Lee, compare with the hand packs. Fact recall, precision, false-verification rate (a fact marked verified that is wrong). Bar for the demo: no false verifications on key numbers.
- Demo: run on the 4th county live or from a recorded run, show the review report.

### Phase 6: deploy, evals, docs (1 day)
One Cloud Run service (same link as today), image with all templates; packs from GCS. README + architecture diagram + demo script for 5 agents + research page. Planted-error evals for both hazards, live pass rates per agent.

## Dependencies and order

```
Phase 0 ──► Phase 1 ──► Phase 2 ──► Phase 3 ──► Phase 4 ──► Phase 6
                          ▲            │                       ▲
   retrain (Vertex) ──────┘            └── gold set ──► Phase 5 ┘
   + inference-feature fix
```

The retrain is the critical path for `estimate_impact`. If it isn't ready, Phase 2 ships with history-based ranges (like Dallas's `estimate_demand`) and the model is swapped in later behind the same contract.

## Risks

| Risk | Mitigation |
|---|---|
| Retrained model is weak (few storms, approximate wind field) | Report held-out-storm metrics honestly; fall back to history ranges; never present model output without its range |
| Local data quality varies by county | Packs record gaps explicitly; UI shows "not available" rather than hiding the gap |
| Review time per county (1–2 h) | Review report pre-sorts facts by verification state; only single-source/conflicting need attention |
| Research agent marks wrong facts as verified | Gold-set eval with false-verification rate as the gating metric |
| Cost of Gemini calls in research jobs | Jobs are per request, capped tokens per run; logged |
| Single service gets heavier with each pack | Packs load lazily; agents cached; max instances capped |

## Open questions for Taya

1. **Deadline** for the demo: decides whether Phase 5 is a live research run or a recorded one.
2. **4th county:** Palm Beach (FL, 4th by risk, rich portal) or Charleston (SC, different state)?
3. **Hurricane staging data:** counties rarely publish truck/crew counts. OK for hurricane packs to focus on shelters, evacuee hosting and outages, with staging resources only where documented?
4. **Kanupriya:** does she own the inference-feature fix in `models/pipeline.py` and the model swap, or should that be done here?
