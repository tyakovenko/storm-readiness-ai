"""FastAPI server for the agent demo.

  GET  /api/health   -> which LLM is configured
  GET  /api/overview -> tool outputs for the dashboard screens (no LLM)
  POST /api/chat     -> run the agent + trust layer on one question
  GET  /api/impact, /api/storm, /api/staging -> single-tool reads (no LLM)

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


@app.get("/api/agents/{agent_id}/brief/{brief_type}")
def agent_brief(agent_id: str, brief_type: str, request: Request):
    from agent import registry
    
    if brief_type == "executive":
        prompt = "Draft an executive brief: 1-2 sentence risk summary, peak outage estimate, and high-level shelter readiness. Include ONI context."
    elif brief_type == "responder":
        prompt = "Draft a first responder brief: detailed shelter count (open vs closed), evacuation capacity, generators, pet status, and specific resource commodity needs (water, generators). List largest shelters."
    elif brief_type == "resident":
        prompt = "Draft a resident brief: clear evacuation advice, safety guidelines for power outages and generators, and general shelter guidelines."
    else:
        raise HTTPException(status_code=400, detail="Invalid brief type. Choose from: executive, responder, resident.")

    try:
        return registry.chat(agent_id, prompt, [], request.app.state.judge)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Unknown agent {agent_id!r}")


@app.post("/api/agents/{agent_id}/chat")
def agent_chat(agent_id: str, body: ChatRequest, request: Request):
    from agent import registry
    try:
        return registry.chat(agent_id, body.message, [h.model_dump() for h in body.history], request.app.state.judge)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Unknown agent {agent_id!r}")


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


# ---- Human-in-the-Loop plan approval routes (Gap 3) ----

class PlanCreateRequest(BaseModel):
    agent_id: str
    county: str
    inputs: dict = Field(default_factory=dict)
    allocations: dict = Field(default_factory=dict)
    author: str = "Emergency Manager"
    notes: str = ""


class PlanUpdateRequest(BaseModel):
    status: str | None = None
    approver: str | None = None
    notes: str | None = None
    inputs: dict | None = None
    allocations: dict | None = None


class PlanApproveRequest(BaseModel):
    approver: str = "Incident Commander"
    notes: str = "Approved for execution."


@app.get("/api/plans")
def list_plans(agent_id: str | None = Query(None), status: str | None = Query(None)):
    from agent import plan_store
    return plan_store.list_plans(agent_id=agent_id, status=status)


@app.post("/api/plans")
def create_plan_endpoint(body: PlanCreateRequest):
    from agent import plan_store
    return plan_store.create_plan(
        agent_id=body.agent_id,
        county=body.county,
        inputs=body.inputs,
        allocations=body.allocations,
        author=body.author,
        notes=body.notes,
    )


@app.get("/api/plans/{plan_id}")
def get_plan_endpoint(plan_id: str):
    from agent import plan_store
    p = plan_store.get_plan(plan_id)
    if not p:
        raise HTTPException(status_code=404, detail=f"Plan not found: {plan_id}")
    return p


@app.patch("/api/plans/{plan_id}")
def update_plan_endpoint(plan_id: str, body: PlanUpdateRequest):
    from agent import plan_store
    try:
        return plan_store.update_plan(
            plan_id=plan_id,
            status=body.status,
            approver=body.approver,
            notes=body.notes,
            new_inputs=body.inputs,
            new_allocations=body.allocations,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Plan not found: {plan_id}")
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@app.post("/api/plans/{plan_id}/approve")
def approve_plan_endpoint(plan_id: str, body: PlanApproveRequest):
    from agent import plan_store
    try:
        return plan_store.update_plan(
            plan_id=plan_id,
            status="approved",
            approver=body.approver,
            notes=body.notes,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Plan not found: {plan_id}")
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


# ---- Live NOAA/NHC & NWS Active Feeds (Layer 1 Ingestion) ----

@app.get("/api/live/status")
def live_status():
    """Operational status and connectivity of live NOAA NHC and NWS feed ingestion."""
    from hurricane.live_feed import get_poller
    return get_poller().poll()


@app.get("/api/live/storms")
def live_storms():
    """Currently active tropical cyclones in Atlantic, Gulf, and East Pacific from NOAA NHC."""
    from hurricane.live_feed import get_poller
    return get_poller().get_active_storms()


@app.get("/api/live/alerts")
def live_alerts(fips: str | None = Query(None)):
    """Active NWS tropical cyclone, hurricane, and storm surge watches and warnings."""
    from hurricane.live_feed import get_poller
    return get_poller().get_active_alerts(fips=fips)


@app.get("/api/live/threat/{fips}")
def live_threat(fips: str):
    """Assess active NOAA storm and NWS alert threat level for a county."""
    from hurricane import store
    from hurricane.live_feed import get_poller
    try:
        p = store.pack(fips)
        centroid = p["profile"]["centroid"]
        return get_poller().assess_county_threat(fips, centroid["lat"], centroid["lon"])
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"County not found or threat assessment failed: {e}")


# Production: serve the built React app from the same origin as /api (no CORS).
# Mounted last so /api routes win. Absent in dev, where Vite serves the UI.
STATIC_DIR = Path(os.getenv("STATIC_DIR", Path(__file__).resolve().parent.parent / "frontend" / "dist"))
if STATIC_DIR.is_dir():
    from fastapi.staticfiles import StaticFiles
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="ui")
