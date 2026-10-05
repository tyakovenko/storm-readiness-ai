"""FastAPI server for the agent demo.

  GET  /api/health   -> which LLM is configured
  GET  /api/overview -> tool outputs for the dashboard screens (no LLM)
  POST /api/chat     -> run the agent + trust layer on one question
  GET  /api/impact, /api/storm, /api/staging -> single-tool reads (no LLM)
  GET  /api/research, /api/research/{hazard}/{fips}/{run_id} -> research drafts + judge verdicts (read-only)

AGENT_DOMAIN picks what /api/chat runs:
  dallas (default)  -> ADK agent on the Dallas tools, trust layer around it (agent/dallas_adk.py)
  hurricane         -> the original plain loop on the stub hurricane tools (agent/loop.py)

Run from backend/:  uvicorn app:app --reload --port 8001
"""

import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from dotenv import find_dotenv, load_dotenv
from fastapi import FastAPI, HTTPException, Query, Request
from pydantic import BaseModel, Field

# Ensure backend directory is in sys.path
backend_dir = Path(__file__).parent.resolve()
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

load_dotenv(find_dotenv())  # finds the repo-root .env

from agent.judge import build_judge  # noqa: E402
from agent.llm import build_llm  # noqa: E402
from agent.loop import run_agent  # noqa: E402
from agent.tools import run_tool  # noqa: E402

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


DOMAIN = os.getenv("AGENT_DOMAIN", "dallas").strip().lower()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Fail loudly: a bad model config, missing key or missing data stops the server here.
    if DOMAIN in ("dallas", "multi"):
        from agent.dallas_adk import build_agent, build_model, check_model, model_label
        from dallas import store
        store.load_all()
        model = build_model()
        check_model(model)
        app.state.agent = build_agent(model)
        app.state.model_label = model_label(model)
        if DOMAIN == "multi":  # hurricane packs load lazily per agent; list them now so a bad index shows at startup
            from agent import registry
            log.info("agents: %s", [a["id"] for a in registry.list_agents()])
    elif DOMAIN == "hurricane":
        app.state.llm = build_llm()
        app.state.model_label = app.state.llm.model
    else:
        raise RuntimeError(f"AGENT_DOMAIN must be 'dallas', 'multi' or 'hurricane', got {DOMAIN!r}")
    app.state.judge = build_judge()
    yield


app = FastAPI(title="Storm Readiness AI agent", lifespan=lifespan)


