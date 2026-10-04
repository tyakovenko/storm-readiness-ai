"""FastAPI server for the agent demo.

  GET  /api/health  -> which LLM is configured
  POST /api/chat    -> run the agent + trust layer on one question

Run from backend/:  uvicorn app:app --reload --port 8001
"""

import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from dotenv import find_dotenv, load_dotenv
from fastapi import FastAPI, Request
from pydantic import BaseModel, Field

# Ensure backend directory is in sys.path
backend_dir = Path(__file__).parent.resolve()
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

load_dotenv(find_dotenv())  # finds the repo-root .env

from agent.judge import build_judge  # noqa: E402
from agent.llm import build_llm  # noqa: E402
from agent.loop import run_agent  # noqa: E402

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Fail loudly: a bad model config or missing key stops the server here.
    app.state.llm = build_llm()
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
    model = request.app.state.llm.model
    judge = request.app.state.judge
    return {"model": model, "mock": model == "mock", "judge": judge.model if judge else None}


@app.post("/api/chat")
def chat(body: ChatRequest, request: Request):
    history = [h.model_dump() for h in body.history]
    return run_agent(body.message, history, request.app.state.llm, request.app.state.judge)


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
