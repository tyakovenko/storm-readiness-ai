"""LLM clients. The model is a config setting (CLAUDE.md rule 6).

LLM_MODEL in .env picks the client:
  - a LiteLLM model string, e.g. "anthropic/claude-opus-5" or "gemini/gemini-2.5-pro"
  - "mock": the scripted demo client in mock_llm.py (no key, no network)
There is no silent fallback between them (rule 5): a bad config stops startup.
"""

import json
import logging
import os
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

MAX_TOKENS = 16000
TIMEOUT_S = 120


class ConfigError(RuntimeError):
    pass


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class Turn:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    raw: dict = field(default_factory=dict)  # assistant message to append to history


class LiteLLMClient:
    def __init__(self, model: str):
        import litellm

        self._litellm = litellm
        self.model = model

    def complete(self, messages: list[dict], tools: list[dict]) -> Turn:
        resp = self._litellm.completion(
            model=self.model, messages=messages, tools=tools,
            max_tokens=MAX_TOKENS, timeout=TIMEOUT_S,
        )
        msg = resp.choices[0].message
        calls = []
        for tc in msg.tool_calls or []:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError as e:
                raise RuntimeError(f"Model returned invalid JSON for {tc.function.name}: {e}") from e
            calls.append(ToolCall(tc.id, tc.function.name, args))
        # Keep the full message (incl. thinking blocks) so multi-step tool use stays valid.
        return Turn(msg.content or "", calls, msg.model_dump(exclude_none=True))

    def check_tool_calling(self) -> None:
        ping = {"type": "function", "function": {
            "name": "ping", "description": "Startup check.",
            "parameters": {"type": "object", "properties": {}, "required": []}}}
        turn = self.complete([{"role": "user", "content": "Startup check: call the ping tool."}], [ping])
        if not any(c.name == "ping" for c in turn.tool_calls):
            raise ConfigError(f"{self.model} did not make a tool call at startup; tool calling is required.")


def build_llm():
    model = os.environ.get("LLM_MODEL", "").strip()
    if not model:
        raise ConfigError(
            "LLM_MODEL is not set. In .env, set LLM_MODEL=mock for the scripted demo, "
            "or a LiteLLM model such as LLM_MODEL=anthropic/claude-opus-5 (plus its API key).")
    if model == "mock":
        from .mock_llm import MockLLM

        log.warning("LLM_MODEL=mock: running the scripted demo client, not a real LLM")
        return MockLLM()

    import litellm

    env = litellm.validate_environment(model=model)
    if not env.get("keys_in_environment"):
        raise ConfigError(f"Missing credentials for {model}: {env.get('missing_keys')}. Add them to .env.")
    client = LiteLLMClient(model)
    client.check_tool_calling()
    log.info("LLM ready: %s (tool calling verified)", model)
    return client