class HistoryItem(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    history: list[HistoryItem] = Field(default_factory=list, max_length=20)


@app.get("/api/health")
def health(request: Request):
    model = request.app.state.model_label
    judge = request.app.state.judge
    return {"model": model, "mock": model == "mock", "judge": judge.model if judge else None, "domain": DOMAIN}


@app.get("/api/overview")
def overview(max_trucks: int | None = Query(None, ge=0),
             closed: list[str] = Query(default_factory=list)):
    """Read-only data for the dashboard screens: the same tools the agent calls, no LLM.

    run_tool validates every output against contracts.py, so the screens get
    exactly the shapes the data team builds to. max_trucks/closed are the
    Resource Planner's what-if inputs, passed straight to solve_staging.
    """
    if DOMAIN in ("dallas", "multi"):
        return dallas_overview(max_trucks, closed)
    staging_args = {}
    if max_trucks is not None:  # 0 trucks is a valid what-if
        staging_args["max_trucks"] = max_trucks
    if closed:
        staging_args["unavailable_sites"] = closed
    return {
        "advisory": run_tool("get_advisory", {}),
        "scenarios": run_tool("generate_scenarios", {}),
        "enso": run_tool("get_enso_context", {}),
        "impact": run_tool("predict_impact", {}),
        "staging": run_tool("solve_staging", staging_args),
        "assets": run_tool("query_assets", {}),
    }


def dallas_overview(trucks: int | None, closed: list[str]) -> dict:
    """Dashboard data for Dallas: the same tools the agent calls (contract-validated), no LLM.
    trucks/closed are the planner's what-if; diff is versus the default plan."""
    from agent.dallas_tools import run_tool as dallas_tool
    from dallas import store
    what_if = {k: v for k, v in (("trucks", trucks), ("unavailable_shelters", closed or None)) if v is not None}
    plan = dallas_tool("plan_response", what_if)
    if "error" in plan:  # e.g. an unknown shelter name in the query string
        raise HTTPException(status_code=422, detail=plan["error"])
    return {
        "domain": "dallas",
        "alert": dallas_tool("get_storm_alert", {}),
        "similar": dallas_tool("find_similar_storms", {}),
        "demand": dallas_tool("estimate_demand", {}),
        "plan": plan,
        "diff": dallas_tool("diff_plans", what_if) if what_if else None,
        "assets": dallas_tool("query_assets", {}),
        "enso": dallas_tool("get_enso_context", {}),
        "districts": store.districts(),
    }


@app.post("/api/chat")
def chat(body: ChatRequest, request: Request):
    history = [h.model_dump() for h in body.history]
    if DOMAIN in ("dallas", "multi"):
        from agent.dallas_adk import run_dallas_agent
        return run_dallas_agent(body.message, history, request.app.state.agent, request.app.state.judge)
    return run_agent(body.message, history, request.app.state.llm, request.app.state.judge)


# ---- multi-agent routes (AGENT_DOMAIN=multi): one link, one page set per agent ----

@app.get("/api/agents")
def agents():
    from agent import registry
    return registry.list_agents()


@app.get("/api/agents/{agent_id}/overview")
def agent_overview(agent_id: str, max_trucks: int | None = Query(None, ge=0),
                   closed: list[str] = Query(default_factory=list), include_surge: bool = False):
    from agent import registry
    if agent_id == registry.DALLAS["id"]:
        return dallas_overview(max_trucks, closed)
    try:
        return registry.hurricane_overview(agent_id, closed, include_surge)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Unknown agent {agent_id!r}")


@app.post("/api/agents/{agent_id}/chat")
def agent_chat(agent_id: str, body: ChatRequest, request: Request):
    from agent import registry
    try:
        return registry.chat(agent_id, body.message, [h.model_dump() for h in body.history], request.app.state.judge)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Unknown agent {agent_id!r}")


# ---- research drafts (read-only; publishing is research.publish, a human step) ----

@app.get("/api/research")
def research_runs():
    from research import store
    return store.list_drafts()


@app.get("/api/research/{hazard}/{fips}/{run_id}")
def research_run(hazard: str, fips: str, run_id: str):
    from research import store
    try:
        return store.dumps(store.get_draft(hazard, fips, run_id))
    except KeyError:
        raise HTTPException(status_code=404, detail=f"No research draft {hazard}/{fips}/{run_id}")
    except Exception as e:  # GCS unreachable or a corrupt draft: say so, don't report it as missing
        log.error("research draft %s/%s/%s unavailable: %s", hazard, fips, run_id, e)
        raise HTTPException(status_code=503, detail=f"Draft store unavailable: {e}")


@app.get("/api/impact")
def get_impact(fips: str | None = None):
    """Return county-level outage impact predictions matching frontend contract."""
    from agent.tools import predict_impact
    fips_list = [f.strip() for f in fips.split(",")] if fips else None
    return predict_impact(fips_list)


@app.get("/api/storm")
def get_storm():
    """Return active storm advisory, scenario track cone, and ENSO climate context."""
    from agent.tools import get_advisory, generate_scenarios, get_enso_context
    return {
        "advisory": get_advisory(),
        "scenarios": generate_scenarios(),
        "enso": get_enso_context(),
    }


@app.get("/api/staging")
def get_staging(max_trucks: int | None = None):
    """Return resource staging allocations and shelter bed demand."""
    from agent.tools import solve_staging
    return solve_staging(max_trucks=max_trucks)


# Production: serve the built React app from the same origin as /api (no CORS).
# Mounted last so /api routes win. Absent in dev, where Vite serves the UI.
STATIC_DIR = Path(os.getenv("STATIC_DIR", Path(__file__).resolve().parent.parent / "frontend" / "dist"))
if STATIC_DIR.is_dir():
    from fastapi.staticfiles import StaticFiles
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="ui")
