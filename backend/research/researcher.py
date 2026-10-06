"""The researcher: an ADK agent (Gemini Flash + Google Search + research tools) that drafts a county pack.

Runs offline as a job, never in chat (ADR research-offline-human-gate). Output is a DraftPack for the judge.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone

from google.adk.agents import LlmAgent
from google.adk.models.llm_response import LlmResponse
from google.adk.runners import InMemoryRunner
from google.adk.tools import google_search
from google.genai import types

from research import policy
from research.schema import DraftPack, Gap, Target
from research.tools import ResearchSession

log = logging.getLogger(__name__)
APP = "storm_research"

INSTRUCTION = """You research {county}, {state} (FIPS {fips}) for its {hazard} readiness pack. Emergency \
managers will plan with these facts, so every fact must come from a source you read, cited exactly.

Find, for {jurisdiction}:
{gaps}

Metrics you may submit (name: unit; key metrics need the strongest sources):
{metrics}

Storms in this county's record (use the id as storm_id for a storm-specific fact):
{storms}

How to work:
1. Search (google_search, arcgis_search{portal_hint}) for official sources first: county and city \
emergency management, after-action reports, shelter plans, budget books, council or commission items. \
News is second choice.
2. read_source every page you want to cite. Numbers on the page are tagged like ⟦N17⟧1,314.
3. submit_fact for each fact: give the number's tag as value_ref ("N17"). NEVER type a number yourself, never \
add, subtract, round or convert. If no tag sits on the number you need, that number can't be cited.
4. One fact per number. Capacity is not occupancy; a figure for another storm or year is a different fact. \
A city's own figure (e.g. city-run shelters) is submitted with place set to that city; leave place empty \
only for county-wide figures. Always name the subject: the organization the number belongs to, as the \
source names it. Pick the metric whose definition fits that subject (utility workers are utility_workers, \
never staff_count). Skip figures that aren't about storm readiness or response. If submit_fact refuses, read the reason and fix the citation, \
or move on.
5. For each item above you could not source, report_gap with where you looked.
Stop when every item is either submitted or reported as a gap. End with a one-line summary."""


def _instruction(target: Target, gaps: list[Gap], portals: dict) -> str:
    metrics = "\n".join(f"- {name}: {m.unit}{' (key)' if m.key else ''} - {m.definition}"
                        for name, m in policy.METRICS.items())
    storms = "\n".join(f"- {s.id}: {s.name} {s.year}" for s in target.storms) or "- none"
    wanted = "\n".join(f"- {g.metric}" for g in gaps) or "- shelters and capacities, staffing, staging, after-action figures"
    juris = ", ".join(target.jurisdiction_names())
    hint = f", legistar_search (clients: {', '.join(portals['legistar'])})" if portals.get("legistar") else ""
    return INSTRUCTION.format(county=target.county, state=target.state, fips=target.fips, hazard=target.hazard,
                              jurisdiction=juris, gaps=wanted, metrics=metrics, storms=storms, portal_hint=hint)


class CallCap:
    """before_model_callback: counts model calls; at the cap it answers in place of the model, which ends
    the run with a partial draft. The cap is recorded in the run log, never silent."""

    def __init__(self, cap: int):
        self.cap, self.count, self.hit = cap, 0, False

    def __call__(self, callback_context, llm_request):
        self.count += 1
        if self.count > self.cap:
            self.hit = True
            log.error("research run hit the model-call cap (%d); draft is partial", self.cap)
            return LlmResponse(content=types.Content(role="model", parts=[types.Part(
                text=f"Stopped: model-call cap of {self.cap} reached. Draft is partial.")]))
        return None


# ADK doesn't retry 429/503 by default: one quota spike killed a cloud run (2026-10-05). 5 tries, 5 s -> 60 s.
HARD_STOP_GRACE_S = 120
# Per-call timeout (ms): with only the client retry options, one call still hung until the run's hard stop
# (Miami-Dade run 2026-10-06). A timed-out call is retried like a 429.
CALL_TIMEOUT_MS = 120_000
RETRY = types.HttpRetryOptions(attempts=5, initial_delay=5, max_delay=60, exp_base=2,
                               http_status_codes=[408, 429, 503, 504])


def build_agent(session: ResearchSession, gaps: list[Gap], model: str, cap: CallCap) -> LlmAgent:
    from google.adk.models import Gemini
    return LlmAgent(name="county_researcher", model=Gemini(model=model, retry_options=RETRY),
                    instruction=_instruction(session.target, gaps, session.portals),
                    tools=[google_search, *session.tools()], before_model_callback=cap,
                    generate_content_config=types.GenerateContentConfig(
                        http_options=types.HttpOptions(timeout=CALL_TIMEOUT_MS)))


async def run_research(target: Target, gaps: list[Gap], portals: dict, model: str,
                       max_calls: int = policy.MAX_GEMINI_CALLS, session: ResearchSession | None = None,
                       max_seconds: int = policy.MAX_RUN_SECONDS) -> DraftPack:
    session = session or ResearchSession(target, portals)
    cap = CallCap(max_calls)
    agent = build_agent(session, gaps, model, cap)
    runner = InMemoryRunner(agent=agent, app_name=APP)
    adk_session = await runner.session_service.create_session(app_name=APP, user_id="research")
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    t0, summary, grounding = time.time(), "", []
    msg = types.Content(role="user", parts=[types.Part(text=f"Research {target.county} now.")])
    time_cap_hit, run_error = False, None

    async def consume():
        nonlocal summary, time_cap_hit
        async for ev in runner.run_async(user_id="research", session_id=adk_session.id, new_message=msg):
            if time.time() - t0 > max_seconds:
                # Stop here rather than be killed from outside: a killed run loses every fact found so far.
                time_cap_hit = True
                log.error("research run hit the time cap (%d s); draft is partial", max_seconds)
                break
            gm = getattr(ev, "grounding_metadata", None)
            if gm and gm.grounding_chunks:
                grounding.extend(c.web.uri for c in gm.grounding_chunks if c.web)
            if ev.is_final_response() and ev.content and ev.content.parts:
                summary = "".join(p.text or "" for p in ev.content.parts)

    try:
        # The in-loop check only runs between events; a hung model or tool call never yields one.
        # wait_for is the hard stop (grace for the call in flight).
        await asyncio.wait_for(consume(), timeout=max_seconds + HARD_STOP_GRACE_S)
    except asyncio.TimeoutError:
        time_cap_hit = True
        run_error = f"hard stop after {max_seconds + HARD_STOP_GRACE_S} s (a call hung)"
        log.error("research run: %s; saving a partial draft", run_error)
    except Exception as e:  # model/API failure after retries: keep what was found, mark the draft partial
        run_error = f"{type(e).__name__}: {str(e)[:300]}"
        log.error("research run failed; saving a partial draft: %s", run_error)
    run_log = {"model_calls": cap.count, "model_call_cap": max_calls, "cap_hit": cap.hit,
               "partial": cap.hit or time_cap_hit or run_error is not None,  # items not reached are missing
               "time_cap_hit": time_cap_hit, "time_cap_s": max_seconds, "run_error": run_error,
               "fetches": session.fetch.count, "fetch_cap": session.fetch.max_fetches,
               "tool_calls": dict(session.calls), "rejected_submissions": session.rejected,
               "fetch_errors": {u: p.error for u, p in session.fetch.cache.items() if p.error},
               "search_results_seen": len(grounding), "seconds": round(time.time() - t0, 1), "summary": summary}
    return DraftPack(target=target, run_id=run_id, researcher_model=model, facts=session.facts,
                     gaps=session.gaps, run_log=run_log)
