"""Actionable check: an LLM judge with a written rubric (proposal §4.5).

Non-blocking by design: it flags answers for the human reviewer, never hides
them. Its verdicts are UNVALIDATED until it is scored against a human-labeled
sample; the detail text says so, and the UI shows it as a flag only.

JUDGE_MODEL in .env (a LiteLLM model string) turns it on. Unset -> the check is
reported as "not configured" (visible, not a silent pass).
"""

import json
import logging
import os

from .llm import ConfigError, TIMEOUT_S
from .trust import Check

log = logging.getLogger(__name__)

NAME = "actionable"
MAX_TOKENS = 400

RUBRIC = """You grade answers from a storm-preparedness assistant for emergency managers.
An answer is ACTIONABLE if a reader could act on it now. It passes if at least one holds:
- it names what to do or stage, where (county, council district or facility) and how much or by when;
- the question was informational and the answer gives the facts plus the decision they inform;
- it clearly says which information is missing and which tool or person would provide it.
It fails if it is vague ("be prepared", "monitor the situation") with no concrete next step.
Do not judge whether the numbers are correct; other checks do that.

Reply with only JSON: {"actionable": true|false, "reason": "<one short sentence>"}"""


def _parse(raw: str, model: str) -> Check:
    try:
        verdict = json.loads(raw[raw.index("{"):raw.rindex("}") + 1])
        ok, reason = bool(verdict["actionable"]), str(verdict["reason"])
    except (ValueError, KeyError) as e:
        log.error("Judge %s returned unparseable output: %r (%s)", model, raw, e)
        return Check(NAME, None, False, f"Judge output unparseable; not graded ({model})")
    return Check(NAME, ok, False, f"{reason} [unvalidated LLM judge: {model}]")


class GeminiJudge:
    """Gemini on Vertex via ADC: no API key, so Cloud Run needs no extra secret."""

    def __init__(self, model: str):
        from google import genai
        self._client = genai.Client()
        self.model = model

    def grade(self, question: str, answer: str) -> Check:
        from google.genai import types
        resp = self._client.models.generate_content(
            model=self.model, contents=f"Question:\n{question}\n\nAnswer:\n{answer}",
            # Thinking off + JSON mode: with thinking on, 2.5-flash spent the token budget
            # thinking and returned truncated JSON (live run 2026-10-04).
            config=types.GenerateContentConfig(
                system_instruction=RUBRIC, max_output_tokens=MAX_TOKENS,
                response_mime_type="application/json",
                thinking_config=types.ThinkingConfig(thinking_budget=0)))
        return _parse((resp.text or "").strip(), self.model)


class Judge:
    def __init__(self, model: str):
        import litellm

        self._litellm = litellm
        self.model = model

    def grade(self, question: str, answer: str) -> Check:
        resp = self._litellm.completion(
            model=self.model, max_tokens=MAX_TOKENS, timeout=TIMEOUT_S,
            messages=[{"role": "system", "content": RUBRIC},
                      {"role": "user", "content": f"Question:\n{question}\n\nAnswer:\n{answer}"}])
        return _parse((resp.choices[0].message.content or "").strip(), self.model)


def build_judge() -> Judge | GeminiJudge | None:
    model = os.environ.get("JUDGE_MODEL", "").strip()
    if not model:
        log.warning("JUDGE_MODEL not set: the actionable check will report 'not configured'")
        return None
    if model.startswith("gemini"):  # bare Gemini id -> Vertex via ADC
        log.info("Actionable judge ready: %s (Vertex)", model)
        return GeminiJudge(model)
    import litellm

    env = litellm.validate_environment(model=model)
    if not env.get("keys_in_environment"):
        raise ConfigError(f"Missing credentials for JUDGE_MODEL={model}: {env.get('missing_keys')}")
    log.info("Actionable judge ready: %s", model)
    return Judge(model)


def not_configured() -> Check:
    return Check(NAME, None, False, "Not configured: set JUDGE_MODEL in .env to run the LLM judge")


def grade_or_report(judge, question: str, answer: str) -> Check:
    """Judge the final answer; a missing or failing judge is reported, never a silent pass."""
    if judge is None:
        return not_configured()
    try:
        return judge.grade(question, answer)
    except Exception as e:  # advisory check: surface the failure, keep the answer
        log.error("Actionable judge failed: %s", e)
        return Check(NAME, None, False, f"Judge call failed: {e}")
