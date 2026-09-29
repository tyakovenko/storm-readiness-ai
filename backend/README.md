# Agent demo (Workstream C)

A basic agent + trust layer with a React chat UI. All tools return **stub data** until the data and optimization engines land.

To run it, follow [Run the demo on your laptop](../README.md#run-the-demo-on-your-laptop) in the main README.

## How it fits together

```
React (frontend/src/App.jsx) ──POST /api/chat──► FastAPI (app.py)
                                                   └─ agent/loop.py      tool-calling loop, regenerate once on a trust block
                                                        ├─ agent/llm.py        LLM_MODEL config; LiteLLM or mock; fails loudly at startup
                                                        ├─ agent/tools.py      tool schemas + functions (stubbed)
                                                        ├─ agent/contracts.py  output shape per tool, validated on every call
                                                        ├─ agent/stub_data.py  fake data; replace with real engines
                                                        ├─ agent/trust.py      numbers, required steps, confidence vs lead time
                                                        └─ agent/judge.py      actionable check (LLM judge, optional, non-blocking)
```

To plug in a real engine, replace a function in `tools.py` and keep its output keys; `contracts.py` enforces them. Field-by-field sources: [`docs/data-contract.md`](../docs/data-contract.md).

Tests (mock mode, no key): `.venv/bin/pytest -q`

## Not built yet (to decide as a team)

- Agent framework: this is a plain loop; Google ADK is still an option
- Trust checks: calibrate confidence thresholds; validate the judge on a human-labeled sample
- Replay clock (only data known at advisory time)
- Map, three user views, review/approve flow (Workstream D)
