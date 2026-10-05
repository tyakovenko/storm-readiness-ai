# Research judge: fixed checks → entailment → independent corroboration

**Status:** Accepted 2026-10-05 (thresholds open, see `docs/research-agent-plan.md` §Judge inputs)

## Context
The researcher (Gemini Flash + Google Search) pulls facts out of web pages and PDFs. Known ways real sources went wrong in the Dallas and hurricane builds:
- FEMA PA lists the applicant's county, not where the damage was
- the Dallas payroll registry is citywide totals, not one row per employee
- ASOS gauges over-read precipitation in sleet
- a number that only appears in a source name was used as evidence ("FOX 4")
- the right number is quoted but for the wrong storm or year

A judge that is the same model with the same context shares the researcher's blind spots. It reads the same page the same way and agrees.

## Decision
The judge differs from the researcher in **what evidence it sees**, not only in which model it runs. Three layers, cheapest first; a fact that fails one layer doesn't go to the next.

1. **Fixed checks** (`research/verify.py`, no LLM). Refetch `source_url` itself, ignoring any text the researcher cached. Then check: the quote is in the page (after normalizing case, whitespace, quote marks and dashes); the value is in the quote (number normalization reused from `agent/trust.py`); the unit is near the quote; a jurisdiction name is on the page; if the fact names a storm, its name or year is on the page. Any failure → `unsupported`. A check that can't run (fetch error, unsupported type) → `unchecked`, never a pass.
2. **Entailment** (Gemini Pro, thinking on, JSON output). Input is only the source passage around the quote plus the claim (metric, value, unit, qualifier, county, storm, as_of). It never sees the researcher's reasoning. Question: does this passage support this exact claim? Answer is a label (supports / contradicts / wrong scope / wrong time / not enough) with a reason. This catches the scope and time errors listed above.
3. **Independent corroboration** (Gemini Pro + Google Search, key metrics only). The judge searches on its own, without seeing the researcher's URLs. A second source counts only if it is independent: a different publisher, and not a syndicated copy (text-similarity check). Each source it finds goes through layer 1 too.

Verdict: 2 independent supporting sources → `verified`; 1 → `single_source`; a credible source with a different value → `conflicting`.

The judge is measured, not trusted:
- **planted errors**: wrong facts injected into a correct draft, one per failure kind above
- **gold set**: hand-labeled facts for Harris, Miami-Dade and Lee
- **gating metric**: false-verification rate (wrong fact marked verified) = 0 on key metrics

## Rejected
- **One LLM judge pass** (same model as the researcher, reading the researcher's transcript): agrees with the researcher for the same reasons the researcher was wrong.
- **LLM-only quote check:** whether a quote appears on a page has an exact answer. An LLM can say "found" for a paraphrase.
- **Reusing `agent/judge.py`:** that judge grades whether a chat answer is actionable. It checks against nothing.

## Consequences
- More cost per fact: one refetch, one Pro call, and for key metrics a search plus up to 3 more fetches. Capped per run (plan §Cost).
- Pages behind JS rendering or bot blocks come back `unchecked`, which means more human review. That is preferred over passing them.
- Thresholds (key metrics, value tolerance, source independence, staleness) are policy and live in one config (`research/policy.py`), not in the code.
