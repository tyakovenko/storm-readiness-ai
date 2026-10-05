# Storm Readiness AI — Presenter Notes
Companion to `storm-readiness-pitch.pptx`. One section per slide. Source: `docs/proposal.md`.

---

## Slide 1 — Storm Readiness AI

Opening framing: this is a decision-support system, not a forecast model. We don't predict where the hurricane goes — NHC already does that, well. We take their forecast and answer the question NHC doesn't: what does this storm mean for *this* county's power, shelters, and staging, and what should we pre-position, where, before the roads close.

If asked "what's the one-liner": *we turn a hurricane forecast into a staged, reviewed resource plan, and we re-run the whole thing every time a new advisory comes out.*

Team of 4, workstreams A (data/impact model), B (scenarios/optimization), C (agent/trust layer), D (app/accessibility/demo) — owners assigned post-mentor-session.

---

## Slide 2 — Forecasts say where the storm goes — not what it costs your county

Full quote to have ready: "staging decisions are made under forecast uncertainty. Over-staging wastes scarce inventory; under-staging leaves people without water, power or shelter capacity."

Three views of *the same underlying plan* — not three separate products. Emergency managers get the full plan and can ask what-if questions and approve/reject/edit. Organizations (food banks, school districts, utility community partners) get only what's relevant to them: their resource needs and which of their own facilities are at risk. Residents get plain-language, location-specific prep alerts generated straight from the approved plan — including Spanish.

Why it matters, in one line: large operators (utilities, big retailers) run 24/7 ops centers that already connect forecast to logistics. Most counties and community organizations don't have that — this system is meant to close that capability gap, not replace what already works well.

---

## Slide 3 — The pipeline mirrors the sponsor's own seven-stage design, stage for stage

This is a deliberate relevance play for judges: the sponsor brief's own suggested "Big Idea" architecture is Storm Detection → Forecast → Impact Prediction → Risk Assessment → Resource Analysis → Recommended Actions → Human Decision. Our architecture (§4, §6 of the proposal) matches it stage for stage — we're not reinterpreting the brief, we're building exactly what was asked for.

Mapping (full names, for Q&A — the slide uses one-word labels for readability):
1. Detect — live NHC advisory ingestion
2. Forecast — NHC track/intensity plus our generated scenarios
3. Impact — XGBoost impact model output per scenario
4. Risk — risk map, ranked counties/facilities
5. Resources — staging optimizer run
6. Actions — agent-drafted ops brief + resident alerts
7. Decision — human approve/reject/edit, logged

The demo flow the sponsor specified (*Select Storm → View Forecast → Analyze Impacts → Identify High-Risk Areas → Ask AI → Receive Recommendations*) maps directly onto this pipeline in our historical-replay mode — pick a past storm, and the pipeline runs stages 1–6 live in front of the judges, with the chat interface available at every step.

---

## Slide 4 — All 10 MVP-required components ship — three are the ones teams skip

The sponsor brief lists ten required MVP components. All ten are addressed in the MVP build — none are pushed to stretch or phase-2 (full table in appendix, §2.1 of the proposal). Seven are the "obvious" ones any competent team will hit: storm data ingestion, geographic visualization, trajectory/forecast, risk/impact analysis, at least one predictive capability, high-risk location identification, AI-generated recommendations.

The three on this slide are the ones easy to leave as an afterthought, and they're worth pausing on:
- **NL interface**: it has to be the *same* agent and tools as the automatic per-advisory run — a typed question becomes a real tool call and a re-solve, not a second, unverified free-text answer bolted on for the demo.
- **Why an area is high-risk**: pulled directly from the impact model's own feature importance, in plain language — e.g. "flagged for wind exposure and low canopy cover, not population alone." This is the AI Quality criterion ("findings include supporting evidence") satisfied directly, not asserted.
- **Sources panel**: names the specific NHC advisory, model version, and scenario set behind each number — this is the trust layer's groundedness check, surfaced to the user rather than just used internally.

---

## Slide 5 — Each job goes to the tool that's actually good at it

This is the core design philosophy, worth stating explicitly if there's time: physics/statistical forecasts handle the hazard, a trained and testable model handles impact, optimization handles allocation, the language model orchestrates, explains, and communicates. The one failure mode we will not accept is a language model inventing a quantity in a life-safety context — the architecture rules that out structurally, it doesn't try to catch it after the fact with a filter.

