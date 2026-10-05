"""Shared ADK + trust-layer runner for every hazard template (winter/Dallas, hurricane).

    question -> ADK agent calls the template's tools -> answer
             -> trust.run_checks(profile, catalog) -> pass: show
             -> fail: feedback in the same session, one regenerate -> fail again: block

Trust runs around the Runner, not in callbacks: the checks need the whole turn's tool outputs
and must be able to ask for a rewrite (decision 2026-10-04). Response shape matches
loop.run_agent so the UI is the same for every agent.
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid

from google.adk.events import Event
from google.adk.runners import InMemoryRunner
from google.genai import types

from . import judge as judge_mod
from . import trust
from .llm import ConfigError

log = logging.getLogger(__name__)
APP = "storm_readiness"
TRUST_PREFIX = "[trust-layer]"


def model_from_name(name: str | None, mock_factory):
    """LLM_MODEL: "mock" | a Gemini id (Vertex, via ADC) | a LiteLLM string with "/" (e.g. anthropic/...).
    mock_factory() builds the template's scripted BaseLlm for "mock"."""
    name = (name or os.environ.get("LLM_MODEL", "")).strip()
    if not name:
        raise ConfigError("LLM_MODEL is not set: use 'mock', a Gemini id such as gemini-3.8-flash, "
                          "or a LiteLLM model string.")
    if name == "mock":
        log.warning("LLM_MODEL=mock: scripted demo model, not a real LLM")
        return mock_factory()
    if "/" in name:
        from google.adk.models.lite_llm import LiteLlm
        return LiteLlm(model=name)
    if os.environ.get("GOOGLE_GENAI_USE_VERTEXAI", "").upper() not in {"TRUE", "1"} \
            or not os.environ.get("GOOGLE_CLOUD_PROJECT"):
        raise ConfigError(f"{name} needs GOOGLE_GENAI_USE_VERTEXAI=TRUE and GOOGLE_CLOUD_PROJECT "
                          "(and GOOGLE_CLOUD_LOCATION=global for gemini-3.8-flash).")
    return name


def check_model(model) -> None:
    """Fail at startup if a real Gemini model can't be called (no deferred validation)."""
    if not isinstance(model, str):
        return
    from google import genai
    # Keep a reference: a temporary Client can be collected mid-call, closing its HTTP client
    # ("Cannot send a request, as the client has been closed" - startup crash on Cloud Run).
    client = genai.Client()
    try:
        client.models.generate_content(model=model, contents="Reply with: ok")
    except Exception as e:
        raise ConfigError(f"Gemini model {model} is not callable "
                          f"(location={os.environ.get('GOOGLE_CLOUD_LOCATION')}): {e}") from e


def model_label(model) -> str:
    return model if isinstance(model, str) else getattr(model, "model", type(model).__name__)


async def _attempt(runner, session_id: str, text: str) -> tuple[str, list[dict], list[dict]]:
    calls, outputs, answer = [], [], ""
    async for ev in runner.run_async(user_id="user", session_id=session_id,
                                     new_message=types.Content(role="user", parts=[types.Part(text=text)])):
        for p in (ev.content.parts if ev.content else None) or []:
            if p.function_call:
                calls.append({"name": p.function_call.name, "arguments": dict(p.function_call.args or {})})
            elif p.function_response:
                outputs.append(dict(p.function_response.response or {}))
            elif p.text and not p.thought:
                answer = p.text if ev.is_final_response() else answer
    return answer, calls, outputs


async def _run(agent, question: str, history: list[dict], profile, catalog: list[dict]):
    runner = InMemoryRunner(agent=agent, app_name=APP)
    session = await runner.session_service.create_session(app_name=APP, user_id="user")
    for h in history:  # earlier turns from the UI, replayed as session events
        role = "user" if h["role"] == "user" else "model"
        await runner.session_service.append_event(session, Event(
            invocation_id=str(uuid.uuid4()), author="user" if role == "user" else agent.name,
            content=types.Content(role=role, parts=[types.Part(text=h["content"])])))

    all_calls, outputs, attempts = [], [], []
    status, message = "blocked", question
    for attempt in range(2):
        text, calls, outs = await _attempt(runner, session.id, message)
        all_calls += calls
        outputs += outs
        names_all = [c["name"] for c in all_calls]
        names_now = [c["name"] for c in calls] or names_all
        checks = trust.run_checks(text, names_all, outputs, question, catalog, order_calls=names_now,
                                  profile=profile)
        attempts.append({"text": text, "checks": trust.to_dicts(checks)})
        failed = [c for c in checks if c.blocking and c.passed is False]
        if not failed:
            status = "passed" if attempt == 0 else "regenerated"
            break
        message = (f"{TRUST_PREFIX} Your answer was blocked: " + "; ".join(c.detail for c in failed)
                   + ". Rewrite it to fix these. Use only numbers from tool results; call tools again if you need to "
                   f"(if the tool order was wrong, call {profile.first_tool} first, then re-run the other tools). "
                   "Reply with the corrected answer only: users never see this feedback.")
    return attempts, all_calls, outputs, status


def run_with_trust(question: str, history: list[dict], agent, judge, profile, catalog: list[dict]) -> dict:
    attempts, all_calls, outputs, status = asyncio.run(_run(agent, question, history, profile, catalog))
    final = (judge_mod.grade_or_report(judge, question, attempts[-1]["text"]) if status != "blocked"
             else trust.Check(judge_mod.NAME, None, False, "Not graded: answer was blocked"))
    attempts[-1]["checks"] += trust.to_dicts([final])
    sources = set()
    for o in outputs:
        if isinstance(o.get("source"), str):
            sources.add(o["source"])
        sources.update(s for s in o.get("sources", []) if isinstance(s, str))
    return {
        "status": status,
        "answer": attempts[-1]["text"] if status != "blocked" else None,
        "checks": attempts[-1]["checks"],
        "attempts": attempts,
        "tool_calls": all_calls,
        "sources": sorted(sources),
        "why": [],
        "model": model_label(agent.model),
    }
