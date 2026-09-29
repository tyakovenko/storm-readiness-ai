# Branch `c/agent-data-contract`

Builds on `c/agent-trust-layer` (Julie's agent + trust layer + React UI). Still stub data.

## What this branch adds

| Area | Change |
|---|---|
| **Data contract** | `backend/agent/contracts.py`: a pydantic schema per tool, checked on every tool call. Fields come from the Data Strategy doc (EAGLE-I/MCC, NRI/SVI, ONI, FEMA ESF #6 shelters). Human-readable version: [`data-contract.md`](data-contract.md) |
| **Trust check 3: confidence fits lead time** | Deterministic and blocking. When lead time > 48 h or scenario spread > 60 nm: no certainty words ("definitely", "will lose power"), and a county's median % must come with its low–high range. Thresholds are constants in `trust.py`, to be calibrated from approve/reject logs |
| **Trust check 4: actionable (LLM judge)** | `backend/agent/judge.py`. Set `JUDGE_MODEL` to turn it on. It never blocks, only flags for the reviewer, and its output is labeled "unvalidated" until we score it against human labels. Without `JUDGE_MODEL`, it reports "not configured" instead of a silent pass |
| **Stale-advisory check** | Part of `required_steps`: blocks answers that mix tool outputs from different advisory numbers |
| **`diff_plans` tool** | What-ifs now report what changed compared with the full plan (truckloads per county, unmet need, beds, shortfall) |
| **`get_enso_context` tool** | ONI phase and strength. Works for both the base design and the El Niño variant |
| **Shelters** | Now use the FEMA ESF #6 shape (evacuation vs post-impact capacity, generator, pets, surge zone). Bed counts use `evacuation_capacity` |
| **Tests** | `backend/tests/`, 24 tests, mock mode only, no key needed: `cd backend && .venv/bin/pytest -q` |
| **UI** | Second trust demo ("overconfident") and a judge on/off badge |

Bug fixed: a negative change like "-2 truckloads" was flagged as a made-up number because the number regex drops the sign.

## Open questions: answers where the code decides

**How should `tools.py` match the data team's output?** Each side builds to a contract. The data team keeps full control of raw formats and pipelines; only the *engine output* has to match `contracts.py`, which already uses their fields (FIPS strings, low/median/high, `source` on everything). If a field is wrong for their data, we change the contract together: edit `contracts.py` and `data-contract.md` in one PR, and the tests show what broke. That's cheaper than either side guessing.

**Base design or the El Niño variant?** The agent code doesn't need this decided yet. `solve_staging` keeps the same interface either way (its `method` field reports optimizer vs highest-need-first), and `get_enso_context` / `find_analogs` are optional tools. The Data Strategy already treats ONI as a model *feature* with a with/without test (action item 5), which is the El Niño-as-input approach. The decision matters for Workstream B's scope and whether analogs need real data, not for the agent.

**Plain loop or Google ADK?** Recommendation: **stay on the plain loop** for the hackathon.
- It works now, and it's provider-agnostic through LiteLLM (Claude, Gemini, mock).
- The trust layer sits directly in the loop: regenerate once, then block. In ADK it would have to be re-done as callbacks, a day of rework for no user-visible change.
- The tools are plain Python functions with JSON schemas, so switching to ADK later is contained (`loop.py` + `llm.py`).
- Rejected: ADK now, because it adds a Gemini-leaning dependency and we'd lose the mock mode, the only free way for the team to demo.

**Who builds the last 2 trust checks?** First versions are on this branch. Still open: (a) calibrate the 48 h / 60 nm thresholds, (b) a small human-labeled set, about 30 answers, to validate the judge before its verdicts count. (b) needs someone other than the judge's author to label.

**Which LLM for the final demo?** It's a config line (`LLM_MODEL`, `JUDGE_MODEL` in `.env`). Tested on this branch: Claude Haiku 4.5 (cheap and fast) for both agent and judge. For the final demo, compare 2 models on trust-check pass rate. The proposal already promises a model comparison, so the eval harness doubles as that.

## Open questions for the meeting (not code)

- When will the first real data piece be ready, and in what format? Suggested order, easiest swap first: FEMA shelters → `query_assets`, then historical NHC advisory → `get_advisory`, then the impact model → `predict_impact`.
- Who pays for the LLM? Should we ask the sponsor for credits?
- Who owns the UI from here (map, the three user views, approve/reject)?
- Data Strategy action items 1–4 (geography, years, target definition, features): the target definition changes the contract (see `data-contract.md`).

## Live Haiku run (2026-09-29)

- The trust layer caught real mistakes: Haiku computed a beds-lost number itself (900) and rewrote a 0.82 similarity as "82". Both were blocked, and the regenerate passed.
- Haiku guessed a wrong FIPS code for Levy. `predict_impact` now returns an error listing the known codes instead of an empty list.
- Regenerated answers opened with "You're right, let me recalculate". The feedback now tells the model users never see it.
- The judge is strict: it marks informational answers (El Niño context, a single number) as not actionable. That's a rubric call to settle when we validate it.
- Haiku writes `**bold**` even when told not to, so the UI renders bold (no markdown library).

## Known gaps

- Mock mode is keyword-scripted: it only shows the plumbing, not agent quality.
- The confidence check matches county names exactly ("Levy County"). If the model writes just "Levy", a missing range can slip through.
- The judge isn't validated. Treat its verdicts as a demo of the mechanism.
- No replay clock yet. Everything is one fixed stub advisory.
