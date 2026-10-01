"""FastAPI server for the agent demo.

  GET  /api/health  -> which LLM is configured
  GET  /api/overview -> tool outputs for the dashboard screens (no LLM)
  POST /api/chat    -> run the agent + trust layer on one question

Run from backend/:  uvicorn app:app --reload --port 8001
"""

import logging
from contextlib import asynccontextmanager
from typing import Literal

from dotenv import find_dotenv, load_dotenv
from fastapi import FastAPI, Query, Request
from pydantic import BaseModel, Field

load_dotenv(find_dotenv())  # finds the repo-root .env

from agent.judge import build_judge  # noqa: E402
from agent.llm import build_llm  # noqa: E402
from agent.loop import run_agent  # noqa: E402
from agent.tools import run_tool  # noqa: E402

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


@app.get("/api/overview")
def overview(max_trucks: int | None = Query(None, ge=0),
             closed: list[str] = Query(default_factory=list)):
    """Read-only data for the dashboard screens: the same tools the agent calls, no LLM.

    run_tool validates every output against contracts.py, so the screens get
    exactly the shapes the data team builds to. max_trucks/closed are the
    Resource Planner's what-if inputs, passed straight to solve_staging.
    """
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


@app.post("/api/chat")
def chat(body: ChatRequest, request: Request):
    history = [h.model_dump() for h in body.history]
    return run_agent(body.message, history, request.app.state.llm, request.app.state.judge)