Detail per component:
- **Scenarios**: AR(1) models fit to NHC's own published historical forecast-error statistics (track and intensity), sampled to generate plausible storm scenarios, grouped into discrete storm states with transition probabilities. Works anywhere on the US coast without new data, since NHC's error stats cover the whole Atlantic basin.
- **Impact model**: XGBoost with quantile outputs (low/median/high per county), trained on peak share of customers without power, using EAGLE-I 2014–2024. Features: hazard (wind/rainfall per scenario), exposure (population, housing, customers served), vulnerability (CDC SVI, FEMA NRI), geography (coastal distance, canopy). Chosen because it has strong published results on this exact task, trains in minutes on CPU, and is directly interpretable via feature importance.
- **Optimizer**: a two-stage stochastic program (Bhattarai & Song, Clemson — full citation in appendix/references), re-solved in a rolling horizon on every advisory. First stage: where to pre-position, how much. Second stage: post-landfall distribution, penalized for unmet demand. We reuse their scenario-generation and shelter-demand assumption as-is (labeled as their assumption, since there's no public ground truth to improve it), and add a new outage-driven resource layer (generators, water/ice, cooling/charging centers) that the paper doesn't model.
- **Agent**: tool-calling loop (`get_advisory`, `generate_scenarios`, `predict_impact`, `solve_staging`, `diff_plans`, `query_assets`, `retrieve_guidance`). Model-agnostic — Gemini, Claude, or self-hosted Gemma swap via config, no code change.

---

## Slide 6 — Every AI output is checked against the models before a human ever sees it

This is the differentiator to lead with if a judge asks "what's actually novel here" — not the optimizer (that's a published method), not the impact model (solid but standard gradient-boosted trees) — it's that nothing the agent says reaches a person unfiltered.

Four checks, all before display:
1. **Numbers match the models** — deterministic, every quantity/place/facility in generated text must trace to a tool output field, or it's blocked and regenerated.
2. **Confidence fits lead time** — rule-based: no single-facility certainty claims four days out when scenarios still diverge widely.
3. **Required steps followed** — the agent's own tool-call sequence is checked: no plan without a current-advisory `solve_staging` call, no stale-advisory data, no skipped steps.
4. **Actionable** — LLM-as-judge against a written rubric, but the judge itself is validated against human-labeled samples first, and its scores are only shown once its agreement with humans is acceptable.

If asked how this compares to typical hackathon "RAG + disclaimer" approaches: this checks *quantities against tool outputs*, not just "does this sound plausible" — that's the structural difference.

---

## Slide 7 — Runs end-to-end on GCP's serverless tier — no BigQuery required

Left side is the simplified data flow: public data sources feed the three models (scenarios, impact, optimizer), which feed the agent + trust layer, which feeds the web app and review log.

Stack, if asked for specifics:
- Cloud Storage (Parquet) for data, trained model files, scenario cache — deliberately no BigQuery, because the data is small once aggregated to county/tract level.
- DuckDB, GeoPandas, xarray for processing — fast local SQL over Parquet, spatial joins, gridded forecast data.
- Cloud Run for the API/agent (FastAPI) and the web app, scale-to-zero.
- Cloud Scheduler triggers the pipeline every 6 hours (matching NHC's advisory cadence).
- Firestore for the review log — serverless, no database to manage.
- LLM is fully config-driven: Vertex AI (Gemini, or Claude via Vertex AI Model Garden) if proprietary models are approved, or vLLM + Gemma on Cloud Run GPU (1x NVIDIA L4, scales to zero) as the open-weights fallback. Startup check validates the configured LLM endpoint and tool-calling ability and fails loudly rather than degrading silently.

---

## Slide 8 — Every data source is public, grouped into three categories

All sources are public; access is still to be confirmed for each before we depend on it (noted explicitly in the proposal, §8).

Worth flagging if asked: EAGLE-I coverage varies by utility and year, so we normalize by covered customers rather than raw counts, and report coverage alongside results.

Considered and explicitly not used (have ready for Q&A, §8.1): paid weather-tile APIs (Weather.com, Tomorrow.io, OpenWeatherMap, Xweather) — redundant with free NHC/NWS fields; social media / public reports — no reliable public feed and doesn't fit the trust layer's groundedness requirement; emergency call data / response times — not public.

Phase-2 sources (NFHL, Overture roads/transit, HIFLD grid) are listed here to show the data path is already scoped, not to imply they're used in the MVP.

---

## Slide 9 — Backtested leave-one-storm-out against ten years of real storms

Leave-one-storm-out matters because outcomes *within* a storm are correlated (same storm, many counties) — training and testing on the same storm would overstate performance. This also avoids hindsight leakage: backtests use archived forecast advisories as inputs, never the best-track (after-the-fact) data.

Candidate storms: **Florence 2018** is the credibility step — we first reproduce Bhattarai & Song's own South Carolina case study configuration before generalizing. Then **Ian 2022**, **Helene 2024**, **Milton 2024** as held-out generalization tests, plus the remaining 2014–2024 landfalls used for impact-model training.

Comparison we'll report: the published paper's shelter-only plan vs. our plan with the outage-driven resource layer, both scored on unmet demand under the outages that actually happened.

---

## Slide 10 — Multi-hazard is scoped and data-ready — deliberately not built for the MVP

This preempts a predictable judge question: "the sponsor's Idea A example mentions flooding and road closures — why only power outages?" The answer is discipline, not a gap. Splitting effort across three or four untested impact models before Oct 5 would mean none of them are rigorously backtested. One model, backtested on ten years of real EAGLE-I data, beats three unproven ones on a hackathon timeline.

The data path is already identified, not invented on the spot: FEMA National Flood Hazard Layer for flood zones, OpenStreetMap/Overture for roads and transit, HIFLD for grid assets beyond EAGLE-I's county aggregate. The next model after the MVP — a road/transit/flood disruption predictor — would follow the exact same leave-one-storm-out backtest discipline as the power-outage model, and feed the same optimizer as an additional resource-need category. This is explicitly the first step of the phase-2 roadmap (§11 of the proposal), not a vague "future work" gesture.

---

## Slide 11 — Designed to keep running every hurricane season at near-zero idle cost

This slide answers "what happens to this after Oct 16" before anyone has to ask. Between storms, Cloud Scheduler just polls NHC every 6 hours and everything else — API, web app, GPU model service — scales to zero, so idle cost is close to nothing. When a storm actually threatens US land (watch/warning issued, or the forecast cone reaches shore), the full pipeline activates automatically on every advisory.

Public post-storm scorecard: after each storm, we publish predicted-vs-actual county outages and plan performance — this is a standing, public accountability mechanism, not a one-time hackathon claim. It's meant to be extended with predicted-vs-observed structural damage once the post-landfall reconciliation stretch layer (§4.6) is validated.

We're seeking one pilot partner — a county emergency management office or regional food bank — for the 2027 season, to validate staging recommendations against real operators rather than just backtests.

---

## Slide 12 — Four workstreams run in parallel toward an Oct 5 build freeze

Full timeline for reference:
- Sep 24–25: proposal + architecture; mentor session Sep 25; sponsor questions sent; GPU quota requested.
- Sep 26–29: data pipeline (EAGLE-I, HURDAT2, NHC archive, Census/SVI, facilities); scenario generator; baseline impact model; agent skeleton with stubbed tools; app shell.
- Sep 30–Oct 2: impact model backtest; optimizer (Florence reproduction + outage layer); agent wired to real tools; trust layer.
- Oct 3–5: end-to-end replay on a held-out storm; model comparison; accessibility pass; **build freeze Oct 5**.
- Oct 5–9: demo video (problem, users, why it matters, story of the build); **submit early, deadline Oct 9, 9:00 PM PT.**
- Oct 12–15: mentor prep. Oct 16: presentation.

Workstreams: A — data & impact model (ingestion, features, XGBoost, backtest; stretch: post-landfall reconciliation data). B — scenarios & optimization (forecast-error generator, Pyomo model, Florence reproduction, outage layer). C — agent & trust layer (tool definitions, agent loop, model config, trust checks, judge validation). D — app, accessibility & demo (three user views, four-tier map drill-down, NL chat, why/sources panel, review flow, accessibility, video/storyline).

A running decision log is kept throughout — feeds the "story behind the build" portion of the submission video.

---

## Slide 13 — Four sponsor decisions would materially change what we can build

These are 4 of the 9 open questions in the full proposal (§14) — the ones with the largest effect on scope. Full list, if asked: proprietary models; Vertex billing; overall GCP budget/cap; GPU quota; BigQuery; storm-type scope (Atlantic/Gulf only, acceptable?); data access (public-only, or sponsor/partner data available?); post-hackathon hosting; repository visibility (public vs. private-with-review-access).

Key point to land: the system is model-agnostic by design specifically *because* these answers were uncertain when we scoped it — Gemini/Claude on Vertex and self-hosted Gemma are both first-class paths, so a "no" on proprietary models or GPU quota changes which path we use, not whether the system works.

---

## Slide 14 — Appendix

Transition line: "the following slides are backup for Q&A — happy to go deeper on any of the compliance mapping, data sources, or architecture."

---

## Slide 15 — Full MVP compliance table

Full 10-row mapping from the sponsor's required MVP components to the exact proposal section addressing each one (§2.1). The three highlighted rows (natural-language interface, why-explanation, sources display) are the ones surfaced on the main deck as the easy-to-miss items — this table is here in case a judge wants to see the complete picture rather than just the three highlights.
